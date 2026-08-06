"""The index line versus the companies inside it.

The published AIM 100 level already tells anyone it went nowhere, so "the index
was flat" is not a finding. The question worth asking is what the index line
HIDES: it is cap-weighted, so a handful of large risers can hold the headline
number flat while the typical holding is falling, and it nets opposing moves
against each other every day, so its drawdown is far shallower than the
drawdown of anything actually inside it.

Builds a cap-weighted buy-and-hold of the 2025-08-05 basket (which should track
the published index closely, and is the reconciliation check) and compares it
against the equal-weighted and per-company experience.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import numpy as np
import pandas as pd

from aim100_asof import build_prices, parse_snapshot, SNAPSHOT, DUPES
from aim100_returns import (START, END, repair_units, clean_ticks, max_drawdown)

P = lambda v: "{:+.1f}%".format(v * 100)


def main():
    then = {k: v for k, v in parse_snapshot(SNAPSHOT).items() if k not in DUPES}
    rows = pd.read_csv(os.path.join(_HERE, "aim100_asof_full.csv"))
    rows = rows[rows.in_then]
    caps = rows.set_index("symbol").cap_sort.dropna()

    px = build_prices(sorted(then))
    series = {}
    for sym, g in px.groupby("symbol"):
        g = g.reset_index(drop=True)
        g, _ = repair_units(g)
        g, _ = clean_ticks(g)
        g = g[(g.date >= pd.Timestamp(START)) & (g.date <= pd.Timestamp(END))]
        if len(g) >= 200:
            series[sym] = g.set_index("date").close

    panel = pd.DataFrame(series).sort_index().ffill()
    panel = panel[[c for c in panel.columns if c in caps.index]]
    panel = panel.dropna(axis=1)
    norm = panel / panel.iloc[0]           # each company rebased to 1.0

    w = caps.reindex(panel.columns)
    w = w / w.sum()

    capw = (norm * w).sum(axis=1)
    eqw = norm.mean(axis=1)

    print("=" * 78)
    print("RECONCILIATION: does a cap-weighted basket reproduce the index line?")
    print("=" * 78)
    print("  companies used                : {}".format(panel.shape[1]))
    print("  cap-weighted buy-and-hold     : {}".format(P(capw.iloc[-1] - 1)))
    print("  published FTSE AIM 100 (chart): about flat, ~+0.5%")
    print("  -> if these agree, the sample is sound and the gap below is real")

    print()
    print("=" * 78)
    print("WHAT THE INDEX LINE HIDES")
    print("=" * 78)
    percomp_dd = norm.apply(lambda c: max_drawdown(c.to_numpy(dtype=float)))
    rets = norm.iloc[-1] - 1

    print("  RETURN")
    print("    cap-weighted (the index)    : {}".format(P(capw.iloc[-1] - 1)))
    print("    equal-weighted (a spread)   : {}".format(P(eqw.iloc[-1] - 1)))
    print("    the MIDDLE company          : {}".format(P(rets.median())))
    print("    share of companies that rose: {:.0f}%".format((rets > 0).mean() * 100))

    print()
    print("  WORST FALL ALONG THE WAY")
    print("    the index line              : {}".format(P(max_drawdown(capw.to_numpy(dtype=float)))))
    print("    equal-weighted basket       : {}".format(P(max_drawdown(eqw.to_numpy(dtype=float)))))
    print("    the MIDDLE company          : {}".format(P(percomp_dd.median())))
    print("    companies falling 30%+      : {:.0f}%".format((percomp_dd <= -0.30).mean() * 100))
    print("    companies halving           : {:.0f}%".format((percomp_dd <= -0.50).mean() * 100))

    print()
    print("  CONCENTRATION - who held the index up")
    top = (rets * w).sort_values(ascending=False)
    print("    top 5 contributors added    : {} of index return".format(P(top.head(5).sum())))
    for s, v in top.head(5).items():
        print("      {:8s} {:>7s} return, {:.1f}% of the index".format(
            s.replace(".L", ""), P(rets[s]), w[s] * 100))

    out = pd.DataFrame({"capw": capw, "eqw": eqw})
    out.to_csv(os.path.join(_HERE, "index_vs_holdings.csv"))
    print("\nwrote index_vs_holdings.csv")


if __name__ == "__main__":
    main()
