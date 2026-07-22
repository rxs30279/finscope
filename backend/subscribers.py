"""Email subscription endpoints — signup + unsubscribe.

The `subscribers` table (migration 019) is the source of truth for the list.
It used to be Resend's Segments + Contacts API; that made the list unqueryable
from SQL, put a network call in the path of every signup and every digest send,
and tied application state to the email vendor — see migrate_subscribers.py for
the one-off move.

Endpoints:
  POST /api/subscribers/signup           — body {"email": "..."}
  GET  /api/unsubscribe?email=&t=        — confirmation page + unsub (HMAC-signed)
  POST /api/unsubscribe                  — RFC 8058 one-click unsub
  POST /api/subscribers/unsubscribe-self — website form; emails the signed link

Env:
  UNSUBSCRIBE_SECRET    — random hex string for HMAC token signing
  MAX_SUBSCRIBERS       — hard cap on the active list (default 100)
  SUBSCRIBER_COUNT_FLOOR— display-only seed for the scarcity counter (default 22)
"""
import os
import re
import time
import hmac
import hashlib
import urllib.parse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from db import connection, query
from request_utils import client_ip, SlidingWindowLimiter


router = APIRouter()

# Simple email shape check — full RFC 5322 validation is not worth the
# email-validator dependency, and the send path rejects malformed addresses.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


# ── Token signing ─────────────────────────────────────────────────────────────

def _unsubscribe_token(email: str) -> str:
    secret = os.environ.get("UNSUBSCRIBE_SECRET")
    if not secret:
        raise HTTPException(500, "UNSUBSCRIBE_SECRET not configured")
    mac = hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256)
    return mac.hexdigest()[:32]


def _verify_token(email: str, token: str) -> bool:
    try:
        expected = _unsubscribe_token(email)
    except HTTPException:
        return False
    return hmac.compare_digest(expected, token)


# Hard cap on the active subscriber list. Surfaced as a scarcity message on the
# signup forms; enforced here so the claim is real. Overridable via env without
# a code change (default 100).
def _max_subscribers() -> int:
    try:
        return int(os.environ.get("MAX_SUBSCRIBERS", "100"))
    except ValueError:
        return 100


# ── Signup ────────────────────────────────────────────────────────────────────

class SignupBody(BaseModel):
    email: str


@router.post("/api/subscribers/signup")
def signup(body: SignupBody):
    """Add the address to the list, or re-activate it if it unsubscribed
    earlier. Single opt-in — instantly subscribed."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")

    # Capacity gate. An address that's already an active subscriber is
    # idempotent and never blocked; only a genuinely new (or returning,
    # previously-unsubscribed) address is rejected once the list is full.
    cap = _max_subscribers()
    try:
        already_unsubscribed = _is_unsubscribed(email)
    except RuntimeError as e:
        raise HTTPException(502, f"Subscriber lookup failed: {e}")
    if already_unsubscribed is False:  # existing row, currently active
        return {"ok": True, "status": "subscribed"}
    try:
        count = active_count()
    except RuntimeError as e:
        raise HTTPException(502, f"Subscriber lookup failed: {e}")
    if count >= cap:
        raise HTTPException(
            403,
            f"Sign-ups are full — all {cap} spots have been taken. "
            "Check back soon; we open more from time to time.",
        )

    # One statement covers both cases the Resend version needed a
    # create-then-PATCH-on-409 dance for. RETURNING tells us which happened:
    # xmax = 0 identifies a freshly inserted row, so a returning subscriber is
    # reported as "reactivated" exactly as before.
    try:
        with connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO subscribers (email, unsubscribed, source)
                VALUES (%s, FALSE, 'signup')
                ON CONFLICT (email) DO UPDATE
                    SET unsubscribed = FALSE,
                        resubscribed_at = CASE WHEN subscribers.unsubscribed
                                               THEN NOW()
                                               ELSE subscribers.resubscribed_at END
                RETURNING (xmax = 0) AS inserted
                """,
                (email,),
            )
            inserted = bool(cur.fetchone()[0])
            conn.commit()
    except Exception as e:
        raise HTTPException(502, f"Could not save subscription: {e}")

    _count_cache["data"] = None  # the scarcity counter just went stale
    return {"ok": True, "status": "subscribed" if inserted else "reactivated"}


# ── Live count (scarcity counter) ─────────────────────────────────────────────

# Every landing visitor reads this, so cache it in-process. Cheaper than it was
# against Resend but still a round trip to Supabase on a page that renders
# before anything else. Hosted on a long-lived process (Hetzner), so the module
# cache survives across requests; a short TTL keeps the number fresh enough.
_COUNT_TTL = 60.0
_count_cache: dict = {"ts": 0.0, "data": None}


