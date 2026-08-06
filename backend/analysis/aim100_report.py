"""Cuts of the AIM 100 last-12-months returns. Reads aim100_rows.csv."""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

_HERE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 200)

d = pd.read_csv(os.path.join(_HERE, "aim100_rows.csv"))
aim = d[d.ftse_index == "FTSE AIM 100"].copy()
N = len(aim)


def pct(x):
    return f"{x * 100:.1f}%"


def money(x):
    if pd.isna(x):
        return "n/a"
    for cut, suf in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(x) >= cut:
            return f"£{x / cut:.2f}{suf}"
    return f"£{x:.0f}"


def band(frame, col, label, q=5, labels=None):
    """Quantile buckets of `col`, each row a summary of what happened next."""
    sub = frame[frame[col].notna()].copy()
    try:
        sub["bucket"] = pd.qcut(sub[col], q, labels=labels, duplicates="drop")
    except ValueError:
        return None
    rows = []
    for b, g in sub.groupby("bucket", observed=True):
        rows.append({
            label: str(b),
            "n": len(g),
            "range": f"{money(g[col].min())} - {money(g[col].max())}"
            if g[col].abs().max() > 1000 else
            f"{g[col].min():.2f} - {g[col].max():.2f}",
            "med ret": pct(g.ret_1y.median()),
            "mean ret": pct(g.ret_1y.mean()),
            "% up": pct((g.ret_1y > 0).mean()),
            "% -30%+": pct((g.ret_1y <= -0.30).mean()),
            "% +50%+": pct((g.ret_1y >= 0.50).mean()),
            "med vol": pct(g.vol_prior.median()),
            "med worst fall": pct(g.maxdd.median()),
        })
    return pd.DataFrame(rows)


def show(title, table):
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
    if table is None or not len(table):
        print("  (insufficient data)")
        return
    print(table.to_string(index=False))


def spearman(frame, col, target="ret_1y"):
    s = frame[[col, target]].dropna()
    if len(s) < 20:
        return None
    r, p = stats.spearmanr(s[col], s[target])
    return len(s), r, p


# ---------------------------------------------------------------- baseline --
print(f"{'=' * 100}\nAIM 100 - 12 months to 2026-08-05 (n={N} of 100 with usable history)\n{'=' * 100}")
r = aim.ret_1y
print(f"  median return      {pct(r.median())}")
print(f"  mean return        {pct(r.mean())}   <- pulled up by the tail")
print(f"  equal-weight basket{pct(r.mean())} (same thing: EW basket == mean member)")
print(f"  % that made money  {pct((r > 0).mean())}")
print(f"  % that beat +10%   {pct((r > 0.10).mean())}")
print(f"  % that lost 30%+   {pct((r <= -0.30).mean())}")
print(f"  % that lost 50%+   {pct((r <= -0.50).mean())}")
print(f"  worst / best       {pct(r.min())} / {pct(r.max())}")
print(f"  deciles            " + "  ".join(pct(r.quantile(q)) for q in np.arange(.1, 1, .1)))
print(f"\n  median WORST FALL inside the year: {pct(aim.maxdd.median())}")
print(f"  % whose worst fall was 30%+ at some point: {pct((aim.maxdd <= -0.30).mean())}")
print(f"  % whose worst fall was 50%+ at some point: {pct((aim.maxdd <= -0.50).mean())}")

# how concentrated is the index return?
srt = r.sort_values(ascending=False)
tot = r.sum()
for k in (1, 3, 5, 10, 20):
    print(f"  top {k:2d} names contributed {srt.head(k).sum() / tot * 100:5.1f}% "
          f"of the equal-weight total return")
print(f"  return of the basket EXCLUDING the top 5: "
      f"{pct(srt.iloc[5:].mean())}  (vs {pct(r.mean())} with them)")

# ------------------------------------------------------------ tier context --
rows = []
for tier in ["FTSE 100", "FTSE 250", "FTSE SmallCap", "FTSE AIM 100", "AIM"]:
    g = d[d.ftse_index == tier]
    rows.append({
        "tier": tier, "n": len(g),
        "med ret": pct(g.ret_1y.median()),
        "mean ret": pct(g.ret_1y.mean()),
        "% up": pct((g.ret_1y > 0).mean()),
        "% lost 30%+": pct((g.ret_1y <= -0.30).mean()),
        "med vol": pct(g.vol_prior.median()),
        "med worst fall": pct(g.maxdd.median()),
        "% fell 50% intra-yr": pct((g.maxdd <= -0.50).mean()),
        "10th pct": pct(g.ret_1y.quantile(.1)),
        "90th pct": pct(g.ret_1y.quantile(.9)),
    })
show("CONTEXT - the same year across every tier", pd.DataFrame(rows))

# ------------------------------------------------------------------- 1 CAP --
show("1. BY MARKET CAP at the lagged sort date (2025-07-04) - the honest cut",
     band(aim, "cap_sort", "cap quintile"))
show("1b. ROBUSTNESS - by market cap at fiscal year end (a 7-month lag)",
     band(aim, "cap_fy", "cap quintile"))
show("1c. THE TRAP - bucketing by TODAY's market cap (look-ahead, do not use)",
     band(aim, "cap_today_biased", "cap quintile"))

