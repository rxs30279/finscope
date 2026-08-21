"""Render Cron Job entry point — rebuild screener_scores standalone.

The scores are normally rebuilt at the end of run_prices.py. This standalone
job is the safety net / manual rebuild path (e.g. after a financials update
changes inputs that feed the scores). Synchronous; exits when done.

Replaces the /api/scores/run endpoint. Exits non-zero on failure.
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from main import compute_and_store_scores, compute_and_store_valuations, snapshot_scores


def main() -> int:
    print(f"[scores] rebuild starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = compute_and_store_scores()
        print(f"[scores] rebuilt — {result}")
    except Exception as e:
        print(f"[scores] rebuild FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    # Dated snapshot for the forward-test history table. Non-fatal: scores above
    # are already committed and this self-heals on the next run.
    try:
        snap = snapshot_scores()
        print(f"[scores] history snapshot recorded — {snap}")
    except Exception as e:
        print(f"[scores] history snapshot FAILED (non-fatal) — {type(e).__name__}: {e}")
        traceback.print_exc()

    try:
        vals = compute_and_store_valuations()
        print(f"[scores] valuation estimates rebuilt — {vals}")
        return 0
    except Exception as e:
        print(f"[scores] valuation rebuild FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
