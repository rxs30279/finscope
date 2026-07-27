"""Dokploy cron entry point -- weekly "story of the week" pick.

Selects the best scored-before-the-open RNS announcement from the trailing week
(and the price reaction it called) and snapshots it into landing_story, which the
marketing landing page renders. Synchronous; exits when done. Exits non-zero on
failure.

Runs Monday early -- `20 6 * * 1` -- so the previous week's prices have settled.
A thin week is not an error: nothing qualifies, the previous row stays live, and
the run is stamped 'skipped'.

Usage:
    python run_landing_story.py             # pick and write
    python run_landing_story.py --dry-run   # print the pick, write nothing
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from landing_story import pick_story, record_run, select_candidate


def _dry_run() -> int:
    cand = select_candidate()
    if cand is None:
        print("[landing_story] dry-run -- no qualifying story in the trailing week")
        return 0
    print(
        f"[landing_story] dry-run -- would pick {cand['symbol']} "
        f"({cand['company_name']}), score {cand['llm_score']} {cand['direction']}, "
        f"gap {cand['gap_pct']:+.2f}% "
        f"({float(cand['prev_close']):.2f}p -> {float(cand['event_open']):.2f}p) "
        f"on {cand['event_date']}"
    )
    print(f"[landing_story]   {cand['headline']}")
    print(f"[landing_story]   {cand['llm_thesis']}")
    return 0


def main() -> int:
    if "--dry-run" in sys.argv[1:]:
        return _dry_run()

    print(f"[landing_story] pick starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = pick_story()
        print(f"[landing_story] pick done -- {result}")
    except Exception as e:
        print(f"[landing_story] pick FAILED -- {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            record_run("error", {"error": str(e)})
        except Exception:
            pass
        return 1

    try:
        record_run(result.get("status", "ok"), result)
    except Exception as e:
        print(f"[landing_story] pipeline_runs stamp FAILED (non-fatal) -- {type(e).__name__}: {e}")

    print("[landing_story] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
