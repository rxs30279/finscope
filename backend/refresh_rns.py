"""Full RNS pipeline: ingest → AI summaries → LLM rank.

Run directly:    python refresh_rns.py
Or scheduled:    Windows Task Scheduler → python C:\\...\\refresh_rns.py

Suggested cadence: every 15 min Mon-Fri between 07:00 and 10:00 BST
(the RNS drop window). A second run at 17:00 catches after-market items.

Each stage is wrapped so one failure doesn't stop the next: if investegate
summary fetching fails transiently, we still attempt the LLM rank on rows
that already have summaries from a previous run.
"""
import sys, os
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

import time
import traceback

from rns import _run_ingest, _backfill_summaries
from rns_llm import _rank_pending


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
    t_start = time.time()
    print(f"[rns-pipeline] starting at {time.strftime('%Y-%m-%d %H:%M:%S')}")

    ingest   = _stage("ingest",    _run_ingest, max_pages=5, stop_on_known=True, sleep_s=1.5)
    summary  = _stage("summaries", _backfill_summaries, limit=50, sleep_s=1.0, tiers=("A", "B"))
    ranking  = _stage("rank",      _rank_pending, limit=50, tiers=("A", "B"), hours=48)

    total = round(time.time() - t_start, 1)
    print(f"[rns-pipeline] complete in {total}s")
    print(f"  ingest:    {ingest}")
    print(f"  summaries: {summary}")
    print(f"  ranking:   {ranking}")
