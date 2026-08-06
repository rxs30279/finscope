"""AIM 100: what explained the last year's returns?

Read-only exploratory analysis for the AIM risk article. One row per current
FTSE AIM 100 constituent (the other index tiers come along for context):

  * ret_1y      - total return over the trailing 12 months (prices are
                  auto_adjust=True, so dividends and splits are included)
  * maxdd       - worst peak-to-trough fall INSIDE the window
  * vol_prior   - annualised daily vol over the 12 months BEFORE the window.
                  This is the only volatility a reader could have known in
                  advance, so it is the one that can be used predictively.
  * vol_window  - annualised daily vol during the window (descriptive only)
  * cap_sort    - market cap at a LAGGED sort date one month before the window
                  opens: pre-window share count x price on the sort date. The
                  lag is deliberate. Sorting on the price at the window start
                  puts that same price in the return denominator, and that
                  look-ahead is what invalidated an earlier cut of this work.
  * revenue_gbp - last FY ending before the window, converted to GBP
  * plus dilution, profitability, leverage, liquidity, sector, risk score

Three data problems were found by inspection and all three are material:

  1. Unadjusted splits. price_history is written once by a backfill and then
     appended to daily; nothing re-adjusts the stored history, so a split after
     the backfill leaves a permanent step. F&C Investment Trust (4:1), Capital
     Gearing (10:1) and AEP (10:1) each print a 90%+ one-day "fall" that is
     pure artifact. Fixed by re-downloading with auto_adjust=True.
  2. A 100x pence/pounds glitch on illiquid days (SAVE.L alternates between
     7.2 and 0.072; CLDN.L steps 100x in July 2025 and never steps back).
     Fixed by repair_units() below.
  3. Missing share counts - annual_financials.shares_outstanding is NULL for
     21 of 100. Filled from diluted/basic, then per-share ratios, then a
     one-off Yahoo lookup. Deliberately NOT from market_cap/price, which would
     derive size from the return.

Usage:
    python aim100_returns.py --download    # refresh yf_close.pkl / yf_vol.pkl
    python aim100_returns.py [--csv out.csv]
"""

import argparse
import json
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND)

import numpy as np
import pandas as pd

from db import query

# ---- window ----------------------------------------------------------------
END = date(2026, 8, 5)          # latest bar available
START = date(2025, 8, 5)        # 12 months back
PRIOR_START = date(2024, 8, 5)  # 12 months before that (for vol_prior)
SORT_DATE = date(2025, 7, 4)    # lagged size sort date (~1m before the window)

TIERS = ["FTSE 100", "FTSE 250", "FTSE SmallCap", "FTSE AIM 100", "AIM"]

# Approximate spot rates, used only to make revenue buckets comparable across
# reporting currencies. A quintile boundary does not move on a 3% FX drift.
FX_TO_GBP = {"GBP": 1.0, "USD": 0.74, "EUR": 0.86, "AUD": 0.49, "CAD": 0.54,
             "GBp": 0.01, "SEK": 0.078, "NOK": 0.072, "CHF": 0.92, "ILS": 0.22}

# Quote currency -> GBP for PRICES (distinct from FX_TO_GBP, which converts
# reported financials). Pence is the LSE default; a few lines quote in their
# home currency, and GRP.L in euros would otherwise read 100x too small.
PX_TO_GBP = {"GBp": 0.01, "GBP": 1.0, "EUR": 0.86, "USD": 0.74, "ILS": 0.0022}

TRADING_DAYS = 252

# Spike filter: a bar is bad if it deviates by more than this factor from BOTH
# the 5 bars before and the 5 bars after. A genuine sustained move fails the
# second test, so only isolated one-day prints are removed.
_TICK_FACTOR = 2.5

# Cornish Metals ran a 1-for-10 consolidation on 2025-12-18 (7.85p -> 79.5p on
# a tenth of median volume) that is missing from Yahoo's split table, so nothing
# upstream rescales the earlier bars. Left alone it shows as a +913% one-day
# gain. Any other consolidation found later belongs here, with its evidence.
MANUAL_SPLITS = {"TIN.L": [(date(2025, 12, 18), 10.0)]}

