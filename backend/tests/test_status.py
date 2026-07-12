"""Tests for the admin /api/status page and the digest send-status mapping.

Hermetic: the GitHub CI client and the health collector are mocked, and the
digest status decision is a pure function, so nothing here touches the DB or
the network.
"""
import pytest
from fastapi.testclient import TestClient

import contextlib

import main
from main import app
from email_rns_digest import _record_send, _send_status


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
        lambda force=False: {"available": True, "workflows": [
            {"workflow": "healthcheck.yml", "status": "completed",
             "conclusion": "success", "run_started_at": "2026-07-12T06:00:00Z",
             "html_url": "https://github.com/x/runs/1", "dispatchable": False},
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
    monkeypatch.setattr(main, "_ci_latest_runs", lambda force=False: {"available": False, "error": "no token"})
    monkeypatch.setattr(main, "_digest_marker", lambda: None)
    body = client.get("/api/status").json()
    assert body["health"]["summary"] == "fail"
    assert body["ci"]["available"] is False
    assert body["digest"] is None


# ── on-demand workflow dispatch (POST /api/ci/run) ─────────────────────────────

def test_ci_run_rejects_non_dispatchable_workflow(client):
    # Only the smoke/e2e suites are dispatchable; everything else (including
    # real workflow files like healthcheck.yml) must 400, not dispatch.
    assert client.post("/api/ci/run?workflow=healthcheck.yml").status_code == 400
    assert client.post("/api/ci/run?workflow=evil.yml").status_code == 400


def test_ci_run_dispatches_and_invalidates_cache(client, monkeypatch):
    dispatched, invalidated = [], []
    monkeypatch.setattr(
        main.gh_actions, "dispatch",
        lambda wf: (dispatched.append(wf), "2026-07-12T20:00:00Z")[1],
    )
    monkeypatch.setattr(main.ci_status, "invalidate", lambda: invalidated.append(True))
    r = client.post("/api/ci/run?workflow=smoke.yml")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "dispatched"
    assert body["workflow"] == "smoke.yml"
    assert dispatched == ["smoke.yml"]
    assert invalidated  # stale pre-dispatch CI cache must be dropped


def test_ci_run_dispatch_failure_returns_502(client, monkeypatch):
    def boom(wf):
        raise RuntimeError("GH_DISPATCH_TOKEN env var not set")
    monkeypatch.setattr(main.gh_actions, "dispatch", boom)
    r = client.post("/api/ci/run?workflow=e2e.yml")
    assert r.status_code == 502


def test_status_fresh_ci_bypasses_cache(client, monkeypatch):
    forces = []
    monkeypatch.setattr(main, "_collect_health", lambda query_one=None: [])
    monkeypatch.setattr(main, "_digest_marker", lambda: None)
    monkeypatch.setattr(
        main, "_ci_latest_runs",
        lambda force=False: (forces.append(force), {"available": False, "error": "x"})[1],
    )
    client.get("/api/status")
    client.get("/api/status?fresh_ci=true")
    assert forces == [False, True]


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


# ── pipeline_runs stamp (email_rns_digest._record_send) ────────────────────────

class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def test_record_send_stamps_marker(monkeypatch):
    """The full stamp path must run (a NameError here once slipped past the
    pure-mapping tests): status + detail land in the upsert params."""
    import db
    conn = _FakeConn()

    @contextlib.contextmanager
    def fake_connection():
        yield conn

    monkeypatch.setattr(db, "connection", fake_connection)
    _record_send({"exit_code": 0, "mode": "segment",
                  "recipients": 27, "sent": 27, "failed": 0})

    assert conn.committed
    (sql, params), = conn.cur.executed
    assert "pipeline_runs" in sql and "'rns_digest'" in sql
    status, detail_json = params
    assert status == "ok"
    assert detail_json.adapted == {
        "mode": "segment", "recipients": 27, "sent": 27, "failed": 0,
    }


def test_record_send_never_raises(monkeypatch):
    """Best-effort contract: a DB failure (or any bug in the stamp path) must
    not propagate — main() calls this after the mail has already gone out."""
    import db

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "connection", boom)
    _record_send({"exit_code": 0, "mode": "segment",
                  "recipients": 27, "sent": 27, "failed": 0})  # must not raise
