"""Resend delivery-event webhook.

Resend POSTs one event per delivery transition (email.sent → email.delivered →
email.opened, or email.delivery_delayed / email.bounced / email.complained when
things go wrong). Until this existed nothing in the app recorded them: the
Resend API only exposes `last_event` on the current message, so history is lost
the moment an event is superseded, and a deferral was only noticeable if a
recipient happened to mention their digest arrived late.

That is exactly what happened on 21 Jul 2026 — 6 of 9 Microsoft recipients
(hotmail/outlook) soft-deferred while all 45 other recipients delivered on time.
Events land in the `email_events` table (migration 018) so the pattern is
visible in /api/status instead of anecdotal.

Deliberately record-only: it does NOT auto-unsubscribe on bounce. Resend already
maintains its own account-level suppression list for hard bounces, so acting
here would be a second, divergent source of truth for who is subscribed — and
the subscriber list itself lives in Resend's segment, not our DB (subscribers.py).

Endpoint:
  POST /api/webhooks/resend   — Svix-signed; configure in the Resend dashboard

Env:
  RESEND_WEBHOOK_SECRET  — required, the `whsec_...` signing secret Resend shows
                           when you create the endpoint. Without it the route
                           fails closed (503) rather than trusting the caller.

Retention: ~150 rows/day at current list size. No pruning policy exists yet —
`/emails` (email_monitor.py) reads a user-selectable window (up to 30 days
today), so a dated DELETE keyed to the /status window would silently remove
data that page still serves. Any future pruning needs to key off the widest
window either surface can request.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

import psycopg2.extras
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from db import connection, query


router = APIRouter()

# Svix rejects anything older than this, and so do we — without it a captured
# request body stays replayable forever, since the signature never expires.
_TOLERANCE_SECONDS = 5 * 60

# Per-event-type sub-objects worth keeping. The rest of the payload is either
# already columns (to/subject/created_at) or noise, so `detail` stays small and
# queryable instead of being a dump of the whole body.
_DETAIL_KEYS = ("bounce", "failed", "click", "complaint")

# Resend's click sub-object carries ipAddress + userAgent. Keep the link, drop
# the personal data — email_events has no retention policy, so anything stored
# here is stored indefinitely, and nothing downstream ever needs to know more
# than which link was clicked.
_CLICK_KEEP = ("link", "timestamp")


# ── Signature verification (Standard Webhooks / Svix, stdlib only) ────────────

def _headers(request: Request) -> tuple[str, str, str]:
    """Pull the id/timestamp/signature triple.

    Resend sends the `svix-*` spelling today, but the underlying Standard
    Webhooks spec defines `webhook-*` and Svix accepts both — read either so a
    provider-side rename doesn't silently start rejecting every event.
    """
    h = request.headers
    msg_id = h.get("svix-id") or h.get("webhook-id") or ""
    timestamp = h.get("svix-timestamp") or h.get("webhook-timestamp") or ""
    signature = h.get("svix-signature") or h.get("webhook-signature") or ""
    return msg_id, timestamp, signature


def _verify(secret: str, msg_id: str, timestamp: str, signature: str, body: bytes) -> None:
    """Raise HTTPException(401) unless `signature` is a valid Svix signature.

    Signed content is `{id}.{timestamp}.{raw_body}` — the body must be the exact
    bytes received, which is why the endpoint reads request.body() rather than
    letting FastAPI parse a model (re-serialising JSON reorders keys and breaks
    the MAC).
    """
    if not (msg_id and timestamp and signature):
        raise HTTPException(401, "Missing webhook signature headers")

    try:
        sent_at = int(timestamp)
    except ValueError:
        raise HTTPException(401, "Malformed webhook timestamp")
    if abs(time.time() - sent_at) > _TOLERANCE_SECONDS:
        raise HTTPException(401, "Webhook timestamp outside tolerance")

    # whsec_<base64>; the prefix is a label, not part of the key material.
    raw_secret = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw_secret)
    except Exception:
        raise HTTPException(503, "RESEND_WEBHOOK_SECRET is not valid base64")

    signed = b"%s.%s." % (msg_id.encode(), timestamp.encode()) + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()

    # Header carries a space-separated list of versioned signatures ("v1,<sig>
    # v1,<sig>") — during a secret rotation more than one is live at once, so
    # any match is a pass.
    for part in signature.split():
        version, _, candidate = part.partition(",")
        if version == "v1" and hmac.compare_digest(candidate, expected):
            return
    raise HTTPException(401, "Invalid webhook signature")


# ── Payload → row ─────────────────────────────────────────────────────────────

def _parse_ts(value) -> datetime | None:
    """Resend timestamps arrive as ISO 8601, sometimes with a trailing Z and
    sometimes as a naive 'YYYY-MM-DD HH:MM:SS.ffffff+00'. Normalise to aware UTC
    so lag arithmetic in SQL never compares across tz-awareness."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row(payload: dict, svix_id: str) -> dict | None:
    """Flatten a Resend event into the email_events shape, or None if it isn't
    a recognisable email event (Svix ping/test deliveries land here too).

    The Svix delivery id lands in the generic `event_id` column — SES's
    equivalent (the SNS MessageId) shares it, see migration 020.
    """
    event_type = payload.get("type")
    data = payload.get("data")
    if not event_type or not isinstance(data, dict):
        return None

    email_id = data.get("email_id") or data.get("id")
    if not email_id:
        return None

    to = data.get("to")
    recipient = None
    if isinstance(to, list) and to:
        recipient = str(to[0]).strip().lower()
    elif isinstance(to, str):
        recipient = to.strip().lower()

    domain = recipient.split("@")[-1] if recipient and "@" in recipient else None

    detail = {k: data[k] for k in _DETAIL_KEYS if k in data}
    if "click" in detail and isinstance(detail["click"], dict):
        detail["click"] = {k: v for k, v in detail["click"].items() if k in _CLICK_KEEP}

    return {
        "event_id": svix_id,
        "provider": "resend",
        "email_id": str(email_id),
        "event_type": str(event_type),
        "recipient": recipient,
        "recipient_domain": domain,
        "subject": data.get("subject"),
        # Top-level created_at is when the *event* fired; data.created_at is when
        # the message was accepted. Fall back to now() only if the payload omits
        # both, so occurred_at is never NULL (it's the primary sort key).
        "occurred_at": _parse_ts(payload.get("created_at"))
                       or _parse_ts(data.get("created_at"))
                       or datetime.now(timezone.utc),
        "email_created_at": _parse_ts(data.get("created_at")),
        "detail": detail or None,
    }


