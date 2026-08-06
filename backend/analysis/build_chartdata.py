"""Regenerate the article's chart payload from the analysis CSVs in one place.

Hand-patching individual keys drifted the figures out of step with the tables
more than once, so everything the article plots is rebuilt here from the same
source frames the statistics come from.
"""
import json
import os

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))

R = lambda v, k=4: None if pd.isna(v) else round(float(v), k)


def quints(sub, col):
    sub = sub[sub[col].notna()].copy()
    sub["q"] = pd.qcut(sub[col], 5, labels=[1, 2, 3, 4, 5])
    out = []
    for b, g in sub.groupby("q", observed=True):
        out.append({"q": int(b), "n": int(len(g)),
                    "med": R(g.ret_1y.median()), "up": R((g.ret_1y > 0).mean()),
                    "dd": R(g.maxdd.median()), "halved": R((g.maxdd <= -0.5).mean()),
                    "vol": R(g[col].median())})
    return out


def summary(r):
    return {"n": int(len(r)), "med": R(r.median()), "mean": R(r.mean()),
            "up": R((r > 0).mean()), "lost30": R((r <= -0.30).mean())}


def main():
    d = pd.read_csv(os.path.join(_HERE, "aim100_asof_full.csv"))
    asof = d[d.in_then]

    out = {}

    srt = asof.sort_values("ret_1y", ascending=False)
    out["returns"] = [{"s": r.symbol, "n": str(r["name"]), "r": R(r.ret_1y),
                       "left": not bool(r.in_now), "res": bool(r.is_res)}
                      for _, r in srt.iterrows()]

    out["head"] = {"n": int(len(asof)), "med": R(asof.ret_1y.median()),
                   "mean": R(asof.ret_1y.mean()), "up": R((asof.ret_1y > 0).mean()),
                   "dd": R(asof.maxdd.median()), "dd30": R((asof.maxdd <= -0.30).mean()),
                   "dd50": R((asof.maxdd <= -0.50).mean()),
                   "lost30": R((asof.ret_1y <= -0.30).mean()),
                   "p10": R(asof.ret_1y.quantile(0.10)),
                   "p90": R(asof.ret_1y.quantile(0.90))}

    out["churn"] = {"held": summary(asof[asof.in_now].ret_1y),
                    "left": summary(asof[~asof.in_now].ret_1y),
                    "joined": summary(d[d.in_now & ~d.in_then].ret_1y)}

    out["cap_asof"] = quints(asof, "cap_sort")
    out["vol_asof"] = quints(asof, "vol_prior")
    out["vol_asof_exres"] = quints(asof[~asof.is_res], "vol_prior")

    sec = (asof.groupby("sector")
           .agg(n=("ret_1y", "size"), med=("ret_1y", "median"),
                up=("ret_1y", lambda x: (x > 0).mean()))
           .query("n >= 4").sort_values("med", ascending=False))
    out["sectors"] = [{"s": i, "n": int(r.n), "med": R(r.med), "up": R(r.up)}
                      for i, r in sec.iterrows()]

    print("returns   n =", len(out["returns"]))
    print("head        ", json.dumps(out["head"]))
    print("churn       ", json.dumps(out["churn"]))
    print("vol_asof  n =", [q["n"] for q in out["vol_asof"]],
          "dd:", [q["dd"] for q in out["vol_asof"]])
    print("vol_exres n =", [q["n"] for q in out["vol_asof_exres"]],
          "dd:", [q["dd"] for q in out["vol_asof_exres"]])
    print("cap_asof med:", [q["med"] for q in out["cap_asof"]])
    print("sectors     ", [(s["s"][:14], s["med"]) for s in out["sectors"]])

    p = os.path.join(_HERE, "chartdata_asof.json")
    json.dump(out, open(p, "w"), separators=(",", ":"))
    print("\nwrote", p)


if __name__ == "__main__":
    main()
