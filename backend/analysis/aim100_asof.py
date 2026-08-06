"""Re-run the AIM 100 analysis on the index as it ACTUALLY stood on 2025-08-05.

The first pass used today's constituent list, which is a look-ahead: a company
that soared during the year gets promoted INTO the AIM 100 and then shows up in
the sample as if you could have owned it from the start. Web-archive snapshots of
Hargreaves Lansdown's constituent page (the same page backend/refresh_index_
membership.py already scrapes) give the real membership on 2025-08-05.

Reuses aim100_returns.py's price cleaning wholesale, so the two runs differ only
in WHICH companies are in the sample.

Usage:  python aim100_asof.py
"""
import json
import os
import sys
from io import StringIO

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND)
sys.path.insert(0, _HERE)

import numpy as np
import pandas as pd
from scipy import stats

from db import query
from universe_common import to_yf_symbol
from aim100_returns import (START, END, PRIOR_START, SORT_DATE, PX_TO_GBP,
                            repair_units, clean_ticks, px_on, ann_vol,
                            max_drawdown, share_count)

SNAPSHOT = os.path.join(_HERE, "wb_20250805.html")   # archived 2025-08-05
LEAVERS = os.path.join(_HERE, "leavers_close.pkl")   # refetched departed names

# Young & Co's Brewery lists two share classes; HL carries both, they are one
# company, and keeping both would double-count it.
DUPES = {"YNGN.L"}

# Ticker renames. A rename looks EXACTLY like a delisting from here - the old
# symbol 404s on Yahoo and is gone from company_metadata - so an unchecked
# "unpriceable" list quietly reclassifies live companies as dead ones. Begbies
# Traynor rebranded to BTG Consulting in Feb 2026 and was wrongly counted as
# taken over until each missing name was checked individually. Prices for the
# new symbol are cached into LEAVERS under the OLD symbol, which is the one the
# archived index page uses.
RENAMES = {"BEG.L": "BTG.L"}  # Begbies Traynor -> BTG Consulting, Feb 2026


def parse_snapshot(path):
    """{yf_symbol: name} from an archived HL constituent page."""
    html = open(path, encoding="utf-8", errors="replace").read()
    best = None
    for t in pd.read_html(StringIO(html)):
        cols = [str(c) for c in t.columns]
        if "EPIC" in cols and "Name" in cols:
            sub = t[["EPIC", "Name"]].dropna()
            sub = sub[sub["EPIC"].astype(str).str.match(r"^[A-Z0-9.&-]{1,7}$")]
            if best is None or len(sub) > len(best):
                best = sub
    return {to_yf_symbol(r.EPIC): str(r.Name).strip() for r in best.itertuples()}


def build_prices(symbols):
    """Long frame of cleaned closes for `symbols`, from both caches."""
    frames = []
    for pkl, vol_pkl in [(os.path.join(_HERE, "yf_close.pkl"),
                          os.path.join(_HERE, "yf_vol.pkl")),
                         (LEAVERS, None)]:
        if not os.path.exists(pkl):
            continue
        close = pd.read_pickle(pkl)
        cols = [c for c in close.columns if c in set(symbols)]
        if not cols:
            continue
        d = close[cols].stack().rename("close").reset_index()
        d.columns = ["date", "symbol", "close"]
        if vol_pkl and os.path.exists(vol_pkl):
            v = pd.read_pickle(vol_pkl)[cols].stack().rename("volume").reset_index()
            v.columns = ["date", "symbol", "volume"]
            d = d.merge(v, on=["date", "symbol"], how="left")
        else:
            d["volume"] = 0.0
        frames.append(d)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "date"])
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    return df[df["close"] > 0].sort_values(["symbol", "date"])


def metrics(px, quote_ccy):
    recs = []
    for sym, g in px.groupby("symbol"):
        g = g.reset_index(drop=True)
        g, _ = repair_units(g)
        g, _ = clean_ticks(g)
        p0, p1, psort = px_on(g, START), px_on(g, END), px_on(g, SORT_DATE)
        if not p0 or not p1 or p0 <= 0:
            continue
        win = g[(g["date"] >= pd.Timestamp(START)) & (g["date"] <= pd.Timestamp(END))]
        pri = g[(g["date"] >= pd.Timestamp(PRIOR_START)) & (g["date"] < pd.Timestamp(START))]
        if len(win) < 200:
            continue
        wc = win["close"].to_numpy(dtype=float)
        recs.append({
            "symbol": sym, "px_sort": psort,
            "px_gbp_factor": PX_TO_GBP.get(quote_ccy.get(sym, "GBp"), 0.01),
            "ret_1y": p1 / p0 - 1.0,
            "maxdd": max_drawdown(wc),
            "vol_window": ann_vol(wc),
            "vol_prior": ann_vol(pri["close"].to_numpy(dtype=float)),
        })
    return pd.DataFrame(recs)


def pct(x):
    return f"{x * 100:+.1f}%"


def summarise(label, r, dd=None):
    print(f"  {label:34s} n={len(r):3d}  median {pct(r.median()):>7s}  "
          f"mean {pct(r.mean()):>7s}  % up {(r > 0).mean() * 100:5.1f}%  "
          f"% lost 30%+ {(r <= -0.30).mean() * 100:5.1f}%")


