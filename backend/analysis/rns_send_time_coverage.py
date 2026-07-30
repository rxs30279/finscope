"""Digest send-time coverage: for each candidate send time, what share of the
morning's Tier A/B RNS (and of the high-impact s>=76 subset) is already
PUBLISHED AND SCORED by then?

This is the real send-time decision input. A late-published item is not "slow" —
it simply doesn't exist at 07:10, so sending earlier trades coverage of the
late-morning tail for timeliness. Read-only.

Usage:  python analysis/rns_send_time_coverage.py [days_back]
"""
import os
import sys
from datetime import timezone
from zoneinfo import ZoneInfo

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND, ".env"))

from db import query

UK = ZoneInfo("Europe/London")
DAYS_BACK = int(sys.argv[1]) if len(sys.argv) > 1 else 21
SEND_TIMES = ["07:10", "07:15", "07:20", "07:30", "08:00"]
HIGH = 76  # high-impact score threshold

rows = query(
    """
    SELECT tier, llm_score, published_at, llm_processed_at
    FROM rns_announcements
    WHERE tier IN ('A','B')
      AND published_at >= (NOW() - (%s || ' days')::interval)
      AND (published_at AT TIME ZONE 'Europe/London')::time BETWEEN '06:30' AND '10:00'
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


def secs_of(t):
    h, m = t.split(":")
    return int(h) * 3600 + int(m) * 60


def clock(dt):
    return dt.hour * 3600 + dt.minute * 60 + dt.second


days = {}
for r in rows:
    pub = to_uk(r["published_at"])
    days.setdefault(pub.date(), []).append(r)

# An item is "available" by send time T if it was BOTH published and scored
# at or before T (both in UK clock time).
def available_by(r, t_secs):
    pub = to_uk(r["published_at"])
    proc = to_uk(r["llm_processed_at"])
    if proc is None:
        return False
    return clock(pub) <= t_secs and clock(proc) <= t_secs


print(f"Digest send-time coverage — last {DAYS_BACK} days, morning Tier A/B\n")
print("Per day: total morning A/B items, and how many are published+scored by each send time")
hdr = f"{'date':<12} {'tot':>3} " + " ".join(f"{t:>7}" for t in SEND_TIMES) + "   | high-impact(>=76) covered by each"
print(hdr)
print("-" * len(hdr))

agg = {t: [] for t in SEND_TIMES}
agg_high = {t: [] for t in SEND_TIMES}
for d in sorted(days):
    batch = days[d]
    tot = len(batch)
    highs = [r for r in batch if (r["llm_score"] or 0) >= HIGH]
    cov = []
    hcov = []
    for t in SEND_TIMES:
        ts = secs_of(t)
        c = sum(1 for r in batch if available_by(r, ts))
        cov.append(c)
        agg[t].append((c, tot))
        hc = sum(1 for r in highs if available_by(r, ts))
        hcov.append(hc)
        agg_high[t].append((hc, len(highs)))
    cov_s = " ".join(f"{c:>3}/{tot:<3}" for c in cov)
    hi_s = " ".join(f"{hc}/{len(highs)}" for hc in hcov)
    print(f"{d.isoformat():<12} {tot:>3} {cov_s}   | {hi_s}")

print("\nAggregate coverage across all days:")
tot_all = sum(t for _, t in agg[SEND_TIMES[0]])
high_all = sum(t for _, t in agg_high[SEND_TIMES[0]])
for t in SEND_TIMES:
    covered = sum(c for c, _ in agg[t])
    hcovered = sum(c for c, _ in agg_high[t])
    print(f"  send {t}:  A/B {covered}/{tot_all} ({100*covered/tot_all:.0f}%)"
          f"   high-impact {hcovered}/{high_all} ({100*hcovered/high_all if high_all else 0:.0f}%)")

print("\nWhat a send at 07:10 would MISS vs 07:20 (items published+scored in 07:10<..<=07:20):")
any_miss = False
for d in sorted(days):
    batch = days[d]
    miss = [r for r in batch
            if available_by(r, secs_of("07:20")) and not available_by(r, secs_of("07:10"))]
    if miss:
        any_miss = True
        hi = sum(1 for r in miss if (r["llm_score"] or 0) >= HIGH)
        scores = sorted((r["llm_score"] or 0) for r in miss)
        print(f"  {d.isoformat()}: {len(miss)} items, scores {scores}, {hi} high-impact")
if not any_miss:
    print("  (none — 07:10 and 07:20 cover the same items on every day)")
