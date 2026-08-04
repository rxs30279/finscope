"""Read-only email delivery monitor — the query layer behind `/emails` and the
daily chart on `/email-metrics`.

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
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from admin_auth import require_admin_token
from db import query

router = APIRouter(prefix="/api/emails", tags=["emails"])

# Days are UK days, not UTC days: the digest goes out at 07:30 Europe/London
# (email_rns_digest._UK_TZ), so a UTC bucket would split a single BST send
# across two columns for nobody's benefit.
_UK_TZ = ZoneInfo("Europe/London")

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


# ── Daily metrics (the `/email-metrics` chart) ─────────────────────────────────

# Each series counts MESSAGES that ever reached that event, not events — a
# message opened four times is one open, matching how `opened`/`clicked` are
# already reported per-message on /emails.
_SERIES_EVENT = {
    "delivered": "email.delivered",
    "opened": "email.opened",
    "clicked": "email.clicked",
    "bounced": "email.bounced",
    "failed": "email.failed",
    "complained": "email.complained",
    "delayed": "email.delivery_delayed",
}

# Opens and clicks were only subscribed on the Resend webhook at ~15:00 on
# 2026-07-30, so `email_events` holds ZERO engagement rows before then even
# though Resend itself was tracking all along — and no backfill is possible
# (Replay only re-sends deliveries for event types that were subscribed at the
# time). Charting those days as 0 would read as "nobody opened it", which is
# false, so days before this date report opened/clicked as null and the chart
# breaks the line instead of drawing a floor. The 30th is excluded because it
# is half-tracked: its 07:30 cohort was live for only part of its open window.
_ENGAGEMENT_TRACKED_FROM = date(2026, 7, 31)


def _cohort_day(msg: dict) -> date | None:
    """The UK date a message went out — every event on it, however late, is
    attributed here. Cohort-by-send-day (not by event day) is what makes the
    rates readable: `opened` on 04 Aug is a share of THAT morning's delivered,
    rather than of whatever happened to be delivered the day the open landed."""
    ts = msg.get("sent_at") or msg.get("last_event_at")
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_UK_TZ).date()


def _rates(totals: dict, engagement_delivered: int) -> dict:
    """Deliverability is of everything sent; engagement is of what actually
    landed — an open rate diluted by undeliverable addresses measures the list,
    not the mail. Engagement takes its own denominator because the untracked
    stretch has to come out of both halves of the fraction, not just the top."""
    sent = totals.get("messages") or 0
    pct = lambda n, d: round(100 * n / d, 1) if d else None  # noqa: E731
    return {
        "delivered": pct(totals.get("delivered") or 0, sent),
        "bounced": pct(totals.get("bounced") or 0, sent),
        "failed": pct(totals.get("failed") or 0, sent),
        "complained": pct(totals.get("complained") or 0, sent),
        "delayed": pct(totals.get("delayed") or 0, sent),
        "opened": pct(totals.get("opened") or 0, engagement_delivered),
        "clicked": pct(totals.get("clicked") or 0, engagement_delivered),
    }


@router.get("/metrics")
def daily_metrics(
    days: int = 15,
    provider: str | None = None,
    domain: str | None = None,
    _admin: None = Depends(require_admin_token),
) -> dict:
    """Per-day message counts for the `/email-metrics` chart.

    Every day in the window is emitted, including days with no send at all —
    the digest is weekdays-only, so dropping empty days would quietly close the
    weekend gaps and make a five-day cadence look continuous.
    """
    days = max(1, min(days, 90))
    today = datetime.now(timezone.utc).astimezone(_UK_TZ).date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    first_day = window[0]

    # One extra day of events: a message sent just outside the window can still
    # be the parent of an event inside it, and _MSGS_SQL filters on event time
    # while the buckets below key on send time. Cohorts outside `window` are
    # dropped after classification.
    rows = query(_MSGS_SQL, {"days": days + 1})

    buckets = {d: {"day": d.isoformat(), "messages": 0, **{s: 0 for s in _SERIES_EVENT}} for d in window}
    totals = {"messages": 0, **{s: 0 for s in _SERIES_EVENT}}
    domains: dict[str, int] = {}

    for r in rows:
        if provider and r.get("provider") != provider:
            continue
        if domain and r.get("recipient_domain") != domain:
            continue
        day = _cohort_day(r)
        if day is None or day not in buckets:
            continue
        types = set(r.get("event_types") or [])
        bucket = buckets[day]
        bucket["messages"] += 1
        totals["messages"] += 1
        for series, event_type in _SERIES_EVENT.items():
            if event_type in types:
                bucket[series] += 1
                totals[series] += 1
        dom = r.get("recipient_domain")
        if dom:
            domains[dom] = domains.get(dom, 0) + 1

    # Null out engagement before it was being recorded — see the constant — and
    # take those days out of the opened/clicked totals too. A total the chart
    # can't draw is worse than no total: the legend would claim 105 opens over a
    # window whose visible points only ever add up to 95.
    for day, bucket in buckets.items():
        if day < _ENGAGEMENT_TRACKED_FROM:
            totals["opened"] -= bucket["opened"]
            totals["clicked"] -= bucket["clicked"]
            bucket["opened"] = None
            bucket["clicked"] = None

    tracked = [d for d in window if d >= _ENGAGEMENT_TRACKED_FROM]
    engagement_base = sum(buckets[d]["messages"] for d in tracked)
    engagement_delivered = sum(buckets[d]["delivered"] for d in tracked)

    return {
        "days": days,
        "start": first_day.isoformat(),
        "end": today.isoformat(),
        "series": list(_SERIES_EVENT),
        "points": [buckets[d] for d in window],
        "totals": totals,
        "rates": _rates(totals, engagement_delivered),
        # Engagement rates recomputed over the tracked days only, so the
        # headline open rate isn't halved by the untracked stretch.
        "engagement": {
            "tracked_from": _ENGAGEMENT_TRACKED_FROM.isoformat(),
            "fully_tracked": first_day >= _ENGAGEMENT_TRACKED_FROM,
            "messages": engagement_base,
            "delivered": engagement_delivered,
            "opened": totals["opened"],
            "clicked": totals["clicked"],
        },
        "domains": [
            {"domain": d, "messages": n}
            for d, n in sorted(domains.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
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