_CLOSE_PKL = os.path.join(_HERE, "yf_close.pkl")
_VOL_PKL = os.path.join(_HERE, "yf_vol.pkl")


def download(symbols):
    """Refresh the local price cache from Yahoo (~45s for 733 symbols)."""
    import yfinance as yf
    df = yf.download(symbols, start="2024-07-15", end="2026-08-06",
                     auto_adjust=True, progress=False, threads=True,
                     group_by="column")
    df["Close"].to_pickle(_CLOSE_PKL)
    df["Volume"].to_pickle(_VOL_PKL)
    print(f"cached {df['Close'].notna().any().sum()} symbols")


def repair_units(g):
    """Undo the 100x pence/pounds glitch. Returns (frame, n_repaired).

    A neighbour-median filter is the wrong tool here: on SAVE.L the glitch runs
    for weeks at a time, so the local median is itself glitched. But the glitch
    is always EXACTLY two decades, which makes it detectable from the bar-to-bar
    ratio alone. Walk the series, track the cumulative unit state, divide it out.

    The state starts at zero on the first bar, so if that bar is itself glitched
    the whole series lands a decade pair off. Re-anchoring is the fiddly part.
    Anchoring on the median fails on CLDN.L, which steps 100x in July 2025 and
    never steps back, leaving the two halves equal and the median stranded
    between them. Anchoring on the most recent bars fails on SAVE.L, whose last
    twenty bars are themselves glitched. What always holds is that the good bars
    outnumber the bad ones, so pick the shift that leaves the most bars equal to
    what the feed already said.
    """
    c = g["close"].astype(float)
    if len(c) < 5:
        return g, 0
    step = np.log10(c / c.shift(1))
    flip = pd.Series(0, index=c.index)
    flip[(step - 2).abs() < 0.05] = 1
    flip[(step + 2).abs() < 0.05] = -1
    if not flip.any():
        return g, 0
    base = c / (100.0 ** flip.cumsum())
    k = max((-2, -1, 0, 1, 2),
            key=lambda j: int((base / (100.0 ** j) / c - 1).abs().lt(0.01).sum()))
    fixed = base / (100.0 ** k)
    return g.assign(close=fixed), int((fixed / c - 1).abs().gt(0.01).sum())


def clean_ticks(g):
    """Drop isolated price spikes. Returns (cleaned_frame, n_dropped)."""
    c = g["close"].astype(float)
    before = c.shift(1).rolling(5, min_periods=3).median()
    after = c.shift(-1)[::-1].rolling(5, min_periods=3).median()[::-1]
    bad = (
        ((c / before > _TICK_FACTOR) | (c / before < 1 / _TICK_FACTOR))
        & ((c / after > _TICK_FACTOR) | (c / after < 1 / _TICK_FACTOR))
        & before.notna() & after.notna()
    )
    return g[~bad], int(bad.sum())


def load_prices(symbols):
    """Prices from the fresh Yahoo pull, not price_history (see module docstring).

    Verified against the DB on the latest bar: 726/726 symbols agree to within
    0.3%, so this swaps the source without moving the price level.
    """
    if not os.path.exists(_CLOSE_PKL):
        raise SystemExit("no price cache - run with --download first")
    close = pd.read_pickle(_CLOSE_PKL)
    vol = pd.read_pickle(_VOL_PKL)
    cols = [c for c in close.columns if c in set(symbols)]

    def melt(frame, name):
        out = frame[cols].stack().rename(name).reset_index()
        out.columns = ["date", "symbol", name]
        return out

    df = melt(close, "close").merge(melt(vol, "volume"), on=["date", "symbol"],
                                    how="left")
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    for sym, events in MANUAL_SPLITS.items():
        for when, factor in events:
            m = (df["symbol"] == sym) & (df["date"] < pd.Timestamp(when))
            df.loc[m, "close"] = df.loc[m, "close"] * factor
    return df[df["close"] > 0].sort_values(["symbol", "date"])


