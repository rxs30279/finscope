"""Read-only email delivery monitor — the query layer behind `/emails`.

A Resend-style per-message view over `email_events` (migrations 018 + 020),
which already carries everything this needs: `provider` lets a message be
compared side-by-side across the Resend/SES parallel run, and every event on
a message already normalises into the same `email.*` vocabulary regardless of
which ingestion path wrote it.

Why a new module rather than extending `email_events.py` or `ses_events.py`:
those are the two *ingestion* paths (the Resend webhook and the SES SQS
drain); this is a *query* layer that belongs to neither. `email_events.py`
already imports `_record_bounce` from `ses_events.py` — don't deepen that
smell by bolting a third concern onto either file.

Read-only: nothing here writes to `email_events`. See
docs/email-monitor-page-plan.md for the full design rationale.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from admin_auth import require_admin_token
from db import query

router = APIRouter(prefix="/api/emails", tags=["emails"])

# Status is by precedence, not recency — deliberately unlike Resend, which
# collapses `sent -> delivery_delayed -> delivered` into "Delivered" and lets
# the lateness disappear. That late-arrival case is the entire reason
# email_events exists (the 21 Jul Microsoft incident), so a message that was
# ever delayed keeps a separate `was_delayed` flag alongside its terminal
# status — a message that was delayed and never delivered stays "delayed",
# which is more alarming than one that recovered, not less.
_STATUS_PRECEDENCE = (
    ("email.complained", "complained"),
    ("email.bounced", "bounced"),
    ("email.failed", "failed"),
    ("email.delivered", "delivered"),
    ("email.delivery_delayed", "delayed"),
)

# One row per message (GROUP BY email_id). Verified against prod 2026-07-30:
# zero email_ids span more than one recipient/subject/provider, so MAX() here
# is picking the only value each column ever holds, not guessing among several.
_MSGS_SQL = """
    SELECT
        email_id,
        MAX(provider)                                                   AS provider,
        MAX(recipient)                                                  AS recipient,
        MAX(recipient_domain)                                           AS recipient_domain,
        MAX(subject)                                                    AS subject,
        MIN(occurred_at) FILTER (WHERE event_type = 'email.sent')       AS sent_at,
        MAX(occurred_at) FILTER (WHERE event_type = 'email.delivered')  AS delivered_at,
        MAX(occurred_at)                                                AS last_event_at,
        ARRAY_AGG(DISTINCT event_type)                                  AS event_types
    FROM email_events
    WHERE occurred_at >= NOW() - (%(days)s || ' days')::INTERVAL
    GROUP BY email_id
"""


def _classify(event_types: list[str] | None) -> tuple[str, bool, bool, bool]:
    """(status, was_delayed, opened, clicked) from one message's event types."""
    types = set(event_types or [])
    status = "sent"
    for event_type, label in _STATUS_PRECEDENCE:
        if event_type in types:
            status = label
            break
    return (
        status,
        "email.delivery_delayed" in types,
        "email.opened" in types,
        "email.clicked" in types,
    )


def _load_messages(days: int) -> list[dict]:
    """One classified row per message in the window. Filtering/pagination
    happen in Python (see list_messages) rather than in SQL — at today's
    volume (~150 events/day, ~409 messages over 9 days per the plan's prod
    check) pulling the whole window is trivial, and it keeps the
    status/was_delayed logic in one place that unit tests can exercise
    without a database."""
    rows = query(_MSGS_SQL, {"days": days})
    out = []
    for r in rows:
        status, was_delayed, opened, clicked = _classify(r.get("event_types"))
        out.append({
            **{k: v for k, v in r.items() if k != "event_types"},
            "status": status,
            "was_delayed": was_delayed,
            "opened": opened,
            "clicked": clicked,
        })
    return out


def _matches(msg: dict, provider: str | None, q: str | None) -> bool:
    if provider and msg.get("provider") != provider:
        return False
    if q:
        needle = q.strip().lower()
        haystack = f"{msg.get('recipient') or ''} {msg.get('subject') or ''}".lower()
        if needle not in haystack:
            return False
    return True


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _sort_key(msg: dict) -> datetime:
    # 6 of 409 messages in prod have no email.sent event (see the plan's
    # verified-against-prod note) — COALESCE onto last_event_at is load-bearing,
    # not defensive: without it those six silently sink to the very bottom
    # regardless of how recent they actually are.
    return msg.get("sent_at") or msg.get("last_event_at") or _EPOCH


@router.get("")
def list_messages(
    days: int = 7,
    status: str | None = None,
    provider: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _admin: None = Depends(require_admin_token),
) -> dict:
    """Message list for the `/emails` admin page.

    `summary` is computed over `provider`/`q`/`days` but deliberately IGNORES
    the `status` filter, so the stat tiles above the table stay stable and
    clickable instead of collapsing to just the currently-selected status.
    """
    messages = _load_messages(days)
    scoped_by_filters = [m for m in messages if _matches(m, provider, q)]

    summary: dict[str, int] = {}
    for m in scoped_by_filters:
        summary[m["status"]] = summary.get(m["status"], 0) + 1

    displayed = [m for m in scoped_by_filters if status is None or m["status"] == status]
    displayed.sort(key=_sort_key, reverse=True)
    page = displayed[offset: offset + limit]

    return {
        "days": days,
        "total": len(displayed),
        "summary": summary,
        "messages": page,
    }


@router.get("/{email_id}")
def message_timeline(email_id: str, _admin: None = Depends(require_admin_token)) -> dict:
    """Every event for one message, ascending, with `detail` exposed for bounce
    / complaint diagnostics. Deliberately not time-bounded — an old message
    stays reachable by id even outside any list window."""
    events = query(
        """
        SELECT event_type, provider, occurred_at, email_created_at, detail
        FROM email_events
        WHERE email_id = %s
        ORDER BY occurred_at ASC
        """,
        (email_id,),
    )
    return {"email_id": email_id, "events": events}
