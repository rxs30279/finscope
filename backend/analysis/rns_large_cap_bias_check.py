"""Does the LLM ranker under-score results/guidance news for large caps?

Triggered by a live miss: Unilever's "2026 First Half Results" (raised full-year
guidance, margin beat, buyback, EPS beat) scored 55 despite the stock moving
+6.5% same-day -- a huge move for a GBP98bn staple. The system prompt in
rns_llm.py explicitly tells the model to discount by company size ("trivial for
a FTSE100"), with no carve-out for guidance changes. This checks whether that's
a one-off or a systemic pattern across large-cap results/trading-update stories.

Read-only. Reuses rns_score_perf.py's price-join machinery (same entry/gap/
since_news conventions) restricted to tier A results-shaped categories, and
splits the score-vs-actual-move relationship by market-cap tier.

Usage:
    python backend/analysis/rns_large_cap_bias_check.py
    python backend/analysis/rns_large_cap_bias_check.py --min-cap 2e9
"""

import argparse
import os
import sys

# Windows console defaults to cp1252, which chokes on £ signs and stray unicode
# in scraped headlines (e.g. word-joiner chars) -- force UTF-8 stdout.
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

import numpy as np
import pandas as pd

from db import query
from rns_score_perf import load_price_series, build_benchmark, compute_returns, _spearman

_RESULTS_CATEGORIES = ("final_results", "interim_results", "trading_update", "quarterly")

# GBP market-cap tiers. AIM/small-cap up to mid, FTSE250-ish mid, FTSE100-ish large.
_CAP_TIERS = [(0, 500e6, "micro/small (<0.5bn)"), (500e6, 5e9, "mid (0.5-5bn)"), (5e9, float("inf"), "large (5bn+)")]


def _cap_tier(mc):
    if mc is None:
        return "unknown"
    for lo, hi, label in _CAP_TIERS:
        if lo <= mc < hi:
            return label
    return "unknown"


def load_rows(min_cap=None):
    rows = query(
        f"""
        SELECT r.id, r.symbol, r.company_name, r.headline, r.category,
               r.published_at, r.llm_score, r.llm_sentiment, r.llm_model,
               r.llm_thesis, m.ftse_index, t.market_cap
        FROM rns_announcements r
        LEFT JOIN company_metadata m ON m.symbol = r.symbol
        LEFT JOIN LATERAL (
            SELECT market_cap FROM ttm_financials
            WHERE company_symbol = r.symbol
            ORDER BY period_end_date DESC NULLS LAST LIMIT 1
        ) t ON TRUE
        WHERE r.tier = 'A'
          AND r.category = ANY(%s)
          AND r.llm_score IS NOT NULL
          AND r.symbol IS NOT NULL
        ORDER BY r.published_at
        """,
        (list(_RESULTS_CATEGORIES),),
    )
    for r in rows:
        r["seg"] = "AIM" if (r["ftse_index"] or "").upper().find("AIM") >= 0 else "Main"
    if min_cap is not None:
        rows = [r for r in rows if (r["market_cap"] or 0) >= min_cap]
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-cap", type=float, default=None, help="only rows with market_cap >= this (GBP)")
    ap.add_argument("--csv", help="dump the flagged misses to CSV")
    args = ap.parse_args()

    print("Loading scored results/trading-update rows (tier A) ...")
    rows = load_rows(min_cap=args.min_cap)
    print(f"  {len(rows)} rows across {len({r['symbol'] for r in rows})} symbols")
    if not rows:
        return

    symbols = {r["symbol"] for r in rows}
    series = load_price_series(symbols)
    bench = build_benchmark()
    global_last = max((g["date"].iloc[-1] for g in series.values()), default=pd.Timestamp.now())
    df, skipped = compute_returns(rows, series, bench, global_last)
    if skipped:
        print(f"  ({skipped} rows skipped -- no usable entry open)")

    d1 = df[(df["horizon"] == "1d") & df["since_news"].notna()].copy()
    if d1.empty:
        print("No matured 1-day rows yet.")
        return

    # Re-attach market cap / company name / thesis (compute_returns drops them).
    meta = {r["id"]: r for r in rows}
    d1["market_cap"] = d1["id"].map(lambda i: meta[i]["market_cap"])
    d1["company_name"] = d1["id"].map(lambda i: meta[i]["company_name"])
    d1["headline"] = d1["id"].map(lambda i: meta[i]["headline"])
    d1["thesis"] = d1["id"].map(lambda i: meta[i]["llm_thesis"])
    d1["cap_tier"] = d1["market_cap"].map(_cap_tier)

    print(f"\n=== Score vs actual same-day move, results/trading-update only, by cap tier ===")
    print(f"    {len(d1)} matured 1-day rows\n")

    tier_order = [t[2] for t in _CAP_TIERS] + ["unknown"]
    print(f"   {'cap tier':<24}{'n':>5}{'Spearman(score,since_news)':>30}")
    for tier in tier_order:
        c = d1[d1["cap_tier"] == tier]
        if len(c) < 3:
            continue
        rho = _spearman(c["llm_score"].to_numpy(), c["since_news"].to_numpy())
        print(f"   {tier:<24}{len(c):>5}{rho:>30.3f}")

    # Flag misses: positive-sentiment, low-to-mid score, but a big same-day move.
    # 4% is a deliberately high bar for a large cap (small/mid caps move that much
    # routinely; large caps rarely do without real news).
    print("\n-- Flagged misses: sentiment=positive, llm_score < 60, |since_news| >= 4% --")
    miss = d1[(d1["sentiment"] == "positive") & (d1["llm_score"] < 60) & (d1["since_news"].abs() >= 0.04)]
    miss = miss.sort_values("since_news", ascending=False)
    if miss.empty:
        print("   (none)")
    else:
        for _, r in miss.iterrows():
            cap = f"£{r['market_cap']/1e9:.1f}bn" if r["market_cap"] else "n/a"
            print(f"   {r['symbol']:<8} score={r['llm_score']:>3}  since_news={r['since_news']*100:+6.1f}%  "
                  f"cap={cap:<8} {r['company_name']} -- {r['headline']}")
            if r["thesis"]:
                print(f"            thesis: {r['thesis']}")

    if args.csv:
        cols = ["id", "symbol", "company_name", "headline", "category", "published_at",
                "llm_score", "sentiment", "cap_tier", "market_cap", "gap", "raw", "since_news", "thesis"]
        d1[cols].to_csv(args.csv, index=False)
        print(f"\nFull day-1 rows written to {args.csv}")


if __name__ == "__main__":
    main()