def _insert(row: dict) -> None:
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO email_events (
                event_id, provider, email_id, event_type, recipient,
                recipient_domain, subject, occurred_at, email_created_at, detail
            ) VALUES (%(event_id)s, %(provider)s, %(email_id)s, %(event_type)s,
                      %(recipient)s, %(recipient_domain)s, %(subject)s,
                      %(occurred_at)s, %(email_created_at)s, %(detail)s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            {**row, "detail": psycopg2.extras.Json(row["detail"]) if row["detail"] else None},
        )
        conn.commit()


def _maybe_record_bounce(row: dict) -> None:
    """Stamp subscribers.bounced_at for a permanent bounce.

    Mirrors ses_events._maybe_record_bounce (same table, same first-bounce-wins
    UPDATE) — the two providers just spell the bounce sub-object differently:
    Resend uses type/subType/message, SES uses bounceType/bounceSubType/
    bouncedRecipients[0].diagnosticCode. Best-effort: email_events already has
    its row by the time this runs, so a failure here must not surface as a
    webhook failure (Svix would retry an event we already stored).
    """
    bounce = (row.get("detail") or {}).get("bounce") or {}
    if bounce.get("type") != "Permanent":
        return
    recipient = row.get("recipient")
    if not recipient:
        return
    reason = bounce.get("message") or f"{bounce.get('type')}/{bounce.get('subType')}"
    try:
        from ses_events import _record_bounce  # local: avoid a module-load cycle
        _record_bounce(recipient, row["occurred_at"], reason)
    except Exception as e:
        print(f"[email-events] WARNING: bounced_at stamp failed for {recipient}: {e}")


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/api/webhooks/resend")
async def resend_webhook(request: Request):
    """Ingest one Resend delivery event.

    Async purely to get at the raw body for signature verification; the DB write
    is pushed to the threadpool so a burst of events (the digest fires ~150 in a
    few minutes) can't stall the event loop on psycopg2's blocking socket.

    Always 200s once the signature checks out, including for payload shapes we
    don't recognise — a non-2xx makes Svix retry with backoff for hours, and
    there is nothing to gain from retrying an event we will never parse.
    """
    secret = os.environ.get("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        # Fail closed: an unauthenticated writer could otherwise forge delivery
        # history. 503 (not 403) because this is our misconfiguration, not theirs.
        raise HTTPException(503, "RESEND_WEBHOOK_SECRET not configured")

    body = await request.body()
    msg_id, timestamp, signature = _headers(request)
    _verify(secret, msg_id, timestamp, signature, body)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Body is not valid JSON")

    row = _row(payload, msg_id)
    if row is None:
        return {"ok": True, "stored": False, "reason": "not an email event"}

    await run_in_threadpool(_insert, row)
    if row["event_type"] == "email.bounced":
        await run_in_threadpool(_maybe_record_bounce, row)
    return {"ok": True, "stored": True, "event": row["event_type"]}


# ── /status panel ─────────────────────────────────────────────────────────────

# Consumer mailbox providers that throttle as a group. Microsoft is the one that
# actually bites here, but grouping the others keeps the panel readable when a
# different provider starts deferring.
_PROVIDERS = {
    "microsoft": ("hotmail.", "outlook.", "live.", "msn."),
    "google":    ("gmail.", "googlemail."),
    "apple":     ("icloud.", "me.", "mac."),
}

_PROBLEM_EVENTS = ("email.delivery_delayed", "email.bounced", "email.complained", "email.failed")


def provider_of(domain: str | None) -> str:
    """Bucket a recipient domain into a mailbox provider, else 'other'."""
    if not domain:
        return "other"
    d = domain.lower()
    for name, prefixes in _PROVIDERS.items():
        if any(d.startswith(p) for p in prefixes):
            return name
    return "other"


def recent_summary(days: int = 7) -> dict:
    """Delivery-problem rollup for the admin /status page.

    Reports per-provider problem *rate* rather than raw counts: 6 delayed means
    nothing without knowing it was 6 of 9 Microsoft recipients against 0 of 45
    everyone else, which is the shape that identifies provider-side throttling.

    Counts distinct messages, NOT events. One email emits several events
    (sent → delivered, or sent → delivery_delayed → delivered), so an
    event-denominated rate silently dilutes as more event types are subscribed
    — today's incident would read 6/24 instead of 6/9. A message counts as
    problematic if it ever emitted a problem event, even if it landed later:
    "arrived, but hours late" is the thing being tracked.
    """
    rows = query(
        """
        SELECT recipient_domain,
               COUNT(DISTINCT email_id) AS messages,
               COUNT(DISTINCT email_id)
                 FILTER (WHERE event_type = ANY(%(problems)s)) AS problem_messages,
               MAX(occurred_at)
                 FILTER (WHERE event_type = ANY(%(problems)s)) AS latest_problem,
               MAX(occurred_at) AS latest_event
        FROM email_events
        WHERE occurred_at >= NOW() - (%(days)s || ' days')::INTERVAL
        GROUP BY recipient_domain
        """,
        {"problems": list(_PROBLEM_EVENTS), "days": days},
    )

    by_provider: dict[str, dict] = {}
    latest_event = None
    for r in rows:
        bucket = by_provider.setdefault(
            provider_of(r["recipient_domain"]),
            {"messages": 0, "problems": 0, "latest_problem": None},
        )
        # Safe to sum across domains: a row is stored per recipient (to[0]), so
        # one message never spans two domains and the distinct counts can't
        # double-count within a provider.
        bucket["messages"] += int(r["messages"] or 0)
        bucket["problems"] += int(r["problem_messages"] or 0)
        latest = r["latest_problem"]
        if latest and (bucket["latest_problem"] is None or latest > bucket["latest_problem"]):
            bucket["latest_problem"] = latest
        seen = r["latest_event"]
        if seen and (latest_event is None or seen > latest_event):
            latest_event = seen

    for bucket in by_provider.values():
        total = bucket["messages"]
        bucket["problem_rate"] = round(bucket["problems"] / total, 3) if total else 0.0
        if bucket["latest_problem"] is not None:
            bucket["latest_problem"] = bucket["latest_problem"].isoformat()

    return {
        "days": days,
        "messages": sum(b["messages"] for b in by_provider.values()),
        "problems": sum(b["problems"] for b in by_provider.values()),
        # Lets the UI separate "no problems" from "no events at all": a webhook
        # that silently stops delivering looks perfectly healthy by rate alone.
        "latest_event": latest_event.isoformat() if latest_event else None,
        "by_provider": by_provider,
    }
