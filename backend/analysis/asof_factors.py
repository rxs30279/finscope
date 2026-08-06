"""Full factor re-test on the AIM 100 as it stood on 2025-08-05."""
import json, os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
import numpy as np, pandas as pd
from scipy import stats
from db import query
from aim100_returns import FX_TO_GBP, share_count, START

d = pd.read_csv(os.path.join(_HERE, "aim100_asof_rows.csv"))
syms = d.symbol.tolist()

meta = pd.DataFrame(query(
    "SELECT symbol, name, sector, financial_currency FROM company_metadata "
    "WHERE symbol = ANY(%s)", (syms,)))
fund = pd.DataFrame(query(
    "SELECT company_symbol AS symbol, period_end_date, revenue, net_income, ebitda, "
    "       fcf, net_debt, total_equity, shares_outstanding, shares_diluted, "
    "       shares_basic, revenue_per_share, book_value_per_share, eps_basic "
    "FROM annual_financials WHERE company_symbol = ANY(%s) AND period_end_date < %s "
    "ORDER BY company_symbol, period_end_date", (syms, START)))
sc = pd.DataFrame(query(
    "SELECT symbol, risk_score, altman_z, piotroski_score FROM screener_scores "
    "WHERE symbol = ANY(%s)", (syms,)))

last = fund.groupby("symbol").tail(1).set_index("symbol")
yh = json.load(open(os.path.join(_HERE, "shares_fallback.json")))
last = last.assign(shares_final=share_count(last, yh))

d = d.drop(columns=[c for c in ("sector","name") if c in d.columns]).merge(meta, on="symbol", how="left").join(last.add_prefix("fy_"), on="symbol")
d = d.merge(sc, on="symbol", how="left")
fx = d.financial_currency.map(FX_TO_GBP).fillna(1.0)
d["revenue_gbp"] = d.fy_revenue * fx
d["net_income_gbp"] = d.fy_net_income * fx
d["cap_sort"] = d.fy_shares_final * d.px_sort * d.px_gbp_factor
d["net_debt_to_cap"] = d.fy_net_debt * fx / d.cap_sort
d["ps_ratio"] = d.cap_sort / d.revenue_gbp.where(d.revenue_gbp > 0)
d["is_res"] = d.sector.isin(["Basic Materials", "Energy"])

P = lambda x: f"{x*100:+.1f}%"
print("=" * 100)
print("FACTOR RE-TEST on the 2025-08-05 membership (n=%d priced)" % len(d))
print("=" * 100)
print(f"{'factor':26s} {'n':>4s} {'rho':>7s} {'p':>7s}   {'PUBLISHED (today-list)':>24s}")
pub = {"cap_sort": "-0.296 p=0.003 SIG", "revenue_gbp": "-0.027 p=0.797 null",
       "vol_prior": "+0.287 p=0.004 SIG", "ps_ratio": "-0.130 p=0.225 null",
       "net_debt_to_cap": "+0.164 p=0.106 weak", "risk_score": "+0.211 p=0.036 SIG",
       "altman_z": "+0.042 p=0.691 null", "piotroski_score": "-0.058 p=0.570 null"}
for col, nm in [("cap_sort", "market cap (lagged)"), ("revenue_gbp", "revenue"),
                ("vol_prior", "prior-year volatility"), ("ps_ratio", "price / sales"),
                ("net_debt_to_cap", "net debt / cap"), ("risk_score", "site risk score"),
                ("altman_z", "Altman Z"), ("piotroski_score", "Piotroski F")]:
    s = d[[col, "ret_1y"]].dropna()
    if len(s) < 20:
        print(f"{nm:26s} {len(s):4d}   too few"); continue
    rho, p = stats.spearmanr(s[col], s.ret_1y)
    v = "SIG" if p < .05 else ("weak" if p < .20 else "null")
    print(f"{nm:26s} {len(s):4d} {rho:+7.3f} {p:7.3f} {v:5s} {pub.get(col,''):>24s}")

print("\n" + "=" * 100)
print("VOLATILITY -> RISK (the finding that should be robust)")
print("=" * 100)
s = d[d.vol_prior.notna()].copy()
s["q"] = pd.qcut(s.vol_prior, 5, labels=[1, 2, 3, 4, 5])
for b, g in s.groupby("q", observed=True):
    print(f"  Q{b}  prior vol {P(g.vol_prior.median()):>7s}  worst fall {P(g.maxdd.median()):>7s}  "
          f"% halved {(g.maxdd<=-.5).mean()*100:5.1f}%  median ret {P(g.ret_1y.median()):>7s}")
rr, pp = stats.spearmanr(s.vol_prior, s.maxdd)
print(f"  spearman(prior vol, worst fall) = {rr:+.3f} (p={pp:.4f})")

print("\n" + "=" * 100)
print("SECTOR (as-of list)")
print("=" * 100)
sec = d.groupby("sector").agg(n=("ret_1y","size"), med=("ret_1y","median"),
                              up=("ret_1y", lambda x:(x>0).mean())).query("n>=4").sort_values("med", ascending=False)
for i, r in sec.iterrows():
    print(f"  {i:24s} n={int(r.n):2d}  median {P(r.med):>7s}  % up {r.up*100:5.1f}%")
print(f"\n  resource stocks   n={int(d.is_res.sum())}  median {P(d[d.is_res].ret_1y.median())}")
print(f"  everything else   n={int((~d.is_res).sum())}  median {P(d[~d.is_res].ret_1y.median())}")
d.to_csv(os.path.join(_HERE, "aim100_asof_full.csv"), index=False)