# Scarcity-counter seeding. The *displayed* "taken" count is floored to this so
# the landing page shows visible traction while the real list is still small
# (default 22 → "78 of 100 free spots left"). This affects the DISPLAY ONLY —
# the real capacity gate in signup() counts genuine subscribers, so seeding can
# never block or double-count a real sign-up. Tunable via env with no redeploy:
# lower it any time to reset the number (e.g. back to 78) if it creeps too high.
def _count_floor() -> int:
    try:
        return max(0, int(os.environ.get("SUBSCRIBER_COUNT_FLOOR", "22")))
    except ValueError:
        return 22


@router.get("/api/subscribers/count")
def subscriber_count():
    """Public: active subscriber count + the cap, for the scarcity counter on
    the signup forms. Cached `_COUNT_TTL` seconds; serves stale on a DB error
    rather than failing the whole landing page."""
    now = time.time()
    cached = _count_cache["data"]
    if cached is not None and now - _count_cache["ts"] < _COUNT_TTL:
        return cached

    cap = _max_subscribers()
    try:
        real = active_count()
    except RuntimeError as e:
        if cached is not None:
            return cached
        raise HTTPException(502, f"Subscriber lookup failed: {e}")

    # Seed the displayed count with the floor for social proof, but never let
    # the floor alone show "full" — the form closes only when GENUINE
    # subscribers fill the list. While real < cap we always leave ≥1 spot
    # showing (ceiling cap-1), so seeding can't prematurely disable signups.
    count = max(real, _count_floor())
    if real < cap:
        count = min(count, cap - 1)
    data = {"count": count, "cap": cap, "remaining": max(0, cap - count)}
    _count_cache["ts"] = now
    _count_cache["data"] = data
    return data


# ── Unsubscribe ───────────────────────────────────────────────────────────────

_PAGE_OK = """<!doctype html><html><head><meta charset="utf-8">
<title>Unsubscribed · Alpha Move AI</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head><body style="margin:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
<div style="max-width:520px;margin:80px auto;padding:32px;background:#fff;border:1px solid #eee;border-radius:6px;text-align:center;">
  <h1 style="margin:0 0 12px;font-family:monospace;color:#f97316;letter-spacing:2px;font-size:16px;text-transform:uppercase;">Alpha Move AI</h1>
  <div style="height:2px;background:#f97316;width:60px;margin:0 auto 24px;"></div>
  <p style="color:#222;font-size:15px;line-height:1.5;">You've been unsubscribed.</p>
  <p style="color:#666;font-size:13px;line-height:1.5;">{email} will no longer receive the daily RNS digest.</p>
  <p style="margin-top:24px;color:#999;font-size:12px;">Changed your mind? <a href="/subscribe" style="color:#f97316;">Sign up again</a>.</p>
</div></body></html>"""

_PAGE_BAD = """<!doctype html><html><head><meta charset="utf-8">
<title>Invalid link · Alpha Move AI</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head><body style="margin:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
<div style="max-width:520px;margin:80px auto;padding:32px;background:#fff;border:1px solid #eee;border-radius:6px;text-align:center;">
  <h1 style="margin:0 0 12px;font-family:monospace;color:#f97316;letter-spacing:2px;font-size:16px;text-transform:uppercase;">Alpha Move AI</h1>
  <p style="color:#222;font-size:15px;line-height:1.5;">This unsubscribe link is invalid or expired.</p>
  <p style="margin-top:24px;color:#999;font-size:12px;"><a href="/subscribe" style="color:#f97316;">Manage subscription</a></p>
</div></body></html>"""