def px_on(g, target):
    """Close on/just before `target`, or None if the nearest bar is >10d stale."""
    sub = g[g["date"] <= pd.Timestamp(target)]
    if sub.empty:
        return None
    row = sub.iloc[-1]
    return None if (pd.Timestamp(target) - row["date"]).days > 10 else float(row["close"])


def ann_vol(closes, min_bars=60):
    r = np.diff(np.log(closes))
    r = r[np.isfinite(r)]
    if len(r) < min_bars:
        return None
    return float(np.std(r, ddof=1) * np.sqrt(TRADING_DAYS))


def max_drawdown(closes):
    peak = np.maximum.accumulate(closes)
    return float((closes / peak - 1.0).min())


def share_count(frame, yahoo_shares=None):
    """Best available share count, cheapest reliable source first."""
    sh = frame["shares_outstanding"]
    sh = sh.fillna(frame["shares_diluted"]).fillna(frame["shares_basic"])
    sh = sh.fillna(frame["revenue"] / frame["revenue_per_share"].replace(0, np.nan))
    sh = sh.fillna(frame["total_equity"]
                   / frame["book_value_per_share"].replace(0, np.nan))
    sh = sh.fillna(frame["net_income"] / frame["eps_basic"].replace(0, np.nan))
    if yahoo_shares:
        sh = sh.fillna(pd.Series(yahoo_shares))
    return sh