# --------------------------------------------------------------- 2 REVENUE --
rev = aim.copy()
rev["rev_bucket"] = np.where(rev.revenue_gbp > 0, "has revenue", "no revenue")
print(f"\n{'=' * 100}\n2. BY REVENUE\n{'=' * 100}")
for b, g in rev.groupby("rev_bucket"):
    print(f"  {b:12s} n={len(g):3d}  med ret {pct(g.ret_1y.median()):>7s}  "
          f"% up {pct((g.ret_1y > 0).mean()):>6s}  med vol {pct(g.vol_prior.median()):>6s}  "
          f"med worst fall {pct(g.maxdd.median()):>7s}")
show("2b. Revenue quintiles (companies with actual revenue only)",
     band(aim[aim.revenue_gbp > 0], "revenue_gbp", "revenue quintile"))
show("2c. Revenue GROWTH quintiles", band(aim, "rev_growth_pct", "rev growth %"))

# -------------------------------------------------------------- 3 VARIANCE --
show("3. BY PRIOR-YEAR VOLATILITY - the only vol you could know in advance",
     band(aim, "vol_prior", "vol quintile"))
show("3b. By volatility DURING the year (descriptive - not investable)",
     band(aim, "vol_window", "vol quintile"))

# ----------------------------------------------------------------- 4 OTHER --
print(f"\n{'=' * 100}\n4. PROFITABILITY (last accounts before the window)\n{'=' * 100}")
for col, name in [("profitable", "profitable (net income > 0)"),
                  ("fcf_positive", "free cash flow positive")]:
    for val in (True, False):
        g = aim[aim[col] == val]
        if not len(g):
            continue
        print(f"  {name:28s} {str(val):5s} n={len(g):3d}  med ret {pct(g.ret_1y.median()):>7s}  "
              f"% up {pct((g.ret_1y > 0).mean()):>6s}  % lost 30%+ {pct((g.ret_1y <= -0.30).mean()):>6s}  "
              f"med vol {pct(g.vol_prior.median()):>6s}")

show("4b. DILUTION - share count growth in the last accounts",
     band(aim, "dilution_pct", "dilution %"))
show("4c. LIQUIDITY - median daily turnover", band(aim, "turnover_med", "turnover"))
show("4d. LEVERAGE - net debt / market cap", band(aim, "net_debt_to_cap", "net debt/cap"))
show("4e. VALUATION - price / sales at the start", band(aim, "ps_ratio", "P/S"))
show("4f. MOMENTUM - the PREVIOUS year's return", band(aim, "ret_prior", "prior year ret"))
show("4g. The site's own risk score", band(aim, "risk_score", "risk score", q=4))

print(f"\n{'=' * 100}\n4h. BY SECTOR (groups of 4+)\n{'=' * 100}")
sec = (aim.groupby("sector")
       .agg(n=("ret_1y", "size"), med_ret=("ret_1y", "median"),
            pct_up=("ret_1y", lambda x: (x > 0).mean()),
            med_vol=("vol_prior", "median"), med_dd=("maxdd", "median"))
       .query("n >= 4").sort_values("med_ret", ascending=False))
sec["med_ret"] = sec.med_ret.map(pct)
sec["pct_up"] = sec.pct_up.map(pct)
sec["med_vol"] = sec.med_vol.map(pct)
sec["med_dd"] = sec.med_dd.map(pct)
print(sec.to_string())

# ------------------------------------------------------------ correlations --
print(f"\n{'=' * 100}\nRANK CORRELATION WITH THE YEAR'S RETURN (Spearman)\n{'=' * 100}")
print(f"{'factor':28s} {'n':>4s} {'rho':>7s} {'p':>8s}   verdict")
for col, name in [("cap_sort", "market cap (lagged)"),
                  ("cap_today_biased", "market cap (TODAY - biased)"),
                  ("revenue_gbp", "revenue"),
                  ("rev_growth_pct", "revenue growth"),
                  ("vol_prior", "prior-year volatility"),
                  ("vol_window", "volatility during year"),
                  ("dilution_pct", "share dilution"),
                  ("turnover_med", "liquidity"),
                  ("net_debt_to_cap", "net debt / cap"),
                  ("ps_ratio", "price / sales"),
                  ("ret_prior", "previous year's return"),
                  ("risk_score", "site risk score"),
                  ("altman_z", "Altman Z"),
                  ("piotroski_score", "Piotroski F")]:
    res = spearman(aim, col)
    if not res:
        print(f"{name:28s}    - too few observations")
        continue
    n, rho, p = res
    verdict = "SIGNIFICANT" if p < 0.05 else ("weak" if p < 0.20 else "nothing")
    print(f"{name:28s} {n:4d} {rho:7.3f} {p:8.3f}   {verdict}")

# ----------------------------------------------------------------- extremes --
print(f"\n{'=' * 100}\nTHE TAILS - best and worst 8\n{'=' * 100}")
cols = ["symbol", "name", "sector", "ret_1y", "maxdd", "vol_prior", "cap_sort",
        "revenue_gbp", "dilution_pct"]
for lab, sl in [("BEST", aim.nlargest(8, "ret_1y")), ("WORST", aim.nsmallest(8, "ret_1y"))]:
    print(f"\n{lab}")
    t = sl[cols].copy()
    t["ret_1y"] = t.ret_1y.map(pct)
    t["maxdd"] = t.maxdd.map(pct)
    t["vol_prior"] = t.vol_prior.map(pct)
    t["cap_sort"] = t.cap_sort.map(money)
    t["revenue_gbp"] = t.revenue_gbp.map(money)
    t["dilution_pct"] = t.dilution_pct.map(lambda x: f"{x:.1f}%" if pd.notna(x) else "n/a")
    print(t.to_string(index=False))
