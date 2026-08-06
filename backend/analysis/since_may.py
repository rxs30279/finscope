"""Attribute the AIM 100's fall from its 7 May 2026 peak.

The natural story is that gold miners drove the index up, so gold coming off
must be driving it down. That is a hypothesis, not a conclusion: the same
cap-weighting that let five miners supply the year's gain would also let a
non-resource name do the damage. Decomposes the move by sector contribution
(weight x return), which is the only way to tell who actually moved the line.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import pandas as pd

from aim100_asof import build_prices, parse_snapshot, SNAPSHOT, DUPES
from aim100_returns import repair_units, clean_ticks

PEAK = pd.Timestamp("2026-05-07")
ENDD = pd.Timestamp("2026-08-05")
P = lambda v: "{:+.1f}%".format(v * 100)


def main():
    then = {k: v for k, v in parse_snapshot(SNAPSHOT).items() if k not in DUPES}
    rows = pd.read_csv(os.path.join(_HERE, "aim100_asof_full.csv"))
    rows = rows[rows.in_then]
    caps = rows.set_index("symbol").cap_sort.dropna()
    sect = rows.set_index("symbol").sector
    names = rows.set_index("symbol")["name"]

    px = build_prices(sorted(then))
    ser = {}
    for sym, g in px.groupby("symbol"):
        g = g.reset_index(drop=True)
        g, _ = repair_units(g)
        g, _ = clean_ticks(g)
        g = g[g.date <= ENDD]
        if len(g) > 200:
            ser[sym] = g.set_index("date").close

    full = pd.DataFrame(ser).sort_index().ffill()
    full = full[[c for c in full.columns if c in caps.index]].dropna(axis=1)
    panel = full[full.index >= PEAK]
    ret = panel.iloc[-1] / panel.iloc[0] - 1

    # Weights must be as at the PEAK, not at the start of the year. GGP more
    # than doubled on the way up, so its share of the index in May was roughly
    # double what it was in August 2025; start-date weights understate exactly
    # the holdings that then fell, and the contributions stop summing to the
    # index move. cap_at_peak = cap_at_sort x price appreciation to the peak.
    grow = panel.iloc[0] / full.iloc[0]
    capk = caps.reindex(panel.columns) * grow
    w = capk / capk.sum()
    contrib = ret * w

    print("=" * 74)
    print("FROM THE 7 MAY PEAK TO 5 AUG: who actually moved the index?")
    print("=" * 74)
    print("  companies: {}   index move: {}".format(len(ret), P(contrib.sum())))

    res = sect.reindex(panel.columns).isin(["Basic Materials", "Energy"])
    print()
    print("  resources    : weight {:.0f}%  median {:>7s}  CONTRIBUTED {:>7s}".format(
        w[res].sum() * 100, P(ret[res].median()), P(contrib[res].sum())))
    print("  everything else: weight {:.0f}%  median {:>7s}  CONTRIBUTED {:>7s}".format(
        w[~res].sum() * 100, P(ret[~res].median()), P(contrib[~res].sum())))

    print()
    print("  by sector (contribution = weight x return):")
    df = pd.DataFrame({"w": w, "ret": ret, "c": contrib,
                       "sec": sect.reindex(panel.columns)})
    for sec, g in df.groupby("sec"):
        if len(g) < 3:
            continue
        print("    {:24s} n={:2d}  wt {:4.1f}%  median {:>7s}  contrib {:>7s}".format(
            sec, len(g), g.w.sum() * 100, P(g.ret.median()), P(g.c.sum())))

    print()
    print("  biggest single drags:")
    for s, v in contrib.nsmallest(6).items():
        print("    {:8s} {:26s} {:>7s} return, contrib {:>7s}".format(
            s.replace(".L", ""), str(names.get(s))[:26], P(ret[s]), P(v)))
    print("  biggest single supports:")
    for s, v in contrib.nlargest(4).items():
        print("    {:8s} {:26s} {:>7s} return, contrib {:>7s}".format(
            s.replace(".L", ""), str(names.get(s))[:26], P(ret[s]), P(v)))

    print()
    print("  breadth: {:.0f}% of companies fell over the period".format(
        (ret < 0).mean() * 100))


if __name__ == "__main__":
    main()
