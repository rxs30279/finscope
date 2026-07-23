"""ses_events.drain check (healthcheck.py).

The drain is pull-based (SQS, no HTTP endpoint), so this pipeline_runs marker
is the only signal that a dead cron has gone unnoticed -- see run_email_events.py.
test_status.py mocks _collect_health wholesale rather than exercising individual
checks, so this file drives run_db_checks directly with a stub query_one,
skipping run_http_checks (which would otherwise make a real network call).
"""
from datetime import datetime, timedelta, timezone

import healthcheck


def _ses_row(status="ok", days_ago=1.0, detail=None):
    return {
        "last_run_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
        "status": status,
        "detail": detail or {"received": 4, "stored": 4, "skipped": 0, "batches": 1},
    }


def _stub(ses_row):
    def query_one(sql):
        text = " ".join(sql.split())
        if "pipeline = 'ses_events'" in text:
            return ses_row
        return None  # every other check: "nothing found", irrelevant here
    return query_one


def _run(query_one) -> dict:
    """Run just the DB checks (no HTTP) and return the ses_events.drain row."""
    healthcheck._results.clear()
    healthcheck.run_db_checks(query_one=query_one)
    results = {n: (s, d) for n, s, d in healthcheck._results}
    return results["ses_events.drain"]


def test_no_marker_warns_not_fails(monkeypatch):
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    status, detail = _run(_stub(None))
    assert status == healthcheck.WARN
    assert "never run" in detail


def test_stale_marker_fails(monkeypatch):
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    status, _ = _run(_stub(_ses_row(days_ago=6)))
    assert status == healthcheck.FAIL


def test_fresh_ok_marker_passes(monkeypatch):
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    status, _ = _run(_stub(_ses_row(days_ago=0.5)))
    assert status == healthcheck.PASS


def test_errored_run_forces_fail_even_if_fresh(monkeypatch):
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    status, _ = _run(_stub(_ses_row(status="error", days_ago=0.1)))
    assert status == healthcheck.FAIL


# ── rns.morning_batch ─────────────────────────────────────────────────────────
# The check reads its own aggregate row (now_uk / n / unscored / done_uk), all in
# naive UK local time. These stubs feed that row directly; the '06:30' window
# literal is unique to this check's SQL, so it can't collide with rns.fetched_at.

def _naive(h, m, s=0):
    return datetime(2026, 7, 23, h, m, s)  # a Thursday, tz-naive UK wall time


def _batch_stub(row):
    def query_one(sql):
        if "'06:30'" in " ".join(sql.split()):
            return row
        return None
    return query_one


def _run_batch(query_one):
    healthcheck._results.clear()
    healthcheck.run_db_checks(query_one=query_one)
    return {n: (s, d) for n, s, d in healthcheck._results}["rns.morning_batch"]


def test_morning_batch_none_passes(monkeypatch):
    # Weekend / holiday / pre-open: no pre-send stories → neutral PASS, not FAIL.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(12, 0), "n": 0, "unscored": 0, "done_uk": None}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "no pre-send batch" in detail


def test_morning_batch_finished_early_passes(monkeypatch):
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(9, 0), "n": 28, "unscored": 0, "done_uk": _naive(7, 6, 51)}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "28 stories" in detail and "07:06:51" in detail


def test_morning_batch_drift_warns(monkeypatch):
    # Completed 07:12 — past the 07:10 warn line but before the 07:15 fail line.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(9, 0), "n": 30, "unscored": 0, "done_uk": _naive(7, 12)}
    status, _ = _run_batch(_batch_stub(row))
    assert status == healthcheck.WARN


def test_morning_batch_late_fails(monkeypatch):
    # Completed 07:22 — the burst slipped; a 07:12 send would have missed stories.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(9, 0), "n": 30, "unscored": 0, "done_uk": _naive(7, 22)}
    status, _ = _run_batch(_batch_stub(row))
    assert status == healthcheck.FAIL


def test_morning_batch_in_progress_passes(monkeypatch):
    # Viewed at 07:05 with a story still ranking: in flight, not a regression.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(7, 5), "n": 20, "unscored": 3, "done_uk": None}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "still ranking" in detail


def test_morning_batch_stalled_fails(monkeypatch):
    # Same unscored rows but now past 07:20: the pipeline has stalled.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(8, 30), "n": 20, "unscored": 3, "done_uk": None}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.FAIL
    assert "stalled" in detail
