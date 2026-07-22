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
