"""email_monitor.py — the read model behind GET /api/emails(/{email_id}).

DB access is mocked via email_monitor.query (same pattern as
test_email_events.py's monkeypatching of email_events._insert): _load_messages
does one query per request and everything else is Python, so these tests
exercise status precedence, was_delayed, filtering, pagination and the
summary rollup without a database.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import email_monitor
from email_monitor import _classify
from main import app


def _msg(email_id, event_types, sent_at=None, last_event_at=None, provider="resend",
         recipient="someone@example.com", subject="RNS Digest"):
    now = datetime(2026, 7, 30, 9, 0, tzinfo=timezone.utc)
    return {
        "email_id": email_id,
        "provider": provider,
        "recipient": recipient,
        "recipient_domain": recipient.split("@")[-1],
        "subject": subject,
        "sent_at": sent_at,
        "delivered_at": None,
        # In real data the send IS the first event, so mirror that by default;
        # the no-sent cases override it explicitly.
        "first_event_at": sent_at,
        "last_event_at": last_event_at or now,
        "event_types": event_types,
    }


# ── Status precedence ──────────────────────────────────────────────────────────

def test_status_precedence_for_each_outcome():
    assert _classify(["email.sent"])[0] == "sent"
    assert _classify(["email.sent", "email.delivery_delayed"])[0] == "delayed"
    assert _classify(["email.sent", "email.delivered"])[0] == "delivered"
    assert _classify(["email.sent", "email.failed"])[0] == "failed"
    assert _classify(["email.sent", "email.delivered", "email.bounced"])[0] == "bounced"
    assert _classify(["email.sent", "email.delivered", "email.complained"])[0] == "complained"


def test_complained_outranks_everything():
    types = ["email.sent", "email.delivered", "email.bounced", "email.complained"]
    assert _classify(types)[0] == "complained"


def test_was_delayed_true_for_sent_delayed_delivered_but_status_still_delivered():
    status, was_delayed, opened, clicked = _classify(
        ["email.sent", "email.delivery_delayed", "email.delivered"]
    )
    assert status == "delivered"
    assert was_delayed is True


def test_opened_and_clicked_are_independent_of_status():
    status, was_delayed, opened, clicked = _classify(
        ["email.sent", "email.delivered", "email.opened", "email.clicked"]
    )
    assert status == "delivered"
    assert was_delayed is False
    assert opened is True
    assert clicked is True


def test_empty_event_types_defaults_to_sent():
    assert _classify(None)[0] == "sent"
    assert _classify([])[0] == "sent"


# ── Ordering: message with no email.sent ───────────────────────────────────────

def test_message_with_no_sent_event_orders_on_last_event_at(monkeypatch):
    """The prod check found 6/409 messages with no email.sent row (hence
    delivered > sent counts). ORDER BY COALESCE(sent_at, last_event_at) is
    load-bearing: without it these sink to the bottom regardless of age."""
    recent_no_sent = _msg(
        "no-sent", ["email.delivered"], sent_at=None,
        last_event_at=datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc),
    )
    older_with_sent = _msg(
        "with-sent", ["email.sent", "email.delivered"],
        sent_at=datetime(2026, 7, 29, 7, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [recent_no_sent, older_with_sent])

    out = email_monitor.list_messages(days=7)
    ids = [m["email_id"] for m in out["messages"]]
    assert ids == ["no-sent", "with-sent"]  # 30 Jul 08:00 is newer than 29 Jul 07:00


# ── Filtering + pagination ──────────────────────────────────────────────────────

def _mixed_messages():
    return [
        _msg("m1", ["email.sent", "email.delivered"], sent_at=datetime(2026, 7, 30, 7, 1, tzinfo=timezone.utc),
             provider="resend", recipient="a@gmail.com"),
        _msg("m2", ["email.sent", "email.bounced"], sent_at=datetime(2026, 7, 30, 7, 2, tzinfo=timezone.utc),
             provider="resend", recipient="b@hotmail.com"),
        _msg("m3", ["email.sent", "email.delivered"], sent_at=datetime(2026, 7, 30, 7, 3, tzinfo=timezone.utc),
             provider="ses", recipient="c@gmail.com"),
        _msg("m4", ["email.sent"], sent_at=datetime(2026, 7, 30, 7, 4, tzinfo=timezone.utc),
             provider="resend", recipient="d@gmail.com", subject="Feedback reply"),
    ]


def test_status_filter_and_pagination_scope_the_filtered_set(monkeypatch):
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: _mixed_messages())

    out = email_monitor.list_messages(days=7, status="delivered", limit=1, offset=0)
    assert out["total"] == 2  # m1 and m3 are 'delivered'
    assert [m["email_id"] for m in out["messages"]] == ["m3"]  # newest first

    out2 = email_monitor.list_messages(days=7, status="delivered", limit=1, offset=1)
    assert [m["email_id"] for m in out2["messages"]] == ["m1"]


def test_provider_filter():
    matches = [m for m in _mixed_messages() if email_monitor._matches(m, "ses", None)]
    assert [m["email_id"] for m in matches] == ["m3"]


def test_search_matches_recipient_or_subject():
    msgs = _mixed_messages()
    assert [m["email_id"] for m in msgs if email_monitor._matches(m, None, "hotmail")] == ["m2"]
    assert [m["email_id"] for m in msgs if email_monitor._matches(m, None, "feedback")] == ["m4"]
    assert [m["email_id"] for m in msgs if email_monitor._matches(m, None, "nomatch")] == []


# ── Summary ignores the status filter ──────────────────────────────────────────

def test_summary_ignores_status_filter_but_honours_provider_and_search(monkeypatch):
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: _mixed_messages())

    out = email_monitor.list_messages(days=7, status="bounced")
    # summary counts every status in the (unfiltered-by-status) population
    assert out["summary"] == {"delivered": 2, "bounced": 1, "sent": 1}
    # but the returned page is still scoped to status='bounced'
    assert [m["email_id"] for m in out["messages"]] == ["m2"]

    out_ses_only = email_monitor.list_messages(days=7, provider="ses")
    assert out_ses_only["summary"] == {"delivered": 1}


# ── Daily metrics ───────────────────────────────────────────────────────────────

def _at(days_ago: int, hour: int = 7) -> datetime:
    """A UTC timestamp `days_ago` UK-days before now, at the digest hour."""
    today = datetime.now(timezone.utc).astimezone(email_monitor._UK_TZ).date()
    day = today - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, 30, tzinfo=email_monitor._UK_TZ)


def test_metrics_emits_every_day_in_the_window_including_empty_ones(monkeypatch):
    """The digest is weekdays-only — dropping days with no send would close the
    weekend gaps and make a five-day cadence look continuous."""
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        _msg("m1", ["email.sent", "email.delivered"], sent_at=_at(0)),
    ])
    out = email_monitor.daily_metrics(days=5)
    assert len(out["points"]) == 5
    assert [p["messages"] for p in out["points"]] == [0, 0, 0, 0, 1]
    assert out["points"][-1]["day"] == out["end"]


def test_metrics_counts_messages_not_events_and_rolls_up_totals(monkeypatch):
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        _msg("m1", ["email.sent", "email.delivered", "email.opened", "email.clicked"], sent_at=_at(0)),
        _msg("m2", ["email.sent", "email.delivered", "email.opened"], sent_at=_at(0)),
        _msg("m3", ["email.sent", "email.bounced"], sent_at=_at(0)),
        _msg("m4", ["email.sent", "email.delivery_delayed", "email.delivered"], sent_at=_at(1)),
    ])
    out = email_monitor.daily_metrics(days=3)
    assert out["totals"] == {
        "messages": 4, "delivered": 3, "opened": 2, "clicked": 1,
        "bounced": 1, "failed": 0, "complained": 0, "delayed": 1,
    }
    # delivered/bounced are of everything sent; opened/clicked of what landed
    assert out["rates"]["delivered"] == 75.0
    assert out["rates"]["bounced"] == 25.0
    assert out["rates"]["opened"] == round(100 * 2 / 3, 1)


def test_metrics_buckets_by_send_day_not_event_day(monkeypatch):
    """A late open belongs to the cohort it was sent with, otherwise the open
    rate on a given column isn't a share of that column's delivered."""
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        _msg("m1", ["email.sent", "email.delivered", "email.opened"],
             sent_at=_at(2), last_event_at=_at(0)),
    ])
    out = email_monitor.daily_metrics(days=5)
    days_with_mail = [p["day"] for p in out["points"] if p["messages"]]
    assert days_with_mail == [_at(2).astimezone(timezone.utc).astimezone(email_monitor._UK_TZ).date().isoformat()]


def test_metrics_does_not_invent_a_send_from_a_late_open(monkeypatch):
    """Seen in prod 2026-08-04: the 21 Jul digest was opened on 3 Aug. Its own
    sent/delivered rows sat outside the event window, so the group arrived
    holding nothing but the open — and the message materialised as a Sunday
    send with delivered=0, dragging that day's deliverability down. The fix is
    the lookback (the sent row comes back into scope) plus cohorting on the
    FIRST event rather than the last."""
    sent_at = _at(12)
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        _msg("old-digest", ["email.sent", "email.delivered", "email.opened"],
             sent_at=sent_at, last_event_at=_at(0, hour=17)),
    ])
    out = email_monitor.daily_metrics(days=3)
    # Sent 12 days ago, so it belongs to no column in a 3-day window at all.
    assert out["totals"] == {
        "messages": 0, "delivered": 0, "opened": 0, "clicked": 0,
        "bounced": 0, "failed": 0, "complained": 0, "delayed": 0,
    }
    assert all(p["messages"] == 0 for p in out["points"])


def test_metrics_lookback_reaches_past_the_charted_window(monkeypatch):
    """The query has to see a message's own send even when only its engagement
    lands in the window, or the bug above comes straight back."""
    seen = {}

    def fake_query(sql, params=None):
        seen["params"] = params
        return []

    monkeypatch.setattr(email_monitor, "query", fake_query)
    email_monitor.daily_metrics(days=15)
    assert seen["params"]["days"] == 15 + email_monitor._COHORT_LOOKBACK_DAYS


def test_metrics_falls_back_to_first_event_not_last(monkeypatch):
    """For the messages with no email.sent row at all, the earliest event is a
    fair proxy for the send; the latest is whenever someone last touched it."""
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        {**_msg("no-sent", ["email.delivered", "email.opened"], sent_at=None,
                last_event_at=_at(0)),
         "first_event_at": _at(2)},
    ])
    out = email_monitor.daily_metrics(days=5)
    days_with_mail = [p["day"] for p in out["points"] if p["messages"]]
    assert days_with_mail == [_at(2).astimezone(email_monitor._UK_TZ).date().isoformat()]


def test_metrics_nulls_engagement_before_it_was_tracked(monkeypatch):
    """Zero would read as "nobody opened it"; the truth is nothing was recorded
    (opens/clicks were only subscribed on the webhook on 2026-07-30)."""
    before = email_monitor._ENGAGEMENT_TRACKED_FROM - timedelta(days=1)
    sent_at = datetime(before.year, before.month, before.day, 7, 30, tzinfo=email_monitor._UK_TZ)
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        # An open DID land on this cohort (some arrived after tracking went on
        # mid-day), but the day is only half-tracked, so it must not be counted.
        _msg("old", ["email.sent", "email.delivered", "email.opened"], sent_at=sent_at),
    ])
    today = datetime.now(timezone.utc).astimezone(email_monitor._UK_TZ).date()
    out = email_monitor.daily_metrics(days=(today - before).days + 1)

    old_point = next(p for p in out["points"] if p["day"] == before.isoformat())
    assert old_point["delivered"] == 1          # deliverability is real back there
    assert old_point["opened"] is None          # engagement is not
    assert old_point["clicked"] is None
    assert out["engagement"]["fully_tracked"] is False
    assert out["engagement"]["messages"] == 0   # untracked days excluded from the base
    # The chip/legend total has to equal the sum of the drawn points, or it
    # claims opens the chart never shows.
    assert out["totals"]["opened"] == 0
    assert sum(p["opened"] or 0 for p in out["points"]) == out["totals"]["opened"]
    assert out["rates"]["opened"] is None       # no tracked delivered to divide by


def test_metrics_provider_and_domain_filters(monkeypatch):
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        _msg("m1", ["email.sent"], sent_at=_at(0), provider="resend", recipient="a@gmail.com"),
        _msg("m2", ["email.sent"], sent_at=_at(0), provider="ses", recipient="b@gmail.com"),
        _msg("m3", ["email.sent"], sent_at=_at(0), provider="resend", recipient="c@hotmail.com"),
    ])
    assert email_monitor.daily_metrics(days=2, provider="ses")["totals"]["messages"] == 1
    assert email_monitor.daily_metrics(days=2, domain="gmail.com")["totals"]["messages"] == 2
    assert email_monitor.daily_metrics(days=2)["domains"] == [
        {"domain": "gmail.com", "messages": 2},
        {"domain": "hotmail.com", "messages": 1},
    ]


def test_metrics_endpoint_requires_admin_token():
    bare = TestClient(app)
    assert bare.get("/api/emails/metrics").status_code == 403


def test_metrics_route_is_not_swallowed_by_the_email_id_route(client, monkeypatch):
    """`/metrics` has to be registered ahead of `/{email_id}`, or it resolves to
    a timeline lookup for a message literally called "metrics" — which returns
    200 with an empty event list, so only the body shape catches the mistake."""
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        _msg("m1", ["email.sent", "email.delivered"], sent_at=_at(0)),
    ])
    r = client.get("/api/emails/metrics", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert "email_id" not in body                    # not the timeline route
    assert body["days"] == 7 and len(body["points"]) == 7
    assert body["totals"]["delivered"] == 1


# ── Timeline ────────────────────────────────────────────────────────────────────

def test_timeline_queries_by_email_id_ascending(monkeypatch):
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"] = sql
        seen["params"] = params
        return [{"event_type": "email.sent", "provider": "resend",
                  "occurred_at": datetime.now(timezone.utc), "email_created_at": None,
                  "detail": None}]

    monkeypatch.setattr(email_monitor, "query", fake_query)
    out = email_monitor.message_timeline("abc-123")
    assert out["email_id"] == "abc-123"
    assert len(out["events"]) == 1
    assert seen["params"] == ("abc-123",)
    assert "ORDER BY occurred_at ASC" in seen["sql"]


# ── Endpoint wiring / admin gating ──────────────────────────────────────────────

def test_list_endpoint_requires_admin_token():
    bare = TestClient(app)
    assert bare.get("/api/emails").status_code == 403


def test_timeline_endpoint_requires_admin_token():
    bare = TestClient(app)
    assert bare.get("/api/emails/abc-123").status_code == 403


def test_list_endpoint_reachable_with_admin_token(client, monkeypatch):
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: _mixed_messages())
    r = client.get("/api/emails", params={"status": "delivered"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["summary"] == {"delivered": 2, "bounced": 1, "sent": 1}


def test_timeline_endpoint_reachable_with_admin_token(client, monkeypatch):
    monkeypatch.setattr(email_monitor, "query", lambda *a, **k: [
        {"event_type": "email.sent", "provider": "resend",
         "occurred_at": datetime.now(timezone.utc), "email_created_at": None, "detail": None},
    ])
    r = client.get("/api/emails/abc-123")
    assert r.status_code == 200
    assert r.json()["email_id"] == "abc-123"
