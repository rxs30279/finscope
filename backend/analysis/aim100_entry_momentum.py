"""Does AIM 100 entry momentum persist AFTER entry, or is it already priced in?

Finding 04 of the AIM risk article. The tempting version of this question is
circular: joiners show a large gain over the year they joined, but that IS the
gain that caused their promotion, and nobody could have captured it.

So this measures forward ONLY: returns from the entry snapshot date onward,
against the INCUMBENTS of the same transition. Comparing to incumbents rather
than to the whole market matters because both sides then share a time period,
so a good or bad stretch for AIM cancels out.

Result at time of writing: entrants beat incumbents at 3m/6m/12m (medians
+1.2/+4.4/+4.3% against -4.5/-6.9/-9.8%, Mann-Whitney p=0.028/0.001/0.004).
Treat as suggestive, not proven - n=39 over 4 intakes, and ~1 in 6 companies
here are absent from price data entirely (mostly takeovers), which hits the
incumbent side harder and so probably flatters the entrant margin.

Usage:
    python aim100_membership_timeline.py --download   # first
    python aim100_entry_momentum.py --download        # prices for the cohort
    python aim100_entry_momentum.py
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND)
sys.path.insert(0, _HERE)

import numpy as np
import pandas as pd
from scipy import stats

from aim100_returns import repair_units, clean_ticks, px_on

CLOSE_PKL = os.path.join(_HERE, "mom_close.pkl")
TRANSITIONS = os.path.join(_HERE, "transitions.json")
HORIZONS = {"3m": 91, "6m": 182, "12m": 365}
END_CAP = datetime(2026, 8, 6)

P = lambda v: f"{v * 100:+.1f}%"


def download(symbols):
    import yfinance as yf
    df = yf.download(symbols, start="2023-06-01", end="2026-08-06",
                     auto_adjust=True, progress=False, threads=True,
                     group_by="column")
    df["Close"].to_pickle(CLOSE_PKL)
    got = int(df["Close"].notna().any().sum())
    print(f"cached {got}/{len(symbols)} symbols")
    missing = [s for s in symbols
               if s not in df["Close"].columns or df["Close"][s].notna().sum() == 0]
    if missing:
        print(f"unpriceable ({len(missing)}), mostly delisted/taken over: {missing}")


def load():
    close = pd.read_pickle(CLOSE_PKL)
    d = close.stack().rename("close").reset_index()
    d.columns = ["date", "symbol", "close"]
    d["date"] = pd.to_datetime(d["date"])
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d[d["close"] > 0].sort_values(["symbol", "date"])
    out = {}
    for sym, g in d.groupby("symbol"):
        g = g.reset_index(drop=True)
        g, _ = repair_units(g)
        g, _ = clean_ticks(g)
        out[sym] = g
    return out


def fwd_returns(g, entry):
    """Forward returns from `entry`, skipping horizons past the data end."""
    p0 = px_on(g, entry.date())
    if not p0:
        return {}
    out = {}
    for label, days in HORIZONS.items():
        target = entry + timedelta(days=days)
        if target > END_CAP:
            continue
        p1 = px_on(g, target.date())
        if p1:
            out[label] = p1 / p0 - 1.0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()

    transitions = json.load(open(TRANSITIONS))
    universe = sorted({s for t in transitions
                       for s in t["entrants"] + t["incumbents"]})
    if args.download:
        download(universe)
        return
    if not os.path.exists(CLOSE_PKL):
        raise SystemExit("no price cache - run with --download first")

    px = load()
    rows = []
    for t in transitions:
        entry = datetime.strptime(t["curr"], "%Y%m%d")
        for group, syms in (("entrant", t["entrants"]),
                            ("incumbent", t["incumbents"])):
            for sym in syms:
                if sym not in px:
                    continue
                for h, v in fwd_returns(px[sym], entry).items():
                    rows.append({"transition": t["curr"], "symbol": sym,
                                 "group": group, "horizon": h, "ret": v})

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(_HERE, "aim100_entry_momentum.csv"), index=False)

    print("=" * 92)
    print("POST-ENTRY FORWARD RETURNS: entrants vs incumbents of the same intake")
    print("=" * 92)
    for h in HORIZONS:
        sub = df[df.horizon == h]
        e, i = sub[sub.group == "entrant"].ret, sub[sub.group == "incumbent"].ret
        if len(e) < 5 or len(i) < 5:
            print(f"\n{h}: too few (entrants={len(e)}, incumbents={len(i)})")
            continue
        _, p = stats.mannwhitneyu(e, i, alternative="two-sided")
        print(f"\n--- {h} forward ---")
        print(f"  entrants   n={len(e):3d}  median {P(e.median()):>7s}  "
              f"mean {P(e.mean()):>7s}  % up {(e > 0).mean() * 100:5.1f}%")
        print(f"  incumbents n={len(i):3d}  median {P(i.median()):>7s}  "
              f"mean {P(i.mean()):>7s}  % up {(i > 0).mean() * 100:5.1f}%")
        print(f"  Mann-Whitney p = {p:.3f}")

    print("\n" + "=" * 92)
    print("PER-INTAKE (each entrant against its own cohort's incumbents)")
    print("=" * 92)
    for h in HORIZONS:
        print(f"\n--- {h} forward ---")
        sub = df[df.horizon == h]
        for tx, g in sub.groupby("transition"):
            e, i = g[g.group == "entrant"].ret, g[g.group == "incumbent"].ret
            if len(e) < 2 or len(i) < 5:
                continue
            print(f"  {tx}  entrants n={len(e):2d} median {P(e.median()):>7s}   "
                  f"incumbents n={len(i):3d} median {P(i.median()):>7s}   "
                  f"diff {P(e.median() - i.median()):>7s}")

    print("\n" + "=" * 92)
    print("POOLED EXCESS (entrant minus its own intake's incumbent median)")
    print("=" * 92)
    for h in HORIZONS:
        sub = df[df.horizon == h]
        bench = sub[sub.group == "incumbent"].groupby("transition").ret.median()
        e = sub[sub.group == "entrant"].copy()
        e["excess"] = e.apply(lambda r: r.ret - bench.get(r.transition, np.nan), axis=1)
        e = e.dropna(subset=["excess"])
        if len(e) < 5:
            continue
        p = stats.wilcoxon(e.excess)[1] if len(e) >= 10 else None
        print(f"  {h}: n={len(e):3d}  median excess {P(e.excess.median()):>7s}  "
              f"mean {P(e.excess.mean()):>7s}  "
              f"% beating their cohort {(e.excess > 0).mean() * 100:5.1f}%"
              + (f"  wilcoxon p={p:.3f}" if p is not None else ""))


if __name__ == "__main__":
    main()
