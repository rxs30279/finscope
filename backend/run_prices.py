"""Render Cron Job entry point — daily price refresh + screener score rebuild.

Fetches missing price history for the whole universe, then rebuilds the
precomputed screener_scores table (momentum/risk read price_history, so scores
must be rebuilt once fresh prices land). Synchronous; the process exits when
done, so a free-tier idle spin-down can never kill it mid-run.

Replaces the /api/prices/run endpoint + cron-job.org trigger. Exits non-zero on
failure so the Render cron run is marked failed.
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from prices import refresh_prices
from main import compute_and_store_scores


def main() -> int:
    print(f"[prices] refresh starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = refresh_prices()
        print(f"[prices] refresh done — {result}")
    except Exception as e:
        print(f"[prices] refresh FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    # Rebuild the precomputed scores now that fresh prices have landed. Prices
    # are already committed at this point, so a failure here is reported (red
    # run) but the price data still self-heals — the next run just rebuilds.
    try:
        scores = compute_and_store_scores()
        print(f"[prices] screener scores rebuilt — {scores}")
    except Exception as e:
        print(f"[prices] screener score rebuild FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    print("[prices] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
