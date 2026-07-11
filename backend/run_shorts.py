"""Dokploy cron entry point -- daily FCA short-position refresh.

Ingests the current + historic Aggregate Net Short Position (ANSP) files the
FCA publishes each working day (from 12pm UK, ~2 working-day lag) and upserts
short_positions_agg. Synchronous; exits when done. Exits non-zero on failure.

company_metadata.isin has no independent backfill step -- it's learned
opportunistically from FCA disclosure rows themselves (see shorts.py
_resolve_symbol), since yfinance's isin lookup was tried and found to return
garbage.

Also exposes the one-time named-holder archive snapshot through this same
entry point so it can be run on the server:
  --backfill-holders <url>    snapshot the pre-13-July named-holder archive

Usage:
    python run_shorts.py                                  # daily ANSP refresh
    python run_shorts.py --backfill-holders <url-or-path>  # one-time archive snapshot
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from shorts import refresh_shorts, backfill_holder_archive, record_run


def _parse_args(argv):
    backfill_holders_arg = None
    for i, a in enumerate(argv):
        if a == "--backfill-holders" and i + 1 < len(argv):
            backfill_holders_arg = argv[i + 1]
    return backfill_holders_arg


def main() -> int:
    backfill_holders_arg = _parse_args(sys.argv[1:])

    if backfill_holders_arg:
        print(f"[shorts] holder archive backfill starting at {datetime.now(timezone.utc).isoformat()}")
        try:
            result = backfill_holder_archive(backfill_holders_arg)
            print(f"[shorts] holder archive backfill done -- {result}")
        except Exception as e:
            print(f"[shorts] holder archive backfill FAILED -- {type(e).__name__}: {e}")
            traceback.print_exc()
            return 1
        return 0

    print(f"[shorts] refresh starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = refresh_shorts()
        print(f"[shorts] refresh done -- {result}")
    except Exception as e:
        print(f"[shorts] refresh FAILED -- {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            record_run("error", {"error": str(e)})
        except Exception:
            pass
        return 1

    try:
        record_run("ok", result)
    except Exception as e:
        print(f"[shorts] pipeline_runs stamp FAILED (non-fatal) -- {type(e).__name__}: {e}")

    print("[shorts] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
