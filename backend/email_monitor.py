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
# Shared with /status's deliverability card so the two can't disagree about what
# counts as real mail. Defined in the ingestion module because it describes the
# table's contents, not this read model.
from email_events import EXCLUDE_SIMULATOR_SQL

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

# How far back to look for a message's own send, beyond the requested window.
# BOTH read models below filter EVENTS, not messages, so without this a late
# open on an old digest arrives as a group holding nothing but that open: the
# message loses its own sent/delivered rows, dates itself to the open, and
# materialises as a phantom send. Seen in prod twice:
#   2026-08-04, metrics — the 21 Jul digest was opened on 3 Aug and turned up as
#     a Sunday send, delivered=0 dragging that day's deliverability down with it.
#   2026-08-06, list — the 29 and 30 Jul digests, reopened together late on the
#     5th, appeared stamped "16h ago" and labelled Sent (_classify defaults to
#     "sent" when a group carries no delivered/bounced/failed row), reading as
#     duplicate sends to the same recipient.
# 30 days covers realistic late-open lag; anything older simply drops out, which
# is the correct outcome.
_COHORT_LOOKBACK_DAYS = 30

# One row per message (GROUP BY email_id). Verified against prod 2026-07-30:
# zero email_ids span more than one recipient/subject/provider, so MAX() here
# is picking the only value each column ever holds, not guessing among several.
#
# Callers pass the WIDENED window (days + _COHORT_LOOKBACK_DAYS) and then drop
# by send time — see _load_messages. email_created_at/first_event_at are
# selected only to feed _cohort_ts, which needs the same inputs here as it gets
# from _METRICS_SQL or the two paths would date the same message differently.
_MSGS_SQL = """
    SELECT
        email_id,
        MAX(provider)                                                   AS provider,
        MAX(recipient)                                                  AS recipient,
        MAX(recipient_domain)                                           AS recipient_domain,
        MAX(subject)                                                    AS subject,
        MIN(email_created_at)                                           AS email_created_at,
        MIN(occurred_at) FILTER (WHERE event_type = 'email.sent')       AS sent_at,
        MAX(occurred_at) FILTER (WHERE event_type = 'email.delivered')  AS delivered_at,
        MIN(occurred_at)                                                AS first_event_at,
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


def _cohort_ts(msg: dict) -> datetime | None:
    """When a message actually went out — every event on it, however late, is
    attributed here.

    Keys on `email_created_at` — the provider's own record of when it built the
    message — in preference to the timestamp of the `email.sent` EVENT. The two
    agree for ordinary mail, but the event can be missing entirely: anything
    sent before the webhook was configured on 21 Jul 09:43 has no sent or
    delivered row at all, and surfaces only if someone later opens it. Derived
    from events, such a message dates itself to the open (sophieclaw1@pm.me
    opened the 21 Jul digest on 3 Aug, landing a 62nd message on a day that sent
    61). `email_created_at` rides on every row including that one — 1363 of 1363
    populated, checked 2026-08-04 — and correctly says 21 Jul.

    The remaining fallbacks are for safety only, cheapest-lie-first: the sent
    event, then the earliest event of any kind. Never the LAST event, which is
    whenever someone last touched the mail — days or weeks adrift.

    One definition, shared by the list's window cut and the metrics buckets, so
    the two pages can never disagree about which day a message belongs to.
    """
    ts = (
        msg.get("email_created_at")
        or msg.get("sent_at")
        or msg.get("first_event_at")
        or msg.get("last_event_at")
    )
    if not isinstance(ts, datetime):
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _load_messages(days: int) -> list[dict]:
    """One classified row per message SENT in the window. Filtering/pagination
    happen in Python (see list_messages) rather than in SQL — at today's
    volume (~150 events/day, ~409 messages over 9 days per the plan's prod
    check) pulling the whole window is trivial, and it keeps the
    status/was_delayed logic in one place that unit tests can exercise
    without a database.

    The QUERY window is widened by _COHORT_LOOKBACK_DAYS so a message whose only
    in-window event is a late open still arrives with its own sent/delivered
    rows attached; those extra messages are then dropped by SEND time. So the
    list means "sent in the last `days`", not "touched in the last `days`" —
    without the drop, reopening a week-old digest resurrects it at the top of
    the list wearing the open's timestamp.

    The cutoff mirrors the SQL's own `NOW() - days` rather than a UK calendar
    day, so widening the query does not quietly move the boundary that decides
    which messages the page shows.
    """
    rows = query(_MSGS_SQL, {"days": days + _COHORT_LOOKBACK_DAYS})
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for r in rows:
        sent_ts = _cohort_ts(r)
        if sent_ts is None or sent_ts < cutoff:
            continue
        status, was_delayed, opened, clicked = _classify(r.get("event_types"))
        out.append({
            # first_event_at exists only to feed _cohort_ts; it would read as a
            # second, subtly different send time in the API response.
            **{k: v for k, v in r.items() if k not in ("event_types", "first_event_at")},
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

# Every series is counted BOTH ways and the page toggles between them:
#
#   unique — messages that ever reached this event. One message opened four
#            times is one open. This is what "open rate" conventionally means
#            and the only basis on which a share-of-delivered is honest.
#   events — raw event count, which is what Resend's own Metrics chart draws.
#            Reconciled 2026-08-04: our 4 clicked against Resend's 13 on 3 Aug
#            was 13 click events spread over 4 messages, one recipient alone
#            clicking 10 times across 6 links. Opens repeat too, but far less
#            (~1.4x against ~3.3x on clicks).
#
# Delivered/bounced/failed rarely repeat, so the two bases nearly coincide
# there; the toggle still applies to every series so a single switch doesn't
# leave the chart mixing bases.
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


# The metrics read model. Separate from _MSGS_SQL because that one collapses a
# message to a DISTINCT set of event types, which is exactly the information the
# unique/events toggle needs back: `event_counts` is a {event_type: n} map.
# Two passes over the same window rather than one clever one — the per-type
# rollup can't also carry per-message MAX(provider), and at this volume (~2k
# events over a charted fortnight) the second scan costs nothing.
_METRICS_SQL = f"""
    WITH windowed AS (
        SELECT * FROM email_events
        WHERE occurred_at >= NOW() - (%(days)s || ' days')::INTERVAL
          AND {EXCLUDE_SIMULATOR_SQL}
    ),
    per_type AS (
        SELECT email_id, event_type, COUNT(*) AS n
        FROM windowed GROUP BY email_id, event_type
    ),
    per_msg AS (
        SELECT
            email_id,
            MAX(provider)                                              AS provider,
            MAX(recipient_domain)                                      AS recipient_domain,
            MIN(email_created_at)                                      AS email_created_at,
            MIN(occurred_at) FILTER (WHERE event_type = 'email.sent')  AS sent_at,
            MIN(occurred_at)                                           AS first_event_at,
            MAX(occurred_at)                                           AS last_event_at
        FROM windowed GROUP BY email_id
    )
    SELECT
        m.email_id, m.provider, m.recipient_domain, m.email_created_at,
        m.sent_at, m.first_event_at, m.last_event_at,
        JSONB_OBJECT_AGG(t.event_type, t.n) AS event_counts
    FROM per_msg m JOIN per_type t USING (email_id)
    GROUP BY m.email_id, m.provider, m.recipient_domain, m.email_created_at,
             m.sent_at, m.first_event_at, m.last_event_at
