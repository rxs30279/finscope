"""Is 'small won' really just 'miners won'? Confound and robustness checks.

Every headline cut in the first pass points at the same 20-odd companies -
smallest quintile, highest volatility, no revenue, loss-making, Basic Materials.
This separates them, and puts error bars on quintile medians built from n=20.
"""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

_HERE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 220)
RNG = np.random.default_rng(20260806)

d = pd.read_csv(os.path.join(_HERE, "aim100_rows.csv"))
aim = d[d.ftse_index == "FTSE AIM 100"].copy()
aim["is_resource"] = aim.sector.isin(["Basic Materials", "Energy"])
aim["logcap"] = np.log(aim.cap_sort)
aim["q_cap"] = pd.qcut(aim.cap_sort, 5, labels=[1, 2, 3, 4, 5])
aim["q_vol"] = pd.qcut(aim.vol_prior, 5, labels=[1, 2, 3, 4, 5])


def pct(x):
    return f"{x * 100:.1f}%"


def boot_median_ci(x, n=10000):
    """Percentile bootstrap CI for a median - quintiles here hold only 20 names."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return (np.nan, np.nan)
    draws = RNG.choice(x, size=(n, len(x)), replace=True)
    meds = np.median(draws, axis=1)
    return np.percentile(meds, 2.5), np.percentile(meds, 97.5)


print("=" * 110)
print("A. HOW MUCH DO THE 'RISKY' BUCKETS OVERLAP?")
print("=" * 110)
small = aim.q_cap.astype(int) == 1
hivol = aim.q_vol.astype(int) == 5
norev = ~(aim.revenue_gbp > 0)
loss = ~aim.profitable.astype(bool)
res = aim.is_resource
print(f"  smallest cap quintile   n={small.sum():2d}   of which resource stocks: "
      f"{(small & res).sum()} ({pct((small & res).mean() / small.mean())})")
print(f"  highest vol quintile    n={hivol.sum():2d}   of which resource stocks: "
      f"{(hivol & res).sum()} ({pct((hivol & res).mean() / hivol.mean())})")
print(f"  no revenue at all       n={norev.sum():2d}   of which resource stocks: "
      f"{(norev & res).sum()} ({pct((norev & res).mean() / norev.mean())})")
print(f"  loss-making             n={loss.sum():2d}   of which resource stocks: "
      f"{(loss & res).sum()} ({pct((loss & res).mean() / loss.mean())})")
print(f"\n  smallest quintile AND highest vol quintile: {(small & hivol).sum()}")
print(f"  smallest quintile AND loss-making:          {(small & loss).sum()}")
print(f"  resource stocks overall: {res.sum()} of {len(aim)} ({pct(res.mean())})")
print(f"\n  median return, resource stocks      {pct(aim[res].ret_1y.median())} "
      f"(n={res.sum()}, {pct((aim[res].ret_1y > 0).mean())} up)")
print(f"  median return, everything else      {pct(aim[~res].ret_1y.median())} "
      f"(n={(~res).sum()}, {pct((aim[~res].ret_1y > 0).mean())} up)")

print("\n" + "=" * 110)
print("B. THE SIZE EFFECT WITH RESOURCE STOCKS REMOVED")
print("=" * 110)
for label, sub in [("all AIM 100", aim), ("excluding Basic Materials + Energy", aim[~res]),
                   ("resource stocks only", aim[res])]:
    if len(sub) < 25:
        s = sub[["cap_sort", "ret_1y"]].dropna()
        rho, p = stats.spearmanr(s.cap_sort, s.ret_1y) if len(s) > 8 else (np.nan, np.nan)
        print(f"\n  {label:38s} n={len(sub):3d}  spearman(cap, ret) = {rho:+.3f} (p={p:.3f})")
        continue
    q = pd.qcut(sub.cap_sort, 5, labels=["Q1 smallest", "Q2", "Q3", "Q4", "Q5 largest"])
    s = sub[["cap_sort", "ret_1y"]].dropna()
    rho, p = stats.spearmanr(s.cap_sort, s.ret_1y)
    print(f"\n  {label:38s} n={len(sub):3d}  spearman(cap, ret) = {rho:+.3f} (p={p:.3f})")
    for b, g in sub.groupby(q, observed=True):
        lo, hi = boot_median_ci(g.ret_1y)
        print(f"      {str(b):12s} n={len(g):2d}  median {pct(g.ret_1y.median()):>7s}  "
              f"95% CI [{pct(lo):>7s}, {pct(hi):>7s}]  % up {pct((g.ret_1y > 0).mean()):>6s}")

print("\n" + "=" * 110)
print("C. THE VOLATILITY EFFECT WITH RESOURCE STOCKS REMOVED")
print("=" * 110)
for label, sub in [("all AIM 100", aim), ("excluding Basic Materials + Energy", aim[~res])]:
    q = pd.qcut(sub.vol_prior, 5, labels=["Q1 calmest", "Q2", "Q3", "Q4", "Q5 wildest"])
    s = sub[["vol_prior", "ret_1y"]].dropna()
    rho, p = stats.spearmanr(s.vol_prior, s.ret_1y)
    print(f"\n  {label:38s} n={len(sub):3d}  spearman(vol, ret) = {rho:+.3f} (p={p:.3f})")
    for b, g in sub.groupby(q, observed=True):
        lo, hi = boot_median_ci(g.ret_1y)
        print(f"      {str(b):12s} n={len(g):2d}  median {pct(g.ret_1y.median()):>7s}  "
              f"95% CI [{pct(lo):>7s}, {pct(hi):>7s}]  % up {pct((g.ret_1y > 0).mean()):>6s}")

print("\n" + "=" * 110)
print("D. WHAT SURVIVES WHEN THE FACTORS COMPETE (OLS on rank-transformed inputs)")
print("=" * 110)
print("   Ranks, not raw values: one +513% name would otherwise drive every coefficient.")
model = aim[["ret_1y", "cap_sort", "vol_prior", "revenue_gbp", "turnover_med",
             "ret_prior", "is_resource"]].copy()
model["revenue_gbp"] = model.revenue_gbp.fillna(0).clip(lower=0)
model = model.dropna()
y = stats.rankdata(model.ret_1y) / len(model)
X = pd.DataFrame({
    "const": 1.0,
    "log cap": stats.rankdata(model.cap_sort) / len(model),
    "prior vol": stats.rankdata(model.vol_prior) / len(model),
    "revenue": stats.rankdata(model.revenue_gbp) / len(model),
    "liquidity": stats.rankdata(model.turnover_med) / len(model),
    "prior return": stats.rankdata(model.ret_prior) / len(model),
    "is resource": model.is_resource.astype(float).to_numpy(),
})
beta, *_ = np.linalg.lstsq(X.to_numpy(), y, rcond=None)
resid = y - X.to_numpy() @ beta
dof = len(y) - X.shape[1]
sigma2 = resid @ resid / dof
cov = sigma2 * np.linalg.inv(X.to_numpy().T @ X.to_numpy())
se = np.sqrt(np.diag(cov))
tstat = beta / se
pvals = 2 * (1 - stats.t.cdf(np.abs(tstat), dof))
r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
print(f"\n   n={len(y)}   R^2={r2:.3f}\n")
print(f"   {'term':14s} {'coef':>8s} {'se':>7s} {'t':>7s} {'p':>7s}   verdict")
for nm, b, s_, t_, p_ in zip(X.columns, beta, se, tstat, pvals):
    v = "SIGNIFICANT" if p_ < 0.05 else ("weak" if p_ < 0.20 else "nothing")
    print(f"   {nm:14s} {b:8.3f} {s_:7.3f} {t_:7.2f} {p_:7.3f}   {'' if nm == 'const' else v}")

print("\n" + "=" * 110)
print("E. IS THE SIZE RESULT JUST THE TWO BEST NAMES?")
print("=" * 110)
q1 = aim[aim.q_cap.astype(int) == 1]
print(f"   smallest quintile, all {len(q1)}: median {pct(q1.ret_1y.median())}, "
      f"mean {pct(q1.ret_1y.mean())}")
trimmed = q1.sort_values("ret_1y").iloc[:-2]
print(f"   drop its 2 best:          median {pct(trimmed.ret_1y.median())}, "
      f"mean {pct(trimmed.ret_1y.mean())}")
print(f"   its members: " + ", ".join(
    f"{r.symbol} {pct(r.ret_1y)}" for r in q1.sort_values("ret_1y", ascending=False).itertuples()))

print("\n" + "=" * 110)
print("F. MEMBERSHIP LOOK-AHEAD - who is in the sample")
print("=" * 110)
print("   ftse_index is TODAY's label. A company that collapsed during the year")
print("   was demoted out of the AIM 100 and now sits in the 'AIM' bucket, so it")
print("   never enters these numbers. The rest-of-AIM tier is the visible half of")
print("   that hole:")
rest = d[d.ftse_index == "AIM"]
print(f"     rest of AIM  n={len(rest)}  median {pct(rest.ret_1y.median())}  "
      f"% up {pct((rest.ret_1y > 0).mean())}  % lost 30%+ {pct((rest.ret_1y <= -0.30).mean())}")
print(f"     AIM 100      n={len(aim)}  median {pct(aim.ret_1y.median())}  "
      f"% up {pct((aim.ret_1y > 0).mean())}  % lost 30%+ {pct((aim.ret_1y <= -0.30).mean())}")
both = d[d.ftse_index.isin(["AIM", "FTSE AIM 100"])]
print(f"     both pooled  n={len(both)}  median {pct(both.ret_1y.median())}  "
      f"% up {pct((both.ret_1y > 0).mean())}  % lost 30%+ {pct((both.ret_1y <= -0.30).mean())}")
