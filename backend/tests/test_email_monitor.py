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