def build():
    meta = pd.DataFrame(query(
        "SELECT symbol, name, sector, industry, ftse_index, financial_currency, "
        "       currency FROM company_metadata "
        "WHERE ftse_index = ANY(%s) AND is_active", (TIERS,)))
    symbols = meta["symbol"].tolist()
    quote_ccy = dict(zip(meta["symbol"], meta["currency"]))

    px = load_prices(symbols)

    fund = pd.DataFrame(query(
        "SELECT company_symbol AS symbol, fiscal_year, period_end_date, revenue, "
        "       net_income, ebitda, fcf, net_debt, total_equity, cash_and_equiv, "
        "       shares_outstanding, shares_diluted, shares_basic, revenue_per_share, "
        "       book_value_per_share, eps_basic, period_end_price, operating_margin, "
        "       current_ratio "
        "FROM annual_financials WHERE company_symbol = ANY(%s) AND period_end_date < %s "
        "ORDER BY company_symbol, period_end_date", (symbols, START)))
    fund["period_end_date"] = pd.to_datetime(fund["period_end_date"])

    scores = pd.DataFrame(query(
        "SELECT symbol, risk_score, altman_z, momentum_score, piotroski_score, "
        "       risk_model FROM screener_scores WHERE symbol = ANY(%s)", (symbols,)))

    yahoo_shares = {}
    if os.path.exists(os.path.join(_HERE, "shares_fallback.json")):
        yahoo_shares = json.load(open(os.path.join(_HERE, "shares_fallback.json")))

    recs, n_fix, n_drop, dirty = [], 0, 0, []
    for sym, g in px.groupby("symbol"):
        g = g.reset_index(drop=True)
        g, nf = repair_units(g)
        g, nd = clean_ticks(g)
        n_fix += nf
        n_drop += nd
        if nf or nd:
            dirty.append((sym, nf, nd))

        p0, p1, psort = px_on(g, START), px_on(g, END), px_on(g, SORT_DATE)
        if not p0 or not p1 or p0 <= 0:
            continue
        win = g[(g["date"] >= pd.Timestamp(START)) & (g["date"] <= pd.Timestamp(END))]
        pri = g[(g["date"] >= pd.Timestamp(PRIOR_START)) & (g["date"] < pd.Timestamp(START))]
        if len(win) < 200:
            continue

        wc = win["close"].to_numpy(dtype=float)
        pc = pri["close"].to_numpy(dtype=float)
        f = PX_TO_GBP.get(quote_ccy.get(sym, "GBp"), 0.01)
        turnover = win["close"] * win["volume"] * f
        recs.append({
            "symbol": sym,
            "px_start": p0, "px_end": p1, "px_sort": psort, "px_gbp_factor": f,
            "ret_1y": p1 / p0 - 1.0,
            "ret_prior": (pc[-1] / pc[0] - 1.0) if len(pc) > 60 else None,
            "maxdd": max_drawdown(wc),
            "vol_window": ann_vol(wc),
            "vol_prior": ann_vol(pc),
            "n_bars": len(win),
            "units_repaired": nf, "ticks_dropped": nd,
            "turnover_med": float(turnover.median()),
            "thin_days_pct": float((turnover < 10_000).mean() * 100),
            "zero_vol_days_pct": float((win["volume"] <= 0).mean() * 100),
        })

    print(f"unit glitches repaired {n_fix}, spikes dropped {n_drop}, "
          f"symbols touched {len(dirty)}")

    df = pd.DataFrame(recs).merge(meta, on="symbol", how="left")

    # last FY ending before the window, and the one before that
    last = fund.groupby("symbol").tail(1).set_index("symbol")
    last = last.assign(shares_final=share_count(last, yahoo_shares))
    # dropna(how="all") on purpose - a plain dropna() drops any prior-year row
    # carrying a single NULL column, which silently cut dilution coverage to 68.
    prev = (fund.groupby("symbol")
            .apply(lambda x: x.iloc[-2] if len(x) >= 2 else None,
                   include_groups=False)
            .dropna(how="all"))
    prev = prev.assign(shares_final=share_count(prev))

    df = df.join(last.add_prefix("fy_"), on="symbol")
    df = df.join(prev[["shares_final", "revenue", "net_income"]].add_prefix("fyprev_"),
                 on="symbol")
    df = df.merge(scores, on="symbol", how="left")

    fx = df["financial_currency"].map(FX_TO_GBP).fillna(1.0)
    for src, dst in [("fy_revenue", "revenue_gbp"), ("fy_ebitda", "ebitda_gbp"),
                     ("fy_net_income", "net_income_gbp"), ("fy_fcf", "fcf_gbp"),
                     ("fy_net_debt", "net_debt_gbp"),
                     ("fy_cash_and_equiv", "cash_gbp"),
                     ("fyprev_revenue", "revenue_prev_gbp")]:
        df[dst] = df[src] * fx

    df["cap_sort"] = df["fy_shares_final"] * df["px_sort"] * df["px_gbp_factor"]
    df["cap_fy"] = df["fy_shares_final"] * df["fy_period_end_price"]
    # today's cap, computed ONLY to demonstrate the look-ahead trap
    df["cap_today_biased"] = df["fy_shares_final"] * df["px_end"] * df["px_gbp_factor"]

    df["dilution_pct"] = (df["fy_shares_final"] / df["fyprev_shares_final"] - 1) * 100
    df["rev_growth_pct"] = (df["revenue_gbp"] / df["revenue_prev_gbp"] - 1) * 100
    df["net_debt_to_cap"] = df["net_debt_gbp"] / df["cap_sort"]
    df["cash_to_cap"] = df["cash_gbp"] / df["cap_sort"]
    df["profitable"] = df["net_income_gbp"] > 0
    df["fcf_positive"] = df["fcf_gbp"] > 0
    df["has_revenue"] = df["revenue_gbp"] > 0
    df["ps_ratio"] = df["cap_sort"] / df["revenue_gbp"].where(df["revenue_gbp"] > 0)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()

    if args.download:
        rows = query("SELECT symbol FROM company_metadata "
                     "WHERE ftse_index = ANY(%s) AND is_active", (TIERS,))
        download([r["symbol"] for r in rows])

    df = build()
    out = args.csv or os.path.join(_HERE, "aim100_rows.csv")
    df.to_csv(out, index=False)

    aim = df[df["ftse_index"] == "FTSE AIM 100"]
    print(f"wrote {out} ({len(df)} rows); AIM 100 usable {len(aim)}/100")
    cols = ["ret_1y", "maxdd", "vol_prior", "cap_sort", "revenue_gbp",
            "dilution_pct", "turnover_med", "net_debt_to_cap"]
    print(aim[cols].describe(percentiles=[.1, .5, .9]).T.to_string(
        float_format=lambda v: f"{v:,.3f}"))


if __name__ == "__main__":
    main()