def _do_unsubscribe(email: str) -> None:
    """Flag the address as unsubscribed. Never deletes the row — see the
    migration-019 header.

    An address with no row is silently fine: the UPDATE matches nothing and the
    caller still sees the success page. That mirrors the old Resend 404 handling
    and is the right answer anyway — telling an unrecognised address that it was
    never subscribed would leak list membership to anyone with a valid token.
    """
    try:
        with connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE subscribers
                   SET unsubscribed = TRUE, unsubscribed_at = NOW()
                 WHERE email = %s AND NOT unsubscribed
                """,
                (email.lower(),),
            )
            conn.commit()
    except Exception as e:
        raise HTTPException(502, f"Could not unsubscribe: {e}")

    _count_cache["data"] = None  # the scarcity counter just went stale


@router.get("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe_get(email: str = Query(...), t: str = Query(...)):
    email = email.lower()
    if not _verify_token(email, t):
        return HTMLResponse(_PAGE_BAD, status_code=400)
    _do_unsubscribe(email)
    return HTMLResponse(_PAGE_OK.format(email=email))


@router.post("/api/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_post(request: Request):
    """RFC 8058 one-click endpoint. Mail clients POST here with the
    email + token in either form-encoded body or query string."""
    email = request.query_params.get("email")
    token = request.query_params.get("t")

    if not (email and token):
        try:
            form = await request.form()
            email = email or form.get("email")
            token = token or form.get("t")
        except Exception:
            pass

    if not (email and token):
        return HTMLResponse(_PAGE_BAD, status_code=400)

    email = email.lower()
    if not _verify_token(email, token):
        return HTMLResponse(_PAGE_BAD, status_code=400)

    _do_unsubscribe(email)
    return HTMLResponse(_PAGE_OK.format(email=email))


class UnsubSelfBody(BaseModel):
    email: str


# Each accepted request may send a confirmation email, so damp scripted abuse.
_unsub_limiter = SlidingWindowLimiter(limit=3, window_seconds=600)


@router.post("/api/subscribers/unsubscribe-self")
def unsubscribe_self(body: UnsubSelfBody, request: Request):
    """User-initiated unsubscribe from the website form.

    Typing an address into a form proves nothing — acting on it directly would
    let anyone silently unsubscribe anyone else. So this emails the address its
    signed one-click unsubscribe link (the same HMAC link the digest footer
    carries): only the inbox owner can complete it.

    The response is identical whether or not the address is subscribed, so the
    form can't be used to probe who's on the list; the email itself is only
    sent to genuine active subscribers, so the form can't be used to spam
    strangers either.
    """
    if not _unsub_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests — please wait a few minutes and try again")

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")

    try:
        active = list_active_contacts()
    except RuntimeError as e:
        raise HTTPException(502, f"Subscriber lookup failed: {e}")

    if any((c.get("email") or "").lower() == email for c in active):
        url = build_unsubscribe_url(email)
        from emailer import EmailSendError, send_email
        try:
            send_email(
                to=email,
                subject="Confirm your unsubscribe — Alpha Move AI",
                text=(
                    "Someone (hopefully you) asked to unsubscribe this address from "
                    "the Alpha Move AI daily digest.\n\n"
                    f"Click to confirm: {url}\n\n"
                    "If this wasn't you, ignore this email and nothing changes."
                ),
                html=(
                    '<div style="font-family:monospace;font-size:14px;color:#111;">'
                    "<p>Someone (hopefully you) asked to unsubscribe this address "
                    "from the Alpha Move AI daily digest.</p>"
                    f'<p><a href="{url}">Confirm unsubscribe</a></p>'
                    '<p style="color:#666;">If this wasn\'t you, ignore this email '
                    "and nothing changes.</p></div>"
                ),
            )
        except EmailSendError as e:
            # 502, matching the old relay: the form must not report success for
            # a confirmation email that never left.
            raise HTTPException(502, f"Could not send confirmation email: {e}") from e

    return {"ok": True, "status": "confirmation_sent"}


# ── Helper exported for the digest sender ─────────────────────────────────────

def build_unsubscribe_url(email: str) -> str:
    """Return the public one-click unsubscribe URL for the given email.
    Used by email_rns_digest.py to insert into per-recipient List-Unsubscribe
    headers and HTML footers."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        # Fallback: relative URL works inside the app but not in emails.
        base = ""
    token = _unsubscribe_token(email)
    qs = urllib.parse.urlencode({"email": email.lower(), "t": token})
    return f"{base}/api/unsubscribe?{qs}"


def active_count() -> int:
    """COUNT of active (not-unsubscribed) subscribers.

    Used wherever only the number is needed (the capacity gate, the scarcity
    counter) so those paths don't pull the whole list over the wire just to
    call len() on it. list_active_contacts() stays the one used by the digest
    sender, which genuinely needs every row.
    """
    try:
        rows = query("SELECT COUNT(*) AS n FROM subscribers WHERE NOT unsubscribed")
    except Exception as e:
        raise RuntimeError(f"subscribers count failed: {e}") from e
    return int(rows[0]["n"]) if rows else 0


def _is_unsubscribed(email: str) -> bool | None:
    """The address's current `unsubscribed` flag, or None if it has no row.

    Used by signup() to tell "already active" from "new or returning" without
    loading the whole active list to scan for membership.
    """
    try:
        rows = query("SELECT unsubscribed FROM subscribers WHERE email = %s", (email,))
    except Exception as e:
        raise RuntimeError(f"subscribers lookup failed: {e}") from e
    return bool(rows[0]["unsubscribed"]) if rows else None


def list_active_contacts() -> list[dict]:
    """Return every subscriber that has NOT unsubscribed, oldest first.
    Used by email_rns_digest.py to populate the recipient list.

    Keeps the `[{"email": ...}]` shape the Resend version returned so callers
    are unaffected by the move, and keeps raising RuntimeError on failure —
    signup(), subscriber_count() and unsubscribe_self() all catch that
    specific type and turn it into a 502.
    """
    try:
        rows = query(
            "SELECT email FROM subscribers "
            "WHERE NOT unsubscribed ORDER BY created_at"
        )
    except Exception as e:
        raise RuntimeError(f"subscribers query failed: {e}") from e
    return [{"email": r["email"]} for r in rows]
