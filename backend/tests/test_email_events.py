"""Resend delivery-event webhook (email_events.py).

The security-relevant half is the Svix signature check: this endpoint is
publicly reachable and writes to a table the /status page reports on, so an
unsigned caller must never get a row in. The parsing half matters because a
payload we mis-flatten is a delivery problem we won't see.
"""
import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import email_events
from main import app

SECRET_KEY = b"0" * 32
SECRET = "whsec_" + base64.b64encode(SECRET_KEY).decode()

DELAYED = {
    "type": "email.delivery_delayed",
    "created_at": "2026-07-21T09:14:02.000Z",
    "data": {
        "email_id": "c6de1612-3b09-43b3-ad42-480adce83335",
        "created_at": "2026-07-21T06:30:44.861Z",
        "from": "Alpha Move AI <digest@alphamoveai.co.uk>",
        "to": ["BenjaminJackMoore@hotmail.co.uk"],
        "subject": "RNS Digest Tue 21 Jul — 32 items",
    },
}


def _sign(msg_id: str, timestamp: str, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    return "v1," + base64.b64encode(hmac.new(SECRET_KEY, signed, hashlib.sha256).digest()).decode()


def _post(client, payload=DELAYED, *, msg_id="msg_1", timestamp=None, signature=None):
    body = json.dumps(payload).encode()
    timestamp = timestamp or str(int(time.time()))
    return client.post(
        "/api/webhooks/resend",
        content=body,
        headers={
            "svix-id": msg_id,
            "svix-timestamp": timestamp,
            "svix-signature": signature or _sign(msg_id, timestamp, body),
            "content-type": "application/json",
        },
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


@pytest.fixture
def inserted(monkeypatch):
    """Capture rows instead of hitting Postgres."""
    rows = []
    monkeypatch.setattr(email_events, "_insert", rows.append)
    return rows


# ── Signature ─────────────────────────────────────────────────────────────────

def test_accepts_valid_signature(client, inserted):
    r = _post(client)
    assert r.status_code == 200, r.text
    assert r.json()["stored"] is True
    assert len(inserted) == 1


def test_rejects_bad_signature(client, inserted):
    r = _post(client, signature="v1," + base64.b64encode(b"x" * 32).decode())
    assert r.status_code == 401
    assert inserted == []


def test_rejects_missing_headers(client, inserted):
    r = client.post("/api/webhooks/resend", content=json.dumps(DELAYED).encode())
    assert r.status_code == 401
    assert inserted == []


def test_rejects_stale_timestamp(client, inserted):
    """Replay guard: a captured body stays signature-valid forever otherwise."""
    old = str(int(time.time()) - 3600)
    r = _post(client, timestamp=old)
    assert r.status_code == 401
    assert inserted == []


def test_signature_covers_the_body(client, inserted):
    """Sign one payload, send another — the MAC must not still validate."""
    body = json.dumps(DELAYED).encode()
    ts = str(int(time.time()))
    good_sig = _sign("msg_1", ts, body)
    tampered = json.dumps({**DELAYED, "type": "email.delivered"}).encode()
    r = client.post(
        "/api/webhooks/resend",
        content=tampered,
        headers={"svix-id": "msg_1", "svix-timestamp": ts, "svix-signature": good_sig},
    )
    assert r.status_code == 401
    assert inserted == []


def test_accepts_any_of_multiple_signatures(client, inserted):
    """During a secret rotation Svix sends several; any valid one is a pass."""
    body = json.dumps(DELAYED).encode()
    ts = str(int(time.time()))
    sigs = "v1," + base64.b64encode(b"stale" * 8).decode() + " " + _sign("msg_1", ts, body)
    r = _post(client, timestamp=ts, signature=sigs)
    assert r.status_code == 200
    assert len(inserted) == 1


def test_fails_closed_without_secret(monkeypatch, inserted):
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    r = _post(TestClient(app))
    assert r.status_code == 503
    assert inserted == []


def test_accepts_webhook_prefixed_headers(client, inserted):
    """Standard Webhooks spells them webhook-*; Resend sends svix-*. Accept both."""
    body = json.dumps(DELAYED).encode()
    ts = str(int(time.time()))
    r = client.post(
        "/api/webhooks/resend",
        content=body,
        headers={
            "webhook-id": "msg_1",
            "webhook-timestamp": ts,
            "webhook-signature": _sign("msg_1", ts, body),
        },
    )
    assert r.status_code == 200
    assert len(inserted) == 1


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_flattens_event(client, inserted):
    _post(client)
    row = inserted[0]
    assert row["event_type"] == "email.delivery_delayed"
    assert row["email_id"] == "c6de1612-3b09-43b3-ad42-480adce83335"
    assert row["recipient"] == "benjaminjackmoore@hotmail.co.uk"  # lowercased
    assert row["recipient_domain"] == "hotmail.co.uk"
    assert row["svix_id"] == "msg_1"
    # Event time and message-accepted time are distinct — the ~2h45m gap between
    # them is the deferral lag this table exists to make measurable.
    assert row["occurred_at"].hour == 9
    assert row["email_created_at"].hour == 6
    assert row["occurred_at"] > row["email_created_at"]


def test_keeps_bounce_detail(client, inserted):
    payload = {
        "type": "email.bounced",
        "created_at": "2026-07-21T09:14:02.000Z",
        "data": {
            "email_id": "abc",
            "to": ["info@bioseekers.com"],
            "bounce": {"type": "Permanent", "subType": "General", "message": "550 5.1.1"},
        },
    }
    _post(client, payload)
    assert inserted[0]["detail"] == {
        "bounce": {"type": "Permanent", "subType": "General", "message": "550 5.1.1"}
    }


def test_ignores_non_email_payload(client, inserted):
    """Svix ping/test deliveries reach the same URL — 200 without storing, since
    a non-2xx would put them into a multi-hour retry loop."""
    r = _post(client, {"type": "ping", "data": {}})
    assert r.status_code == 200
    assert r.json()["stored"] is False
    assert inserted == []


def test_rejects_non_json_body(client, inserted):
    body = b"not json"
    ts = str(int(time.time()))
    r = client.post(
        "/api/webhooks/resend",
        content=body,
        headers={"svix-id": "m", "svix-timestamp": ts, "svix-signature": _sign("m", ts, body)},
    )
    assert r.status_code == 400
    assert inserted == []


# ── Summary rollup ────────────────────────────────────────────────────────────

def test_provider_bucketing():
    assert email_events.provider_of("hotmail.co.uk") == "microsoft"
    assert email_events.provider_of("outlook.com") == "microsoft"
    assert email_events.provider_of("live.co.uk") == "microsoft"
    assert email_events.provider_of("gmail.com") == "google"
    assert email_events.provider_of("selfside.co.uk") == "other"
    assert email_events.provider_of(None) == "other"


def test_recent_summary_reports_rate_not_just_count(monkeypatch):
    """The 21 Jul shape: Microsoft 6 problem messages of 9, everyone else 0 of 45.

    Rate must be per *message*, not per event — each email emits sent +
    delivered (+ delivery_delayed), so an event-denominated rate would report
    6/24 here and get quieter the more event types are subscribed.
    """
    monkeypatch.setattr(email_events, "query", lambda *a, **k: [
        {"recipient_domain": "hotmail.co.uk", "messages": 9,
         "problem_messages": 6, "latest_problem": None, "latest_event": None},
        {"recipient_domain": "gmail.com", "messages": 45,
         "problem_messages": 0, "latest_problem": None, "latest_event": None},
    ])
    out = email_events.recent_summary()
    assert out["messages"] == 54
    assert out["problems"] == 6
    assert out["by_provider"]["microsoft"]["problem_rate"] == pytest.approx(6 / 9, abs=1e-3)
    assert out["by_provider"]["google"]["problem_rate"] == 0.0


def test_recent_summary_merges_domains_into_one_provider(monkeypatch):
    """hotmail.co.uk and outlook.com are separate rows but one provider."""
    monkeypatch.setattr(email_events, "query", lambda *a, **k: [
        {"recipient_domain": "hotmail.co.uk", "messages": 6,
         "problem_messages": 5, "latest_problem": None, "latest_event": None},
        {"recipient_domain": "outlook.com", "messages": 3,
         "problem_messages": 1, "latest_problem": None, "latest_event": None},
    ])
    ms = email_events.recent_summary()["by_provider"]["microsoft"]
    assert (ms["messages"], ms["problems"]) == (9, 6)
