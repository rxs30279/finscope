"""Dokploy cron entry point — weekly dividend history refresh.

Fetches full per-payment dividend history (yfinance Ticker.dividends) for the
active universe and replaces backend/dividend_events wholesale per symbol.
Weekly cadence: declared ex-dates surface weeks ahead, so a weekly sweep keeps
next-ex-date fresh without burning ~630 yfinance calls/day for near-zero delta.
Synchronous; exits when done. Exits non-zero on failure.

Usage:
    python run_dividends.py                      # full active universe
    python run_dividends.py --symbols GRG.L,BP.L  # local testing on a slice
    python run_dividends.py --limit 20            # first N active symbols
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from dividends import refresh_dividends, record_run, query


def _parse_args(argv):
    symbols = None
    limit = None
    for i, a in enumerate(argv):
        if a == "--symbols" and i + 1 < len(argv):
            symbols = [s.strip() for s in argv[i + 1].split(",") if s.strip()]
        elif a == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
    return symbols, limit


def main() -> int:
    symbols, limit = _parse_args(sys.argv[1:])
    if limit and not symbols:
        symbols = [
            r["symbol"]
            for r in query(
                "SELECT symbol FROM company_metadata WHERE is_active ORDER BY symbol LIMIT %s",
                (limit,),
            )
        ]

    print(f"[dividends] refresh starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = refresh_dividends(symbols)
        print(f"[dividends] refresh done — {result}")
    except Exception as e:
        print(f"[dividends] refresh FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            record_run("error", {"error": str(e)})
        except Exception:
            pass
        return 1

    try:
        record_run("ok", result)
    except Exception as e:
        print(f"[dividends] pipeline_runs stamp FAILED (non-fatal) — {type(e).__name__}: {e}")

    print("[dividends] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
