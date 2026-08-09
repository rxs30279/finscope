"""Full RNS pipeline: ingest → AI summaries → LLM rank.

Run directly:    python refresh_rns.py
Or scheduled:    Windows Task Scheduler → python C:\\...\\refresh_rns.py

Suggested cadence: every 15 min Mon-Fri between 07:00 and 10:00 BST
(the RNS drop window). A second run at 17:00 catches after-market items.

Each stage is wrapped so one failure doesn't stop the next: if investegate
summary fetching fails transiently, we still attempt the LLM rank on rows
that already have summaries from a previous run.

Each run reads up to DEFAULT_MAX_PAGES (10 x 50 = 500 items) but stops as soon
as a page yields nothing new, so a quiet run costs two page fetches. The
ceiling matters only at 07:00, which is the busiest 15 minutes of every
trading day without exception.

Smart catch-up: if the newest stored announcement is more than 6h old (e.g.
after the PC was off for a few days), the ingest dynamically bumps
max_pages so the run catches up to the present. Capped at 24 pages — that
is investegate's hard listing limit; anything beyond returns empty HTML.
At 50 items/page the site retains roughly 2.5 trading days of history, so
longer outages will lose the middle of the gap permanently.
"""
import sys, os
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

import math
import time
import traceback
from datetime import datetime, timezone

from rns import _run_ingest, _backfill_summaries, _query
from rns_llm import _rank_pending


# 10 pages = 500 items of reach per run. Was 5 (=250), which the 07:00 drop
# overflowed: measured over 14 days the busiest 15-minute bucket is 07:00 on
# every single day, normally 87-149 items but 253 on 2026-08-03 — past the old
# ceiling, and overflow is lost permanently (see _run_ingest's early exit).
# Raising the ceiling is nearly free because it is a ceiling, not a target: the
# loop stops as soon as a page yields no new rows, so a quiet run still reads
# two pages and stops.
DEFAULT_MAX_PAGES    = 10
# 12 pages/day = 600 items. Was 6 (=300), which described the feed before it
# was measured: over 14 days a trading day actually runs 300-720 items (720 on
# 2026-08-03). Under-counting here silently loses the middle of a 1-2 day gap,
# because a catch-up run that doesn't reach far enough back can never recover
# the rows it skipped. Beyond ~2 days CATCHUP_PAGE_CAP dominates anyway.
PAGES_PER_DAY_BUDGET = 12
CATCHUP_BUFFER_PAGES = 3    # extra headroom beyond the computed need
CATCHUP_PAGE_CAP     = 24   # investegate's hard listing limit — page 25+ returns empty
CATCHUP_THRESHOLD_H  = 6    # don't bother bumping unless we're 6h+ stale

# Fixed 64-bit key for the pipeline-wide advisory lock ('RNS\0' as an int).
# Lives here because this module is imported by run_rns.py, so both entry points
# share one definition — two keys would mean two locks and no mutual exclusion.
# Any other advisory lock added to this database must not reuse this value.
RNS_PIPELINE_LOCK_KEY = 0x524E5300


def _compute_max_pages() -> tuple[int, str]:
    """Pick max_pages based on staleness of stored data.

    Returns (pages, reason) — reason is a short human-readable summary for the log.
    """
    try:
        rows = _query("SELECT MAX(published_at) AS last FROM rns_announcements")
    except Exception as e:
        return DEFAULT_MAX_PAGES, f"staleness check failed ({e}) — using default"

    last = rows[0]["last"] if rows else None
    if last is None:
        return DEFAULT_MAX_PAGES, "empty table — using default"

    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600

    if hours < CATCHUP_THRESHOLD_H:
        return DEFAULT_MAX_PAGES, f"latest row {hours:.1f}h old — no catch-up needed"

    needed = math.ceil(hours / 24 * PAGES_PER_DAY_BUDGET) + CATCHUP_BUFFER_PAGES
    pages  = max(DEFAULT_MAX_PAGES, min(CATCHUP_PAGE_CAP, needed))
    return pages, f"latest row {hours:.1f}h old — catching up with {pages} pages"


def _stage(name: str, fn, *args, **kwargs) -> dict:
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = round(time.time() - t0, 1)
        print(f"[rns-pipeline] {name} done in {elapsed}s — {result}")
        return {"ok": True, "elapsed": elapsed, **(result or {})}
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        print(f"[rns-pipeline] {name} FAILED in {elapsed}s — {e}")
        traceback.print_exc()
        return {"ok": False, "elapsed": elapsed, "error": str(e)}


if __name__ == "__main__":
    # Shares the lock with run_rns.py so a manual run here can't race the
    # Dokploy crons — both would otherwise re-rank the same pending rows.
    from db import advisory_lock

    with advisory_lock(RNS_PIPELINE_LOCK_KEY) as _acquired:
        if not _acquired:
            print("[rns-pipeline] another pipeline run is in flight — nothing to do")
            sys.exit(0)

        t_start = time.time()
        print(f"[rns-pipeline] starting at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        max_pages, reason = _compute_max_pages()
        print(f"[rns-pipeline] {reason}")

        ingest   = _stage("ingest",    _run_ingest, max_pages=max_pages, stop_on_known=True, sleep_s=1.5)
        summary  = _stage("summaries", _backfill_summaries, limit=50, sleep_s=1.0, tiers=("A", "B"))
        ranking  = _stage("rank",      _rank_pending, limit=50, tiers=("A", "B"), hours=48)

        total = round(time.time() - t_start, 1)
        print(f"[rns-pipeline] complete in {total}s")
        print(f"  ingest:    {ingest}")
        print(f"  summaries: {summary}")
        print(f"  ranking:   {ranking}")
