"""ses_events.drain check (healthcheck.py).

The drain is pull-based (SQS, no HTTP endpoint), so this pipeline_runs marker
is the only signal that a dead cron has gone unnoticed -- see run_email_events.py.
test_status.py mocks _collect_health wholesale rather than exercising individual
checks, so this file drives run_db_checks directly with a stub query_one,
skipping run_http_checks (which would otherwise make a real network call).
"""
from datetime import datetime, timedelta, timezone

import healthcheck
from rns import DIGEST_SEND_UK


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


def _send_offset(minutes=0, seconds=0):
    """A naive UK datetime offset from rns.DIGEST_SEND_UK, same day as _naive().

    Derives from the real constant rather than a hardcoded clock time so these
    fixtures can't drift out of sync with the actual send time the way the
    07:12-vs-07:30 mis-calibration (2026-07-31) did."""
    base = _naive(DIGEST_SEND_UK.hour, DIGEST_SEND_UK.minute, DIGEST_SEND_UK.second)
    return base + timedelta(minutes=minutes, seconds=seconds)


def _batch_stub(row):
    def query_one(sql):
        if "'06:30'" in " ".join(sql.split()):
            # backfilled defaults to 0 so the cases that predate same-day
            # backfill handling stay written as they were; the tests that
            # exercise it pass their own value.
            return {"backfilled": 0, **row}
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
    # Completed 3 min before the send — past the 5-min-before warn line but
    # before the fail line (the send itself).
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(9, 0), "n": 30, "unscored": 0,
           "done_uk": _send_offset(minutes=-3)}
    status, _ = _run_batch(_batch_stub(row))
    assert status == healthcheck.WARN


def test_morning_batch_before_send_passes(monkeypatch):
    """Completed 6 min before the send — comfortably ahead of the warn line.

    Regression guard for the mis-calibration fixed on 2026-07-31: this case
    used to FAIL, because the check judged against an 07:12 send the project
    was aiming at but had never deployed.
    """
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(9, 0), "n": 30, "unscored": 0,
           "done_uk": _send_offset(minutes=-6)}
    status, _ = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS


def test_morning_batch_late_fails(monkeypatch):
    # Completed 07:56 — the 2026-07-31 batch; the 07:30 send went out without it.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(9, 0), "n": 45, "unscored": 0, "done_uk": _naive(7, 56, 6)}
    status, _ = _run_batch(_batch_stub(row))
    assert status == healthcheck.FAIL


def test_morning_batch_in_progress_passes(monkeypatch):
    # Viewed at 07:05 with a story still ranking: in flight, not a regression.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(7, 5), "n": 20, "unscored": 3, "done_uk": None}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "still ranking" in detail


def test_morning_batch_unscored_before_send_passes(monkeypatch):
    # 1 min before the send, with rows still ranking: tight, but the send has
    # not fired yet (settled = send + 1 min), so they are in flight rather
    # than missed.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _send_offset(minutes=-1), "n": 20, "unscored": 3, "done_uk": None}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "still ranking" in detail


def test_morning_batch_stalled_fails(monkeypatch):
    # Same unscored rows but now past the 07:30 send: the pipeline has stalled
    # and those stories missed the email.
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(8, 30), "n": 20, "unscored": 3, "done_uk": None}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.FAIL
    assert "stalled" in detail


def test_backfilled_stories_are_reported_but_not_judged(monkeypatch):
    """The 2026-07-28 case: a classifier fix (fd253f3) re-tiered two 07:00
    results headlines from C to A at ~09:40 and they were patched in after the
    email had gone. Scoped on publication time that read as "ranked at 10:02,
    182m late" and failed the check; the morning burst had in fact finished at
    07:06. A same-day fix to a scoring miss must not look like a pipeline
    regression, or the check stops being worth reading."""
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(11, 0), "n": 51, "unscored": 0,
           "done_uk": _naive(7, 6, 51), "backfilled": 2}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "51 stories" in detail
    assert "2 backfilled" in detail          # surfaced, not hidden


def test_backfill_is_surfaced_even_with_no_pre_send_batch(monkeypatch):
    """A day whose entire A/B set arrived via backfill still reports it, rather
    than reading as a silent 'nothing happened today'."""
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    row = {"now_uk": _naive(11, 0), "n": 0, "unscored": 0,
           "done_uk": None, "backfilled": 3}
    status, detail = _run_batch(_batch_stub(row))
    assert status == healthcheck.PASS
    assert "3 backfilled" in detail


def test_morning_batch_scopes_on_candidacy_not_publication(monkeypatch):
    """Locks in the fix: the window must be defined by when a story became a
    ranking candidate (summary_fetched_at), not by when it was published.
    Reverting to a publication-time scope silently restores the false FAIL."""
    monkeypatch.setitem(healthcheck.DB_CONFIG, "host", "test-host")
    seen = []

    def query_one(sql):
        text = " ".join(sql.split())
        if "'06:30'" in text:
            seen.append(text)
            return {"now_uk": _naive(9, 0), "n": 10, "unscored": 0,
                    "done_uk": _naive(7, 6), "backfilled": 0}
        return None

    _run_batch(query_one)
    assert seen, "morning_batch query never ran"
    assert "summary_fetched_at" in seen[0]
