"""One-shot / cron entry point — (re)build the UK consumer indicators table.

Fetches GfK confidence, OECD confidence history, ONS saving ratio / retail
sales, and BoE consumer credit / mortgage approvals / household money, then
upserts all of it into consumer_series (idempotent). Run this once to backfill
the /markets Consumer tab, or any time to force a refresh. Exits non-zero on
failure.

Usage:
    python backend/run_consumer.py
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from consumer import rebuild_consumer_series


def main() -> int:
    print(f"[consumer] rebuild starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = rebuild_consumer_series()
        print(f"[consumer] rebuilt — {result}")
        return 1 if result["failed"] else 0
    except Exception as e:
        print(f"[consumer] rebuild FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
