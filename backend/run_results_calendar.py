"""Dokploy cron entry point -- forward results calendar refresh.

Re-scrapes the Sharecast UK company diary for the current display week plus the
next few and rewrites `results_calendar`. Synchronous; exits when done.
Exits non-zero on failure.

Source changed from Digital Look on 2026-08-17, after that site went into an
open-ended maintenance mode; see results_calendar's module docstring for the
evaluation and for the URL gotcha around the current week.

Runs DAILY (`40 5 * * *`), not weekly, even though the page only turns over on a
Saturday. Companies move their reporting dates -- Currys, Capita, ITV and Shell
all shifted inside the five-week back-test -- and because each week is rewritten
wholesale, a daily run is what lets a moved company leave its old day. A weekly
scrape would strand logos on days nothing happens.

Also backfills the FTSE 100 from yfinance, because a diary can silently omit
companies as well as move them. That adds ~40s of throttled requests. `status`
still counts diary events only, so a working cross-check can never disguise a
broken scrape.

Yahoo's dates drift FORWARDS after a company reports, not just stale-in-the-past,
so those rows are filtered against our own results RNS -- see
results_calendar.drop_reported_dates. A week the diary fails to serve is left
untouched rather than rewritten empty; the run still exits 1 either way.

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
    YF_CROSS_CHECK,
    DiaryUnavailable,
    _fetch_week,
    build_universe_index,
    cross_check_events,
    current_week_start,
    drop_reported_dates,
    fetch_index_earnings_dates,
    parse_diary,
    recent_results_dates,
    refresh,
    _resolve_symbol,
)


def _dry_run() -> int:
    from datetime import timedelta

    index = build_universe_index()
    start = current_week_start()
    yf_dates = fetch_index_earnings_dates() if YF_CROSS_CHECK else {}
    if yf_dates:
        # Same suppression refresh() applies, or the dry run would advertise rows
        # the real run will not write.
        reported = recent_results_dates()
        kept = drop_reported_dates(yf_dates, reported)
        for sym in sorted(set(yf_dates) - set(kept)):
            print(f"[results_calendar] yfinance {sym} {yf_dates[sym]} dropped "
                  f"-- already reported {reported[sym]}")
        yf_dates = kept
    for i in range(WEEKS_AHEAD + 1):
        week = start + timedelta(weeks=i)
        try:
            events = parse_diary(_fetch_week(week), week)
        except DiaryUnavailable as exc:
            print(f"[results_calendar] week {week}: UNAVAILABLE -- {exc}")
            continue
        matched = []
        for e in events:
            e["symbol"], _ = _resolve_symbol(e["source_name"], index)
            if e["symbol"]:
                matched.append((e["event_date"], e["symbol"], e["event_type"],
                                e["source_name"]))
        extra = cross_check_events(yf_dates, week, events)
        print(f"[results_calendar] week {week}: {len(events)} events, "
              f"{len(matched)} in universe, +{len(extra)} cross-check")
        for d, sym, kind, name in sorted(matched)[:10]:
            print(f"    {d} {sym:9} {kind:14} {name}")
        if len(matched) > 10:
            print(f"    ... and {len(matched) - 10} more")
        for e in extra:
            print(f"    {e['event_date']} {e['symbol']:9} {'yfinance':14} "
                  f"(diary silent)")
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
        if w.get("skipped"):
            print(f"[results_calendar]   {w['week_start']}: SKIPPED "
                  f"({w['skipped']}) -- existing rows left in place")
            continue
        print(f"[results_calendar]   {w['week_start']}: "
              f"{w['events']} events, {w['matched']} matched, "
              f"+{w['cross_check']} from the FTSE 100 cross-check")
    print(f"[results_calendar] refresh done -- {result['events']} diary events, "
          f"{result['matched']} matched ({result['match_pct']}%), "
          f"+{result['cross_check']} cross-check rows")

    # A totally empty scrape means the diary changed shape or started blocking
    # us; the page would silently go blank, so fail loudly instead. `status`
    # counts DIARY events only, so a healthy cross-check cannot mask this.
    #
    # This still exits 1 when every week was skipped. The skip protects the
    # STORED rows, which stop being trustworthy the moment they stop being
    # refreshed -- a moved date can no longer leave its old day. Frozen is better
    # than blank, but it is not fine, and it must keep paging.
    if result["status"] == "empty":
        print("[results_calendar] NO EVENTS PARSED -- diary layout or access changed")
        if result.get("skipped"):
            print(f"[results_calendar] {len(result['skipped'])} week(s) left "
                  f"untouched rather than blanked: {', '.join(result['skipped'])}")
        return 1

    print("[results_calendar] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
