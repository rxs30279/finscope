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
    - Dividends        pipeline_runs marker for the weekly dividend-history
                       refresh (stale > ~1.5 weeks, or last run degraded)
    - Shorts           pipeline_runs marker for the daily FCA short-position
                       refresh (stale > 3 days, or last run degraded)
    - Financials       MIN/MAX(financials_updated) on company_metadata (rotation)
  Service liveness (HTTP):
    - Backend API      GET {API_BASE_URL}/api/filters

  The RNS / prices / scores pipelines run as Dokploy cron jobs (no HTTP endpoint
  to ping); their success is covered by the data-freshness checks above plus
  Dokploy's own per-run status.

Known gap (not checked): the email digest leaves no DB trace — Resend is the
source of truth — and hitting /api/digest would actually send mail, so this
script does not verify it.

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
import urllib.error
import urllib.request
from datetime import datetime, date, timezone

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

def run_db_checks() -> None:
    if not DB_CONFIG["host"]:
        record("database", FAIL, "DB_HOST not set — cannot run freshness checks")
        return

    @check("rns.fetched_at")
    def _rns():
        row = _query_one("SELECT MAX(fetched_at) AS t, COUNT(*) AS n FROM rns_announcements")
        if not row or row["t"] is None:
            return FAIL, "rns_announcements is empty"
        h = _age_hours(row["t"])
        # Monitor runs ~11:00 UTC weekdays; last morning RNS slot is 10:00 UTC.
        return _tier(h, warn_at=8, fail_at=24), f"newest {h:.1f}h ago, {row['n']} rows total"

    @check("prices.nightly_refresh")
    def _scores():
        row = _query_one("SELECT MAX(computed_at) AS t, COUNT(*) AS n FROM screener_scores")
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
        row = _query_one("SELECT MAX(date) AS d FROM price_history")
        if not row or row["d"] is None:
            return FAIL, "price_history is empty"
        d = _age_days(row["d"])
        # Loose: MAX(date) legitimately lags over weekends/holidays; the nightly
        # refresh liveness is covered by prices.nightly_refresh above.
        return _tier(d, warn_at=4, fail_at=5), f"latest trading date {row['d']} ({d}d ago)"

    @check("analysts.snapshot")
    def _analysts():
        row = _query_one(
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
        row = _query_one(
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

    @check("dividends.refresh")
    def _dividends_refresh():
        row = _query_one(
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

    @check("shorts.refresh")
    def _shorts_refresh():
        row = _query_one(
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

    @check("financials.rotation")
    def _financials():
        row = _query_one(
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
        # The rotation updates 25 stocks/run, so a healthy full cycle takes
        # ~ceil(universe / 25) days — derive the threshold from the live count
        # rather than hardcoding (the universe grows over time).
        cycle = -(-row["total"] // 25)  # ceil
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