"""


def _cohort_day(msg: dict) -> date | None:
    """The UK date a message went out. Cohort-by-send-day (not by event day) is
    what makes the rates readable: `opened` on 04 Aug is a share of THAT
    morning's delivered, rather than of whatever happened to be delivered the
    day the open landed. See _cohort_ts for the precedence and why."""
    ts = _cohort_ts(msg)
    return ts.astimezone(_UK_TZ).date() if ts is not None else None


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
    """Per-day counts for the `/email-metrics` chart.

    Every day in the window is emitted, including days with no send at all —
    the digest is weekdays-only, so dropping empty days would quietly close the
    weekend gaps and make a five-day cadence look continuous.

    Each series appears twice on every point and in `totals`: `<series>` counts
    unique messages, `<series>_events` counts raw events (see _SERIES_EVENT).
    `rates` stays on the unique basis in both cases — a share-of-delivered
    computed from event counts isn't a rate and can exceed 100%.
    """
    days = max(1, min(days, 90))
    today = datetime.now(timezone.utc).astimezone(_UK_TZ).date()
    window = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    first_day = window[0]

    # Look back well past the charted window: the SQL filters on event time
    # while the buckets below key on SEND time, so a message needs its own
    # sent/delivered rows in scope to be cohorted correctly even when only its
    # late engagement falls inside the window. See _COHORT_LOOKBACK_DAYS.
    # Cohorts outside `window` are dropped after classification.
    rows = query(_METRICS_SQL, {"days": days + _COHORT_LOOKBACK_DAYS})

    # Each bucket carries both bases side by side (`opened` unique,
    # `opened_events` raw), so the page's toggle is a dataKey swap rather than
    # a refetch — and the two can never drift out of step with each other.
    def _blank() -> dict:
        return {
            "messages": 0,
            **{s: 0 for s in _SERIES_EVENT},
            **{f"{s}_events": 0 for s in _SERIES_EVENT},
        }

    buckets = {d: {"day": d.isoformat(), **_blank()} for d in window}
    totals = _blank()
    domains: dict[str, int] = {}

    for r in rows:
        if provider and r.get("provider") != provider:
            continue
        if domain and r.get("recipient_domain") != domain:
            continue
        day = _cohort_day(r)
        if day is None or day not in buckets:
            continue
        counts = r.get("event_counts") or {}
        bucket = buckets[day]
        bucket["messages"] += 1
        totals["messages"] += 1
        for series, event_type in _SERIES_EVENT.items():
            n = int(counts.get(event_type) or 0)
            if n:
                bucket[series] += 1
                totals[series] += 1
            bucket[f"{series}_events"] += n
            totals[f"{series}_events"] += n
        dom = r.get("recipient_domain")
        if dom:
            domains[dom] = domains.get(dom, 0) + 1

    # Null out engagement before it was being recorded — see the constant — and
    # take those days out of the opened/clicked totals too. A total the chart
    # can't draw is worse than no total: the legend would claim 105 opens over a
    # window whose visible points only ever add up to 95.
    for day, bucket in buckets.items():
        if day < _ENGAGEMENT_TRACKED_FROM:
            for key in ("opened", "clicked", "opened_events", "clicked_events"):
                totals[key] -= bucket[key]
                bucket[key] = None

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
