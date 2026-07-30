"""Multi-day: when did each morning RNS batch finish LLM ranking?

Decision input for how early the email digest can safely send. For each trading
day it looks only at the MORNING batch — Tier A/B announcements published in the
~07:00 BST spike window — and reports when the LAST of them received its
llm_processed_at (i.e. the batch was fully scored), all in UK local time.

Read-only. Usage:  python analysis/rns_morning_batch_completion.py [days_back]
"""
import os
import sys
from datetime import timezone, timedelta
from zoneinfo import ZoneInfo

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND, ".env"))

from db import query

UK = ZoneInfo("Europe/London")
DAYS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 14

# "Morning batch" = the RNS drop around the 07:00 BST open. Bound it generously
# in UK local time: published 06:30–08:30 local, Tier A/B only (the ranked set).
rows = query(
    """
    SELECT id, ticker, tier, llm_score,
           published_at, summary_fetched_at, llm_processed_at
    FROM rns_announcements
    WHERE tier IN ('A','B')
      AND published_at >= (NOW() - (%s || ' days')::interval)
      AND (published_at AT TIME ZONE 'Europe/London')::time BETWEEN '06:30' AND '08:30'
    ORDER BY published_at
    """,
    (DAYS_BACK,),
)


def to_uk(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(UK)


# Group by UK trading date
days = {}
for r in rows:
    pub = to_uk(r["published_at"])
    days.setdefault(pub.date(), []).append(r)

print(f"Morning RNS batch completion (UK local time) — last {DAYS_BACK} days\n")
print(f"{'date':<12} {'wday':<4} {'n':>3} {'first_pub':>9} {'last_pub':>9} "
      f"{'batch_done':>10} {'unscored':>8}  slowest_item")
print("-" * 86)

send_safe_times = []
for d in sorted(days):
    batch = days[d]
    n = len(batch)
    pubs = [to_uk(r["published_at"]) for r in batch]
    procs = [to_uk(r["llm_processed_at"]) for r in batch if r["llm_processed_at"]]
    unscored = sum(1 for r in batch if r["llm_processed_at"] is None)
    first_pub = min(pubs)
    last_pub = max(pubs)
    if procs:
        done = max(procs)
        send_safe_times.append(done)
        done_s = f"{done:%H:%M:%S}"
        # slowest item = the one that set batch_done
        slow = max((r for r in batch if r["llm_processed_at"]),
                   key=lambda r: r["llm_processed_at"])
        slow_lat = (to_uk(slow["llm_processed_at"]) - to_uk(slow["published_at"]))
        slow_desc = f"{slow['ticker'] or '?':<6} pub {to_uk(slow['published_at']):%H:%M} " \
                    f"+{int(slow_lat.total_seconds()//60)}m (s={slow['llm_score']})"
    else:
        done_s = "   n/a"
        slow_desc = ""
    wday = d.strftime("%a")
    print(f"{d.isoformat():<12} {wday:<4} {n:>3} {first_pub:%H:%M:%S} {last_pub:%H:%M:%S} "
          f"{done_s:>10} {unscored:>8}  {slow_desc}")

# Summary: how late is "batch done" across days, as a clock time
if send_safe_times:
    clock_secs = sorted(t.hour * 3600 + t.minute * 60 + t.second for t in send_safe_times)

    def fmt_secs(s):
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    n = len(clock_secs)
    print("\nBatch-complete clock time across days:")
    print(f"  earliest {fmt_secs(clock_secs[0])}   "
          f"median {fmt_secs(clock_secs[n // 2])}   "
          f"latest {fmt_secs(clock_secs[-1])}   (n={n} days)")
    latest = clock_secs[-1]
    print(f"\n  A send at 07:12 would be safe on {sum(1 for s in clock_secs if s <= 7*3600+12*60)}/{n} days;"
          f" 07:10 on {sum(1 for s in clock_secs if s <= 7*3600+10*60)}/{n};"
          f" 07:15 on {sum(1 for s in clock_secs if s <= 7*3600+15*60)}/{n}.")
