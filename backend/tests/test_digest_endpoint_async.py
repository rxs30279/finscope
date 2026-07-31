"""/api/digest hands the send off and answers immediately (2026-07-31).

A real send takes ~34s -- 4.5s of prep, then 61 Resend calls plus up to 45s of
deliberate Microsoft pacing sleep -- while cron-job.org gives up at ~30s. The
timeout never lost a send (the server always finished; pipeline_runs proved it)
but it alerted on every healthy run, which is worse than useless: it made a real
failure indistinguishable from the normal case. The latency cannot be optimised
away, because the pacing IS the deliverability fix.

These tests pin the contract that replaced it: 202 immediately for a real send,
unchanged synchronous 200 for dry runs (the smoke suite asserts on that), and a
lock so the now-unpaced endpoint cannot be made to send twice.
"""

import sys, os

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOKEN = "test-digest-token"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DIGEST_CRON_TOKEN", TOKEN)
    import main
    monkeypatch.setattr(main, "_DIGEST_TOKEN", TOKEN, raising=False)
    return TestClient(main.app), main


def _hdr():
    return {"X-Digest-Token": TOKEN}


def test_real_send_returns_202_without_waiting(client, monkeypatch):
    c, main = client
    calls = []
    monkeypatch.setattr(main, "send_digest_locked",
                        lambda updated=False: calls.append(updated) or {"exit_code": 0})
    r = c.get("/api/digest", headers=_hdr())
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["ok"] is True and body["status"] == "accepted"
    # TestClient runs background tasks after the response, so the send still ran.
    assert calls == [False]


def test_updated_flag_reaches_the_background_send(client, monkeypatch):
    c, main = client
    calls = []
    monkeypatch.setattr(main, "send_digest_locked",
                        lambda updated=False: calls.append(updated) or {"exit_code": 0})
    assert c.get("/api/digest?updated=true", headers=_hdr()).status_code == 202
    assert calls == [True]


def test_dry_run_stays_synchronous_and_200(client, monkeypatch):
    """smoke/test_digest_dryrun.py asserts status 200 with ok/dry_run True."""
    c, main = client
    monkeypatch.setattr(main, "run_digest",
                        lambda dry_run=False, updated=False: {
                            "exit_code": 0, "mode": "dry_run", "recipients": 7})
    r = c.get("/api/digest?dry_run=true", headers=_hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["dry_run"] is True
    assert body["recipients"] == 7


def test_dry_run_never_reaches_the_background_path(client, monkeypatch):
    c, main = client
    sent = []
    monkeypatch.setattr(main, "send_digest_locked",
                        lambda updated=False: sent.append(updated))
    monkeypatch.setattr(main, "run_digest",
                        lambda dry_run=False, updated=False: {"exit_code": 0})
    c.get("/api/digest?dry_run=true", headers=_hdr())
    assert sent == [], "dry run must never trigger a real send"


def test_bad_token_still_403s_before_scheduling_anything(client, monkeypatch):
    c, main = client
    sent = []
    monkeypatch.setattr(main, "send_digest_locked",
                        lambda updated=False: sent.append(updated))
    r = c.get("/api/digest", headers={"X-Digest-Token": "wrong"})
    assert r.status_code == 403
    assert sent == [], "auth must gate the handoff, not just the send"


def test_send_locked_skips_when_lock_is_held(monkeypatch):
    """Two overlapping triggers must not both send. Returning 202 removes the
    HTTP response as a natural throttle, so this lock is what replaces it."""
    import email_rns_digest as d
    from contextlib import contextmanager

    @contextmanager
    def _busy(_key):
        yield False

    monkeypatch.setattr("db.advisory_lock", _busy)
    sent = []
    monkeypatch.setattr(d, "main", lambda updated=False: sent.append(updated))
    stats = d.send_locked()
    assert sent == [], "must not send while another send holds the lock"
    assert stats["mode"] == "skipped_locked"
    assert stats["exit_code"] == 0, "losing the race is normal, not a failure"


def test_send_locked_sends_when_lock_is_free(monkeypatch):
    import email_rns_digest as d
    from contextlib import contextmanager

    @contextmanager
    def _free(_key):
        yield True

    monkeypatch.setattr("db.advisory_lock", _free)
    sent = []
    monkeypatch.setattr(d, "main",
                        lambda updated=False: sent.append(updated) or {"exit_code": 0})
    d.send_locked(updated=True)
    assert sent == [True]
