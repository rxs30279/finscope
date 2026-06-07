"""One-shot / cron entry point — (re)build the Fear & Greed daily history.

Reconstructs the trailing-year UK Fear & Greed series from price data and pulls
CNN's US history, then upserts both into fear_greed_history (idempotent). Run
this once to backfill the chart, or any time to force a refresh. The daily
finscope-prices cron already calls the same function, so this is the manual /
backfill path. Exits non-zero on failure.

Usage:
    python backend/run_fg_history.py
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from market import _rebuild_fear_greed_history


def main() -> int:
    print(f"[fg-history] rebuild starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = _rebuild_fear_greed_history()
        print(f"[fg-history] rebuilt — {result}")
        return 0
    except Exception as e:
        print(f"[fg-history] rebuild FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
