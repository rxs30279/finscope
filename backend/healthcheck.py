"""End-to-end health check for the stock screener.

Verifies, in one pass, that every data pipeline is still landing fresh rows AND
that the live backend API responds. Designed to run as a scheduled GitHub
Actions workflow (see .github/workflows/healthcheck.yml): it prints an aligned
PASS/WARN/FAIL table and exits non-zero if ANY check FAILs, so GitHub's built-in
"scheduled workflow failed" email is the alert — no extra alerting code.

What it checks
  Data freshness (Supabase):
    - RNS              MAX(fetched_at)  on rns_announcements
    - Prices (nightly) MAX(computed_at) on screener_scores  (the real "did the
                       nightly price refresh finish" signal, weekend-proof)
    - Prices (feed)    MAX(date)        on price_history
    - Analysts         MAX(snapshot_date) on analyst_snapshots
    - Index refresh    pipeline_runs marker for the quarterly index-membership
                       cron (stale > ~1 quarter, or last run degraded)
    - LSE universe     pipeline_runs marker for the monthly LSE-screen universe
                       refresh (stale > ~5 weeks, or last run degraded)
    - Dividends        pipeline_runs marker for the weekly dividend-history
                       refresh (stale > ~1.5 weeks, or last run degraded)
    - Shorts           pipeline_runs marker for the daily FCA short-position
                       refresh (stale > 3 days, or last run degraded)
    - Digest           pipeline_runs marker for the weekday RNS email send
                       (send time: rns.DIGEST_SEND_UK; stale > 3 days, or
                       last send in fallback/partial)
    - RNS ingest       pipeline_runs marker for the RNS ingest stage — FAILs
                       if the last run aborted mid-sweep (rate limit / fetch
                       error), which otherwise silently drops rows with no
                       trace in the data
    - RNS morning batch when today's pre-send A/B batch finished LLM ranking —
                       guards the digest send (WARN 5 min before
                       rns.DIGEST_SEND_UK, FAIL if the batch ranks after the
                       send would have fired)
    - RNS body capture share of recent tier A/B rows with a non-stub
                       announcement body (guards against silent selector rot
                       — see docs/rns-body-context-plan.md)
    - Financials       MIN/MAX(financials_updated) on company_metadata (rotation)
  Service liveness (HTTP):
    - Backend API      GET {API_BASE_URL}/api/filters

  The RNS / prices / scores pipelines run as Dokploy cron jobs (no HTTP endpoint
  to ping); their success is covered by the data-freshness checks above plus
  Dokploy's own per-run status.

The digest is now verified via a pipeline_runs marker (see Digest above):
email_rns_digest.main() stamps 'rns_digest' after each real send, so a missed
or silently-degraded send (e.g. the 03 Jun–10 Jul 2026 fallback incident) fails
this check without this script having to send any mail itself.

Env vars (same DB_* set the refresh workflows already use):
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  API_BASE_URL  — optional, defaults to https://api.alphamoveai.co.uk

Usage:
  python healthcheck.py            # plain table, exit 1 on any FAIL
  python healthcheck.py --verbose  # also print PASS detail lines
"""

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta, timezone

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}

# Backend migrated off Vercel onto a Hetzner VPS (Dokploy) — api.alphamoveai.co.uk.
# VERCEL_BASE_URL is still honoured as a legacy fallback so any old GHA secret keeps working.
API_BASE_URL = os.environ.get(
    "API_BASE_URL",
    os.environ.get("VERCEL_BASE_URL", "https://api.alphamoveai.co.uk"),
).rstrip("/")

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Collected results: list of (name, status, detail).
_results: list[tuple[str, str, str]] = []

# The checks report through this module-global, so concurrent collect() calls
# (e.g. two overlapping /api/status requests) would interleave their results.
# Serialise them; the CLI is single-threaded and never contends.
_collect_lock = threading.Lock()


def record(name: str, status: str, detail: str) -> None:
    _results.append((name, status, detail))


