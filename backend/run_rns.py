"""Render Cron Job entry point — full RNS pipeline.

Runs ingest -> summaries -> LLM rank -> prune synchronously, then exits. This
replaces the /api/rns/run endpoint + cron-job.org trigger: Render's own
scheduler invokes this script directly (see render.yaml), so there is no HTTP
server, no background thread, and no keep-warm pinging. The instance lives until
this process exits, so the work can never be spun down mid-run.

Exits non-zero on failure so the Render cron run is marked failed (visible in
the dashboard and alertable), rather than failing silently.
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from rns import _run_ingest, _backfill_summaries, _prune_old
from rns_llm import _rank_pending
from refresh_rns import _compute_max_pages


def main() -> int:
    print(f"[rns] pipeline starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        # Stage 1: Ingest
        max_pages, reason = _compute_max_pages()
        print(f"[rns] ingest: {reason}")
        ingest = _run_ingest(max_pages=max_pages, stop_on_known=True, sleep_s=1.5)
        print(f"[rns] ingest done — {ingest}")

        # Stage 2: Backfill summaries
        summaries = _backfill_summaries(limit=50, sleep_s=1.0, tiers=("A", "B"))
        print(f"[rns] summaries done — {summaries}")

        # Stage 3: LLM rank
        ranked = _rank_pending(limit=50, tiers=("A", "B"), hours=48)
        print(f"[rns] ranking done — {ranked}")

        # Stage 3.5: High Impact RNS showcase — flag new candidates and snapshot
        # follow-ups for tracked companies. Entries stay live until the admin
        # archives them manually (no auto-archive). Runs after ranking (needs
        # llm_* populated) and before the prune (needs the follow-ups copied out
        # before the source rows are deleted). Non-fatal: a showcase bug must
        # never block the prune stage that keeps the table from growing unbounded.
        try:
            from showcase import flag_high_impact_candidates, record_followups
            print(f"[rns] showcase flagging — {flag_high_impact_candidates(hours=48)}")
            print(f"[rns] showcase follow-ups — {record_followups()}")
        except Exception as e:
            print(f"[rns] showcase stage FAILED (non-fatal) — {type(e).__name__}: {e}")

        # Stage 4: Prune old rows (Tier C only, keep 14 days; A/B retained indefinitely)
        pruned = _prune_old(days=14)
        print(f"[rns] prune done — {pruned}")

        print("[rns] pipeline completed successfully")
        return 0
    except Exception as e:
        print(f"[rns] pipeline FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
