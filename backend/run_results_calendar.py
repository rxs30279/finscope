"""Dokploy cron entry point -- forward results calendar refresh.

Re-scrapes the Digital Look UK company diary for the current display week plus
the next few and rewrites `results_calendar`. Synchronous; exits when done.
Exits non-zero on failure.

Runs DAILY (`40 5 * * *`), not weekly, even though the page only turns over on a
Saturday. Companies move their reporting dates -- Currys, Capita, ITV and Shell
all shifted inside the five-week back-test -- and because each week is rewritten
wholesale, a daily run is what lets a moved company leave its old day. A weekly
scrape would strand logos on days nothing happens.

Usage:
    python run_results_calendar.py             # scrape and write
    python run_results_calendar.py --dry-run   # print what it found, write nothing
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from results_calendar import (
    WEEKS_AHEAD,
    _fetch_week,
    build_universe_index,
    current_week_start,
    parse_diary,
    refresh,
    _resolve_symbol,
)


def _dry_run() -> int:
    from datetime import timedelta

    index = build_universe_index()
    start = current_week_start()
    for i in range(WEEKS_AHEAD + 1):
        week = start + timedelta(weeks=i)
        events = parse_diary(_fetch_week(week), week)
        matched = []
        for e in events:
            sym, _ = _resolve_symbol(e["source_name"], index)
            if sym:
                matched.append((e["event_date"], sym, e["event_type"], e["source_name"]))
        print(f"[results_calendar] week {week}: {len(events)} events, "
              f"{len(matched)} in universe")
        for d, sym, kind, name in sorted(matched)[:10]:
            print(f"    {d} {sym:9} {kind:14} {name}")
        if len(matched) > 10:
            print(f"    ... and {len(matched) - 10} more")
    return 0


def main() -> int:
    if "--dry-run" in sys.argv[1:]:
        return _dry_run()

    print(f"[results_calendar] refresh starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = refresh()
    except Exception as e:
        print(f"[results_calendar] refresh FAILED -- {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1

    for w in result["weeks"]:
        print(f"[results_calendar]   {w['week_start']}: "
              f"{w['events']} events, {w['matched']} matched")
    print(f"[results_calendar] refresh done -- {result['events']} events, "
          f"{result['matched']} matched ({result['match_pct']}%)")

    # A totally empty scrape means the diary changed shape or started blocking
    # us; the page would silently go blank, so fail loudly instead.
    if result["status"] == "empty":
        print("[results_calendar] NO EVENTS PARSED -- diary layout or access changed")
        return 1

    print("[results_calendar] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
