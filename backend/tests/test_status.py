"""Tests for the admin /api/status page and the digest send-status mapping.

Hermetic: the GitHub CI client and the health collector are mocked, and the
digest status decision is a pure function, so nothing here touches the DB or
the network.
"""
import pytest
from fastapi.testclient import TestClient

import main
from main import app
from email_rns_digest import _send_status


# ── /api/status endpoint ──────────────────────────────────────────────────────

@pytest.fixture
def mocked_status(monkeypatch):
    """Stub the three data sources so the endpoint is deterministic and offline.
    One check is WARN so we can assert the summary reduce picks it up."""
    fake_checks = [
        {"name": "rns.fetched_at", "status": "PASS", "detail": "fresh"},
        {"name": "digest.sent", "status": "WARN", "detail": "last send 3.2d ago"},
    ]
    monkeypatch.setattr(main, "_collect_health", lambda query_one=None: fake_checks)
    monkeypatch.setattr(
        main, "_ci_latest_runs",
        lambda: {"available": True, "workflows": [
            {"workflow": "healthcheck.yml", "status": "completed",
             "conclusion": "success", "run_started_at": "2026-07-12T06:00:00Z",
             "html_url": "https://github.com/x/runs/1"},
        ]},
    )
    monkeypatch.setattr(
        main, "_digest_marker",
        lambda: {"last_run_at": "2026-07-10T06:31:00+00:00", "status": "ok",
                 "mode": "segment", "recipients": 27, "sent": 27, "failed": 0},
    )


def test_status_requires_admin_token():
    bare = TestClient(app)
    assert bare.get("/api/status").status_code == 403
    assert bare.get("/api/status", headers={"X-Admin-Token": "wrong"}).status_code == 403


def test_status_shape(client, mocked_status):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"generated_at", "health", "ci", "digest"}
    # summary reduces the checks: a WARN present, no FAIL -> "warn"
    assert body["health"]["summary"] == "warn"
    assert body["health"]["checks"][0]["name"] == "rns.fetched_at"
    assert body["ci"]["available"] is True
    assert body["ci"]["workflows"][0]["conclusion"] == "success"
    assert body["digest"]["recipients"] == 27


def test_status_summary_fail_wins(client, monkeypatch):
    monkeypatch.setattr(main, "_collect_health", lambda query_one=None: [
        {"name": "a", "status": "PASS", "detail": ""},
        {"name": "b", "status": "WARN", "detail": ""},
        {"name": "c", "status": "FAIL", "detail": ""},
    ])
    monkeypatch.setattr(main, "_ci_latest_runs", lambda: {"available": False, "error": "no token"})
    monkeypatch.setattr(main, "_digest_marker", lambda: None)
    body = client.get("/api/status").json()
    assert body["health"]["summary"] == "fail"
    assert body["ci"]["available"] is False
    assert body["digest"] is None


# ── digest send-status mapping (email_rns_digest._send_status) ─────────────────

@pytest.mark.parametrize("stats,expected", [
    ({"exit_code": 0, "mode": "segment", "sent": 27, "failed": 0}, "ok"),
    ({"exit_code": 2, "mode": "segment", "sent": 25, "failed": 2}, "degraded"),
    ({"exit_code": 0, "mode": "fallback", "recipients": 1}, "degraded"),
    ({"exit_code": 0, "mode": "none", "recipients": 0}, "degraded"),
    ({"exit_code": 1, "mode": "none", "recipients": 0}, "failed"),
])
def test_send_status_mapping(stats, expected):
    assert _send_status(stats) == expected