def check(name: str):
    """Decorator: run a check function, turn any exception into a FAIL."""
    def wrap(fn):
        try:
            status, detail = fn()
        except Exception as e:  # never let one check crash the whole run
            status, detail = FAIL, f"{type(e).__name__}: {e}"
        record(name, status, detail)
        return fn
    return wrap


# ── DB helpers ────────────────────────────────────────────────────────────────

def _query_one(sql: str):
    """Run a single SELECT and return its one row (RealDict)."""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        return cur.fetchone()
    finally:
        conn.close()


def _age_hours(ts) -> float:
    """Hours between a timestamptz value and now (UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def _age_days(d: date) -> int:
    """Whole days between a date and today (UTC)."""
    return (datetime.now(timezone.utc).date() - d).days


def _tier(value: float, warn_at: float, fail_at: float) -> str:
    if value >= fail_at:
        return FAIL
    if value >= warn_at:
        return WARN
    return PASS


# ── Data-freshness checks ─────────────────────────────────────────────────────

def run_db_checks(query_one=None) -> None:
    # `query_one` lets an in-process caller (the /api/status endpoint) inject a
    # pooled query so each check reuses the shared connection pool instead of
    # opening a fresh SSL connection. The CLI passes nothing → standalone
    # `_query_one`.
    query_one = query_one or _query_one
    if not DB_CONFIG["host"]:
        record("database", FAIL, "DB_HOST not set — cannot run freshness checks")
        return

    @check("rns.fetched_at")
    def _rns():
        row = query_one("SELECT MAX(fetched_at) AS t, COUNT(*) AS n FROM rns_announcements")
        if not row or row["t"] is None:
            return FAIL, "rns_announcements is empty"
        h = _age_hours(row["t"])
        # Monitor runs ~11:00 UTC weekdays; last morning RNS slot is 10:00 UTC.
        return _tier(h, warn_at=8, fail_at=24), f"newest {h:.1f}h ago, {row['n']} rows total"

    @check("prices.nightly_refresh")
    def _scores():
        row = query_one("SELECT MAX(computed_at) AS t, COUNT(*) AS n FROM screener_scores")
        if not row or row["t"] is None:
            return FAIL, "screener_scores is empty — nightly refresh never ran"
        h = _age_hours(row["t"])
        n = row["n"]
        status = _tier(h, warn_at=26, fail_at=36)
        if n < 500:  # universe is ~633
            status = FAIL
        return status, f"computed {h:.1f}h ago, {n} symbols scored"

    @check("prices.feed_date")
    def _prices():
        row = query_one("SELECT MAX(date) AS d FROM price_history")
        if not row or row["d"] is None:
            return FAIL, "price_history is empty"
        d = _age_days(row["d"])
        # Loose: MAX(date) legitimately lags over weekends/holidays; the nightly
        # refresh liveness is covered by prices.nightly_refresh above.
        return _tier(d, warn_at=4, fail_at=5), f"latest trading date {row['d']} ({d}d ago)"

    @check("analysts.snapshot")
    def _analysts():
        row = query_one(
            "SELECT MAX(snapshot_date) AS d, "
            "COUNT(*) FILTER (WHERE snapshot_date = (SELECT MAX(snapshot_date) "
            "FROM analyst_snapshots)) AS n FROM analyst_snapshots"
        )
        if not row or row["d"] is None:
            return FAIL, "analyst_snapshots is empty"
        d = _age_days(row["d"])
        n = row["n"]
        status = _tier(d, warn_at=1, fail_at=2)  # runs daily incl. weekends
        if n < 300:  # a healthy daily snapshot covers most of the ~633 universe
            status = max(status, WARN, key=[PASS, WARN, FAIL].index)
        return status, f"latest {row['d']} ({d}d ago), {n} stocks in it"

    @check("index.membership_refresh")
    def _index_refresh():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'index_refresh'"
        )
        if not row or row["last_run_at"] is None:
            return FAIL, "no index_refresh marker in pipeline_runs"
        d = _age_hours(row["last_run_at"]) / 24.0
        # Quarterly Dokploy cron on the 25th of Mar/Jun/Sep/Dec — successive
        # runs are 90-92 days apart, so >93d means a missed quarter.
        status = _tier(d, warn_at=93, fail_at=97)
        if row["status"] != "ok":
            status = FAIL  # last run blocked its purges (or otherwise degraded)
        return status, f"last apply {d:.0f}d ago, status '{row['status']}', {row['detail']}"

    @check("universe.lse_refresh")
    def _lse_universe_refresh():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'lse_universe_refresh'"
        )
        if not row or row["last_run_at"] is None:
            return FAIL, "no lse_universe_refresh marker in pipeline_runs"
        d = _age_hours(row["last_run_at"]) / 24.0
        # Monthly Dokploy cron — successive runs are 28-31 days apart, so give
        # a few days' slack before flagging a missed month.
        status = _tier(d, warn_at=35, fail_at=45)
        if row["status"] != "ok":
            status = FAIL  # last run blocked its purges/deactivations (or errored)
        return status, f"last apply {d:.0f}d ago, status '{row['status']}', {row['detail']}"

    @check("dividends.refresh")
    def _dividends_refresh():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'dividends_refresh'"
        )
        if not row or row["last_run_at"] is None:
            return FAIL, "no dividends_refresh marker in pipeline_runs"
        d = _age_hours(row["last_run_at"]) / 24.0
        # Weekly Dokploy cron (finscope-dividends) — successive runs are ~7d
        # apart, so give a couple of days' slack before flagging a miss.
        status = _tier(d, warn_at=8, fail_at=10)
        if row["status"] != "ok":
            status = FAIL  # last run errored (see detail)
        return status, f"last run {d:.1f}d ago, status '{row['status']}', {row['detail']}"

    @check("landing_story.pick")
    def _landing_story_pick():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'landing_story'"
        )
        if not row or row["last_run_at"] is None:
            return FAIL, "no landing_story marker in pipeline_runs"
        d = _age_hours(row["last_run_at"]) / 24.0
        # Weekly Monday Dokploy cron — successive runs are ~7d apart, so give a
        # couple of days' slack before flagging a miss.
        status = _tier(d, warn_at=8, fail_at=10)
        # 'skipped' is a thin week with nothing worth showing, which is designed
        # behaviour (the previous story stays live) — only a real error fails.
        if row["status"] not in ("ok", "skipped"):
            status = FAIL
        return status, f"last run {d:.1f}d ago, status '{row['status']}', {row['detail']}"

    @check("shorts.refresh")
    def _shorts_refresh():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'shorts_refresh'"
        )
        if not row or row["last_run_at"] is None:
            return FAIL, "no shorts_refresh marker in pipeline_runs"
        d = _age_hours(row["last_run_at"]) / 24.0
        # Weekday Dokploy cron -- weekend gaps are expected, so give slack
        # before flagging a miss (warn > 3 days, fail > 5 days).
        status = _tier(d, warn_at=3, fail_at=5)
        if row["status"] != "ok":
            status = FAIL  # last run errored (see detail)
        return status, f"last run {d:.1f}d ago, status '{row['status']}', {row['detail']}"

    @check("ses_events.drain")
    def _ses_events_drain():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'ses_events'"
        )
        if not row or row["last_run_at"] is None:
            # Not a FAIL: the drain cron is intentionally not enabled yet
            # (blocked on SES production access) — a standing WARN is the
            # nudge to turn it on once the parallel run starts, not noise.
            return WARN, ("drain has never run — enable the Dokploy cron "
                          "(*/15 7-18 * * 1-5) when the SES parallel run starts")
        d = _age_hours(row["last_run_at"]) / 24.0
        # Weekday cron, 07:00-18:00 UTC only -- weekend gaps are expected, so
        # give slack before flagging a miss (warn > 3 days, fail > 5 days).
        status = _tier(d, warn_at=3, fail_at=5)
        if row["status"] != "ok":
            status = FAIL  # last drain errored (see detail)
        return status, f"last run {d:.1f}d ago, status '{row['status']}', {row['detail']}"

    @check("digest.sent")
    def _digest_sent():
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'rns_digest'"
        )
        if not row or row["last_run_at"] is None:
            return FAIL, "no rns_digest marker in pipeline_runs"
        d = _age_hours(row["last_run_at"]) / 24.0
        # Weekday cron-job.org send (see rns.DIGEST_SEND_UK) — weekend gaps
        # are expected, so give a few days' slack before flagging a miss
        # (warn > 3 days, fail > 5).
        status = _tier(d, warn_at=3, fail_at=5)
        if row["status"] != "ok":
            # Non-ok = fallback mode / partial send / nothing sent. This is the
            # signal that went dark 03 Jun–10 Jul 2026 (silent DIGEST_TO
            # fallback); forcing FAIL surfaces it in the daily GHA run.
            status = FAIL
        return status, f"last send {d:.1f}d ago, status '{row['status']}', {row['detail']}"

    @check("rns.ingest_complete")
    def _rns_ingest_complete():
        # _run_ingest aborts its page loop on the first rate-limit or fetch
        # error (rns.py), and because stop_on_known then breaks at page 2 on
        # the NEXT run too, the pages beyond the abort are never re-read —
        # the rows on them are lost silently. A truncated ingest is invisible
        # in the data (a thin digest and a quiet news day look identical), so
        # this pipeline_runs('rns_ingest') marker (stamped by run_rns.py) is
        # the only signal that distinguishes them. run_rns.py already forces
        # a deep sweep on the run after an incomplete one; this just makes
        # that state visible instead of only living in the cron log.
        row = query_one(
            "SELECT last_run_at, status, detail FROM pipeline_runs "
            "WHERE pipeline = 'rns_ingest'"
        )
        if not row or row["last_run_at"] is None:
            return WARN, "no rns_ingest marker yet (stamp lands on the next run)"
        if row["status"] != "ok":
            return FAIL, (
                f"last ingest stopped early: '{row['status']}' — pages beyond "
                f"the abort were not read, next run sweeps deeper, {row['detail']}"
            )
        h = _age_hours(row["last_run_at"])
        # */15 sweep on weekdays; generous slack for weekends/off-hours.
        status = _tier(h / 24.0, warn_at=3, fail_at=5)
        return status, f"last ingest ok, {h:.1f}h ago"

    @check("rns.morning_batch")
    def _rns_morning_batch():
        # Guards the digest send (cron-job.org -> /api/digest, see main.py).
        # The morning RNS batch must be fully LLM-ranked before the send
        # fires; if the early burst crons (07:01/07:04 UK) ever slip later,
        # completion drifts past the send and high-impact stories get missed —
        # that regression should show here.
        #
        # Calibrated against 07:12 until 2026-07-31. That was the send time the
        # project was *aiming* at, never the one in production, which left this
        # check ~18 minutes stricter than reality — it would fail a batch that
        # comfortably made the real email, and a monitor that cries wolf gets
        # ignored. Judge against the send that actually fires — imported from
        # rns.DIGEST_SEND_UK rather than a local literal, since that literal is
        # exactly what drifted out of sync with production before.
        #
        # Scope = A/B stories published BEFORE the send (up to 10 min ahead of
        # it, UK today), i.e. everything that could be in that morning's email.
        # Legitimately late-published stories are excluded on purpose: they
        # don't exist at send time, so they must not drag the metric late. The
        # 10-minute margin (not the send time itself) is because ingest lags
        # publication by ~5 min and ranking takes another minute or two: a
        # story published 5 min before the send cannot make it however healthy
        # the pipeline is, so judging one would be crying wolf about physics.
        #
        # Publication time alone is not enough to define that scope. A story can
        # be published at 07:00, classified Tier C, and only become a ranking
        # candidate hours later when a classifier fix re-tiers it — as happened
        # on 2026-07-28, when fd253f3 landed at 09:30 and two results headlines
        # (ULVR, GAW) were patched in at ~09:40. Measured on publication time
        # that reads as "batch ranked at 10:02, 182m late" and fails the check,
        # when in fact 51 of 53 were ranked by 07:12 and the backfill was the
        # correct response to a scoring miss. Judging a same-day fix as a
        # pipeline regression trains everyone to ignore this check.
        #
        # So scope on summary_fetched_at — when a story actually became a
        # ranking candidate. Anything that entered after the send could never
        # have been in that morning's email; it is counted and reported, but not
        # judged. NULL stays IN scope on purpose: an A/B story that never even
        # reached the summariser is a genuine stall, not a backfill.
        from rns import DIGEST_SEND_UK
        send_today = datetime.combine(date.today(), DIGEST_SEND_UK)
        send_uk = DIGEST_SEND_UK.strftime("%H:%M")
        scope_upper_uk = (send_today - timedelta(minutes=10)).strftime("%H:%M")
        row = query_one(f"""
            WITH batch AS (
                SELECT llm_processed_at,
                       (summary_fetched_at AT TIME ZONE 'Europe/London')::time
                           AS entered_uk
                  FROM rns_announcements
                 WHERE tier IN ('A','B')
                   AND (published_at AT TIME ZONE 'Europe/London')::date
                       = (NOW() AT TIME ZONE 'Europe/London')::date
                   AND (published_at AT TIME ZONE 'Europe/London')::time
                       BETWEEN '06:30' AND '{scope_upper_uk}'
            ), scoped AS (
                SELECT llm_processed_at,
                       (entered_uk IS NULL OR entered_uk <= TIME '{send_uk}')
                           AS in_time
                  FROM batch
            )
            SELECT (NOW() AT TIME ZONE 'Europe/London') AS now_uk,
                   COUNT(*) FILTER (WHERE in_time) AS n,
                   COUNT(*) FILTER (WHERE in_time
                                      AND llm_processed_at IS NULL) AS unscored,
                   (MAX(llm_processed_at) FILTER (WHERE in_time)
                        AT TIME ZONE 'Europe/London') AS done_uk,
                   COUNT(*) FILTER (WHERE NOT in_time) AS backfilled
              FROM scoped
        """)
        if not row or row["now_uk"] is None:
            return PASS, "no data"
        now_uk = row["now_uk"]
        n = row["n"] or 0
        backfilled = row["backfilled"] or 0
        # Always surfaced, never judged: a backfill is worth seeing (it means a
        # story was missed at send time and later fixed) but it is not evidence
        # that the morning pipeline is slow.
        extra = (f", {backfilled} backfilled after {send_uk} (not judged)"
                 if backfilled else "")
        if n == 0:
            return PASS, (f"no pre-send batch today "
                          f"({now_uk:%a %H:%M} UK — weekend/holiday or pre-open)"
                          f"{extra}")
        # Only judge lateness once the send has actually fired; before then an
        # unranked story is still in flight, not a regression. After it, an
        # in-scope story with no score is precisely the miss this check exists
        # to catch, so the line sits just past the send rather than giving the
        # batch further grace it no longer has any use for.
        settled_dt = send_today + timedelta(minutes=1)
        settled = now_uk.time() >= settled_dt.time()
        unscored = row["unscored"] or 0
        if unscored:
            if not settled:
                return PASS, (f"{n} stories, {unscored} still ranking "
                              f"({now_uk:%H:%M} UK){extra}")
            return FAIL, (f"{unscored}/{n} morning stories unscored at "
                          f"{now_uk:%H:%M} UK — pipeline stalled{extra}")
        done = row["done_uk"]
        lag = (done.hour * 60 + done.minute) - 7 * 60
        # The send fires within a few seconds of DIGEST_SEND_UK (every weekday
        # 22-31 Jul 2026 the 07:30 send landed 07:30:25.2-07:30:26.6), and the
        # digest query runs seconds ahead of it. WARN as completion creeps
        # toward that, FAIL once it lands after the send had already gone out
        # — i.e. the batch was missed. There is deliberately no grace past the
        # send: the old three-minute one existed because the send time was an
        # estimate, and the real one is known to the second.
        send_secs = DIGEST_SEND_UK.hour * 3600 + DIGEST_SEND_UK.minute * 60
        status = _tier(
            done.hour * 3600 + done.minute * 60 + done.second,
            warn_at=send_secs - 5 * 60,
            fail_at=send_secs,
        )
        return status, (f"{n} stories ranked by {done:%H:%M:%S} UK "
                        f"(~{lag}m past 07:00){extra}")

    @check("rns.body_capture")
    def _rns_body_capture():
        # Selector rot (docs/rns-body-context-plan.md Risks): the classes
        # around the announcement body are obfuscated CSS on investegate's
        # end and not contractual (fr-view-element / prn-announcement look
        # stable but aren't guaranteed), so a page-layout change could
        # silently zero out every future body capture while
        # summary_fetched_at — and the rest of the pipeline — keeps looking
        # healthy. This check is that regression's only visible signal.
        #
        # Measures extraction, NOT body length. An announcement that only
        # points at an external PDF is a stub, and capturing it as one is the
        # scraper working correctly — the earlier version of this check scored
        # stubs as failures, which put its own ceiling at ~90% and left the
        # 80% threshold flapping on the natural stub rate rather than on rot.
        # Stubs are surfaced below but never judged.
        row = query_one("""
            WITH scoped AS (
                SELECT COALESCE(NULLIF(split_part(url, '/', 5), ''), '?') AS wire,
                       body_chars, body_is_stub
                  FROM rns_announcements
                 WHERE tier IN ('A', 'B')
                   AND body_fetched_at IS NOT NULL
                   AND published_at >= NOW() - INTERVAL '3 days'
            )
            SELECT COUNT(*) AS attempted,
                   COUNT(*) FILTER (WHERE body_chars IS NOT NULL) AS extracted,
                   COUNT(*) FILTER (WHERE body_is_stub) AS stub,
                   COUNT(*) FILTER (WHERE body_chars IS NULL
                                      AND wire IN ('rns', 'prn')) AS core_missed,
                   (SELECT string_agg(n || ' ' || wire, ', ' ORDER BY n DESC, wire)
                      FROM (SELECT wire, COUNT(*) AS n
                              FROM scoped WHERE body_chars IS NULL
                             GROUP BY wire) g) AS missed_by_wire
              FROM scoped
        """)
        attempted = (row or {}).get("attempted") or 0
        if attempted == 0:
            return PASS, "no tier A/B rows in the last 3 days"
        extracted = row["extracted"] or 0
        stub = row["stub"] or 0
        missed = attempted - extracted
        share = extracted / attempted

        # Two signals, worst wins. The overall rate catches a wire we have no
        # selector for at all (investegate carries at least seven — the four
        # beyond rns/prn/ukn are covered only by the generic `news-window`
        # fallback in rns._fetch_body, which is exactly the kind of coverage
        # that can lapse when a new wire appears). Measured over the nine weeks
        # to 2026-08-14 this sits at 97.8-100% per window, the residual being
        # `ukn` pages whose container is present but genuinely empty, so 90%
        # leaves room for that noise while real rot craters the rate.
        overall = _tier(1 - share, warn_at=0.10, fail_at=0.50)
        # The sharper signal, and the one this check was built for: rns and prn
        # are the wires with dedicated precise selectors and ~96% of the volume,
        # and they missed once in 1456 rows over those nine weeks. A handful of
        # misses is invisible in the overall rate (5 of 90 still reads 94%) but
        # against a 1-in-1456 baseline it is the leading edge of rot.
        core = _tier(row["core_missed"] or 0, warn_at=3, fail_at=10)
        status = max(overall, core, key=[PASS, WARN, FAIL].index)

        detail = f"{extracted}/{attempted} recent A/B rows yielded a body ({share:.0%})"
        if missed:
            detail += f" — no container on {row['missed_by_wire']}"
        # Always surfaced, never judged: a rising stub share means more
        # PDF-only announcements, which is a property of the feed rather than
        # of the scraper.
        return status, detail + f", {stub} stubs (not judged)"

    @check("financials.rotation")
    def _financials():
        row = query_one(
            "SELECT MAX(financials_updated) AS newest, "
            "MIN(financials_updated) AS oldest, "
            "COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE financials_updated IS NULL) AS nulls "
            "FROM company_metadata"
        )
        if not row or row["newest"] is None:
            return FAIL, "company_metadata.financials_updated all NULL"
        newest = _age_days(row["newest"])
        oldest = _age_days(row["oldest"]) if row["oldest"] else None
        # The rotation updates 35 stocks/run (updater.STOCKS_PER_RUN — keep in
        # sync; not imported because updater's import side effects are heavy),
        # so a healthy full cycle takes ~ceil(universe / 35) days — derive the
        # threshold from the live count (the universe grows over time).
        cycle = -(-row["total"] // 35)  # ceil
        # newest → did the daily rotation run at all; oldest → is the cycle stalled.
        s1 = _tier(newest, warn_at=2, fail_at=3)
        s2 = _tier(oldest, warn_at=cycle + 4, fail_at=int(cycle * 1.6)) if oldest is not None else PASS
        status = max(s1, s2, key=[PASS, WARN, FAIL].index)
        return status, (
            f"newest {newest}d ago, oldest {oldest}d ago "
            f"(~{cycle}d cycle for {row['total']}), {row['nulls']} never updated"
        )


# ── Service-liveness checks ───────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 60):
    """GET a URL; return (status_code, parsed_json_or_text)."""
    req = urllib.request.Request(url, headers={"User-Agent": "screener-healthcheck"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        try:
            return resp.status, json.loads(raw)
        except json.JSONDecodeError:
            return resp.status, raw


def run_http_checks() -> None:
    @check("backend.api")
    def _backend():
        code, body = _http_get(f"{API_BASE_URL}/api/filters", timeout=30)
        if code != 200:
            return FAIL, f"HTTP {code} from /api/filters"
        if not isinstance(body, dict):
            return WARN, f"200 but unexpected body type {type(body).__name__}"
        return PASS, f"200 OK, {len(body)} filter keys"


# ── Structured collector (in-process callers) ─────────────────────────────────

def collect(query_one=None) -> list[dict]:
    """Run every check once and return structured results.

    Reentrant entry point for in-process callers such as the /api/status admin
    endpoint (the CLI keeps using main()/report(), which read the raw tuple
    list). Clears the module result buffer, runs the DB + HTTP checks, and
    returns ``[{"name", "status", "detail"}, ...]``.

    Pass a pooled ``query_one(sql) -> row`` (see the /api/status endpoint) so
    the DB checks reuse the shared connection pool instead of opening a fresh
    SSL connection each; omit it to use the standalone ``_query_one``.
    """
    with _collect_lock:
        _results.clear()
        run_db_checks(query_one=query_one)
        run_http_checks()
        return [{"name": n, "status": s, "detail": d} for n, s, d in _results]


def summarize(checks: list[dict]) -> str:
    """Reduce structured checks to one overall verdict: 'fail' if any FAIL,
    else 'warn' if any WARN, else 'pass' (lower-cased for the JSON API)."""
    statuses = {c["status"] for c in checks}
    if FAIL in statuses:
        return "fail"
    if WARN in statuses:
        return "warn"
    return "pass"


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(verbose: bool) -> int:
    width = max((len(n) for n, _, _ in _results), default=10)
    print(f"\nHealth check - {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
    for name, status, detail in _results:
        if status == PASS and not verbose:
            continue  # hide healthy checks unless --verbose
        print(f"  {status:<4}  {name:<{width}}  {detail}")

    fails = [n for n, s, _ in _results if s == FAIL]
    warns = [n for n, s, _ in _results if s == WARN]
    print()
    if fails:
        print(f"RESULT: FAIL - {len(fails)} failing: {', '.join(fails)}")
        return 1
    if warns:
        print(f"RESULT: PASS (with {len(warns)} warning(s): {', '.join(warns)})")
        return 0
    print("RESULT: PASS - all checks healthy")
    return 0


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    run_db_checks()
    run_http_checks()
    return report(verbose)


if __name__ == "__main__":
    sys.exit(main())