def main():
    then = parse_snapshot(SNAPSHOT)
    then = {k: v for k, v in then.items() if k not in DUPES}
    now = {r["symbol"]: r["name"] for r in
           query("SELECT symbol, name FROM company_metadata "
                 "WHERE ftse_index = 'FTSE AIM 100'")}
    left, joined = sorted(set(then) - set(now)), sorted(set(now) - set(then))
    print(f"AIM 100 on 2025-08-05: {len(then)} companies")
    print(f"AIM 100 today        : {len(now)} companies")
    print(f"  left during the year : {len(left)}")
    print(f"  joined during the year: {len(joined)}")
    print(f"  held throughout       : {len(set(then) & set(now))}")

    meta = {r["symbol"]: r for r in query(
        "SELECT symbol, name, sector, currency, financial_currency, ftse_index "
        "FROM company_metadata WHERE symbol = ANY(%s)",
        (sorted(set(then) | set(now)),))}
    quote_ccy = {s: m["currency"] for s, m in meta.items()}

    px = build_prices(sorted(set(then) | set(now)))
    m = metrics(px, quote_ccy)
    m["in_then"] = m.symbol.isin(then)
    m["in_now"] = m.symbol.isin(now)
    m["sector"] = m.symbol.map(lambda s: (meta.get(s) or {}).get("sector"))

    asof = m[m.in_then]
    today = m[m.in_now]
    missing = sorted(set(then) - set(m.symbol))
    print(f"\n  priced from the 2025-08-05 list: {len(asof)}/{len(then)}"
          f"   unpriceable: {missing}")

    print("\n" + "=" * 96)
    print("HEADLINE: the index you could actually have bought vs the one we published")
    print("=" * 96)
    summarise("AS-OF 2025-08-05 (correct)", asof.ret_1y)
    summarise("today's constituents (published)", today.ret_1y)
    summarise("  of those, the 25 that JOINED", m[m.in_now & ~m.in_then].ret_1y)
    summarise("  the 26 that LEFT", m[m.in_then & ~m.in_now].ret_1y)

    print(f"\n  median worst fall, as-of list : {pct(asof.maxdd.median())}")
    print(f"  median worst fall, today's    : {pct(today.maxdd.median())}")
    print(f"  % that fell 30%+ intra-year   : as-of {(asof.maxdd <= -0.3).mean() * 100:.1f}%"
          f"   today's {(today.maxdd <= -0.3).mean() * 100:.1f}%")
    print(f"  % that halved intra-year      : as-of {(asof.maxdd <= -0.5).mean() * 100:.1f}%"
          f"   today's {(today.maxdd <= -0.5).mean() * 100:.1f}%")

    srt = asof.ret_1y.sort_values(ascending=False)
    tot = asof.ret_1y.sum()
    print(f"\n  concentration, as-of list: top 5 = "
          f"{srt.head(5).sum() / tot * 100:.1f}% of the total return "
          f"(published figure was 71.7%)")
    print(f"  best 5 as-of: " + ", ".join(
        f"{s.replace('.L','')} {pct(v)}" for s, v in
        zip(asof.set_index('symbol').ret_1y.nlargest(5).index,
            asof.ret_1y.nlargest(5))))
    print(f"  worst 5 as-of: " + ", ".join(
        f"{s.replace('.L','')} {pct(v)}" for s, v in
        zip(asof.set_index('symbol').ret_1y.nsmallest(5).index,
            asof.ret_1y.nsmallest(5))))

    # ---- does the size effect survive on the correct membership? ----
    fund = pd.DataFrame(query(
        "SELECT company_symbol AS symbol, period_end_date, revenue, net_income, "
        "       total_equity, shares_outstanding, shares_diluted, shares_basic, "
        "       revenue_per_share, book_value_per_share, eps_basic "
        "FROM annual_financials WHERE company_symbol = ANY(%s) AND period_end_date < %s "
        "ORDER BY company_symbol, period_end_date", (sorted(set(then)), START)))
    fb = os.path.join(_HERE, "shares_fallback.json")
    yh = json.load(open(fb)) if os.path.exists(fb) else {}
    last = fund.groupby("symbol").tail(1).set_index("symbol")
    last = last.assign(shares_final=share_count(last, yh))
    asof = asof.join(last[["shares_final"]], on="symbol")
    asof["cap_sort"] = asof.shares_final * asof.px_sort * asof.px_gbp_factor

    print("\n" + "=" * 96)
    print("DOES THE SIZE EFFECT SURVIVE ON THE CORRECT MEMBERSHIP?")
    print("=" * 96)
    for label, sub in [("as-of 2025-08-05 list", asof),
                       ("today's list (published)", today)]:
        s = sub.dropna(subset=["cap_sort", "ret_1y"]) if "cap_sort" in sub else None
        if s is None or len(s) < 25:
            continue
        rho, p = stats.spearmanr(s.cap_sort, s.ret_1y)
        print(f"\n  {label:26s} n={len(s):3d}  spearman(cap, ret) = {rho:+.3f} (p={p:.3f})")
        q = pd.qcut(s.cap_sort, 5, labels=["Q1 smallest", "Q2", "Q3", "Q4", "Q5 largest"])
        for b, g in s.groupby(q, observed=True):
            print(f"      {str(b):12s} n={len(g):2d}  median {pct(g.ret_1y.median()):>7s}  "
                  f"% up {(g.ret_1y > 0).mean() * 100:5.1f}%")

    asof.to_csv(os.path.join(_HERE, "aim100_asof_rows.csv"), index=False)


if __name__ == "__main__":
    main()
