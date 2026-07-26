"""Before/after impact of normalising quality_score over its available legs.

Read-only. Nothing is written to the DB and main.py is untouched — this imports
the production scrub/pegy/quality functions so "before" is exactly what
/api/screener serves today.

The problem: _scrub_screener_metrics blanks metrics that are junk for a business
model (bank FCF, trust revenue) BEFORE _quality_score reads the row, but
_quality_score just sums its 10 one-point legs, so a blanked input silently
scores 0 rather than being excluded. _value_score already handles this correctly
(averages the surviving lenses, None if fewer than two), so the two scores treat
absent data in opposite ways.

Effect: quality is capped below 10 for any row missing an input, and hard-capped
by business model — bank/insurer 4/10, trust 2/10, other financial 8/10.

The proposed fix, modelled on _value_score:
  * score = (earned + k * prior) / (available + k) * 10 over the legs whose
    inputs are present, where prior is the universe base rate of those legs
  * the net-margin-vs-median leg is un-nested from `if fcfm is not None`
    (main.py:512) — blanking fcf_margin currently also kills a point that has
    nothing to do with cash flow
  * None when fewer than --min-legs legs are available

k is the shrinkage strength in "pseudo-legs". k=0 is plain earned/available,
which is correct on average but hands a 10 to any row that goes 5-from-5 —
five tests is not the evidence ten are. k>0 pulls thin rows toward typical
while leaving full-coverage rows alone (the script checks that invariant).

Usage:
    python backend/analysis/quality_score_normalisation.py
    python backend/analysis/quality_score_normalisation.py --k 0 2 3 5
    python backend/analysis/quality_score_normalisation.py --min-legs 4 --csv out.csv
"""

import argparse
import os
import sys
from collections import defaultdict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

from db import query
from sectors import to_icb
from main import (
    _attach_pegy,
    _classify_risk_model,
    _quality_score,
    _scrub_screener_metrics,
)

# Legs available at all is a coverage question, not a quality one: too few and
# the ratio is noise whatever the shrinkage. 3 is the level that drops trusts
# (only ever ROE + ROE-vs-median = 2 legs) while keeping banks and insurers,
# which reliably carry 5.
DEFAULT_MIN_LEGS = 3

# The production screener SQL (main.py:1721), unfiltered — same columns, so the
# scrub and both score functions see exactly the rows the endpoint sees.
SQL = """
    SELECT m.symbol, m.name, m.sector, m.industry,
           t.market_cap, t.revenue, t.st_debt, t.lt_debt,
           CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END as price_to_earnings,
           t.price_to_book, t.price_to_sales, t.roe, t.roa, t.roic, t.roce,
           t.gross_margin, t.operating_margin, t.net_income_margin,
           t.revenue_growth, t.eps_diluted_growth, t.fcf_growth,
           t.debt_to_equity, t.current_ratio, t.fcf, t.ebitda,
           t.revenue_cagr_10, t.eps_cagr_10, t.eps_diluted,
           t.fcf_margin, t.dividend_yield, t.period_end_price,
           t.gross_margin_median, t.operating_margin_median,
           t.net_margin_median, t.roe_median, t.roic_median,
           a.eps_growth_next_yr, a.eps_est_current_yr,
           s.risk_model
    FROM ttm_financials t
    JOIN company_metadata m ON m.symbol = t.company_symbol
    LEFT JOIN (
        SELECT DISTINCT ON (symbol)
            symbol, eps_growth_next_yr, eps_est_current_yr
        FROM analyst_snapshots
        ORDER BY symbol, snapshot_date DESC
    ) a ON a.symbol = m.symbol
    LEFT JOIN screener_scores s ON s.symbol = m.symbol
    ORDER BY t.market_cap DESC NULLS LAST
"""


def leg_detail(r):
    """The same 10 one-point tests as _quality_score, as (name, available, won).

    A leg is available when the inputs it reads survived the scrub. Mirrors
    main.py:474-515 exactly except the final leg, which is no longer nested
    inside the fcf_margin branch.
    """
    roic, roic_med = r.get("roic"), r.get("roic_median")
    roe, roe_med = r.get("roe"), r.get("roe_median")
    gm, gm_med = r.get("gross_margin"), r.get("gross_margin_median")
    om, om_med = r.get("operating_margin"), r.get("operating_margin_median")
    fcfm = r.get("fcf_margin")
    nm, nm_med = r.get("net_income_margin"), r.get("net_margin_median")

    legs = [
        ("roic_abs", roic is not None, roic is not None and roic > 0.10),
        ("roic_med", roic is not None and roic_med is not None,
         roic is not None and roic_med is not None and roic >= roic_med),
        ("roe_abs", roe is not None, roe is not None and roe > 0.15),
        ("roe_med", roe is not None and roe_med is not None,
         roe is not None and roe_med is not None and roe >= roe_med),
        ("gm_abs", gm is not None, gm is not None and gm > 0.30),
        ("gm_med", gm is not None and gm_med is not None,
         gm is not None and gm_med is not None and gm >= gm_med),
        ("om_abs", om is not None, om is not None and om > 0.10),
        ("om_med", om is not None and om_med is not None,
         om is not None and om_med is not None and om >= om_med),
        ("fcfm_abs", fcfm is not None, fcfm is not None and fcfm > 0.05),
        ("nm_med", nm is not None and nm_med is not None,
         nm is not None and nm_med is not None and nm >= nm_med),
    ]
    return legs


def quality_legs(r):
    """(earned, available) counts over the 10 legs."""
    legs = leg_detail(r)
    available = sum(1 for _, avail, _ in legs if avail)
    earned = sum(1 for _, avail, won in legs if avail and won)
    return earned, available


def leg_base_rates(rows):
    """Universe pass rate per leg, over the rows where that leg is available.

    This is the shrinkage target: what a leg is worth on average across the
    whole universe, so a row with thin coverage is pulled toward typical rather
    than being handed a 10 for going 5-from-5.
    """
    won = defaultdict(int)
    avail = defaultdict(int)
    for r in rows:
        for name, a, w in leg_detail(r):
            if a:
                avail[name] += 1
                if w:
                    won[name] += 1
    return {name: won[name] / avail[name] for name in avail if avail[name]}


def quality_score_shrunk(r, base_rates, k, min_legs=DEFAULT_MIN_LEGS):
    """Coverage-weighted quality on 0-10.

        score = (earned + k * prior) / (available + k) * 10

    `prior` is the mean base rate of the legs this row actually has, so the
    pull is toward how a typical company scores on the same tests — not toward
    a blanket 0.5 that would punish rows whose surviving legs are easy ones.

    k = 0 is plain normalisation (earned / available). k is in units of
    "pseudo-legs": at k = 3 a row with 5 real legs is 5/8 evidence, 3/8 prior,
    while a 10-leg row is barely moved. Returns None below min_legs.
    """
    legs = leg_detail(r)
    available = [name for name, a, _ in legs if a]
    if len(available) < min_legs:
        return None
    earned = sum(1 for name, a, w in legs if a and w)
    if k == 0:
        return round(earned / len(available) * 10)
    prior = _mean([base_rates.get(n, 0.5) for n in available])
    return round((earned + k * prior) / (len(available) + k) * 10)


def quality_score_imputed(r, base_rates, w, min_legs=DEFAULT_MIN_LEGS):
    """Score the 10 legs, imputing the ones whose inputs were scrubbed away.

        score = earned + sum(imputed_i for each missing leg i)

    Each missing leg is credited at a blend of what this row managed on the
    legs it does have and what the universe manages on that specific leg:

        imputed_i = w * row_rate + (1 - w) * base_rate_i

    w = 1 is exactly earned/available * 10 (missing legs assumed to go the way
    the row's own legs went). w = 0 credits every missing leg at the universe
    base rate, so a bank is neither rewarded nor punished for the legs it can
    never have. In between trades one against the other.

    Unlike quality_score_shrunk this leaves full-coverage rows untouched by
    construction — there is nothing to impute — so the 0 and 10 ends of the
    scale survive.
    """
    legs = leg_detail(r)
    available = [name for name, a, _ in legs if a]
    if len(available) < min_legs:
        return None
    earned = sum(1 for name, a, won in legs if a and won)
    row_rate = earned / len(available)
    imputed = sum(
        w * row_rate + (1 - w) * base_rates.get(name, 0.5)
        for name, a, _ in legs if not a
    )
    return round(min(10.0, earned + imputed))


def _fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def _fmt_signed(x, nd=1):
    return "-" if x is None else f"{x:+.{nd}f}"


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _table(title, rowkey, rows, labels):
    """Group rows by rowkey(row); mean score before, then once per variant."""
    groups = defaultdict(list)
    for r in rows:
        groups[rowkey(r)].append(r)

    print(f"\n{title}  (mean score; n/a rows excluded from the mean)")
    hdr = f"{'group':<24}{'n':>5}{'legs':>6}{'before':>8}"
    hdr += "".join(f"{lab:>8}" for lab in labels) + f"{'n/a':>6}"
    print(hdr)
    print("-" * len(hdr))
    for key in sorted(groups, key=lambda g: -len(groups[g])):
        g = groups[key]
        before = [r["_before"] for r in g if r["_before"] is not None]
        avail = [r["_available"] for r in g]
        line = (f"{str(key)[:23]:<24}{len(g):>5}{_fmt(_mean(avail)):>6}"
                f"{_fmt(_mean(before)):>8}")
        for lab in labels:
            vals = [r["_v"][lab] for r in g if r["_v"][lab] is not None]
            line += f"{_fmt(_mean(vals)):>8}"
        n_none = sum(1 for r in g if r["_v"][labels[0]] is None)
        print(line + f"{n_none:>6}")


def _histogram(rows, labels):
    print("\nScore distribution (whole universe)")
    hdr = f"{'score':<8}{'before':>9}" + "".join(f"{lab:>8}" for lab in labels)
    print(hdr)
    print("-" * len(hdr))
    for s in list(range(11)) + [None]:
        label = "n/a" if s is None else str(s)
        line = f"{label:<8}{sum(1 for r in rows if r['_before'] == s):>9}"
        for lab in labels:
            line += f"{sum(1 for r in rows if r['_v'][lab] == s):>8}"
        print(line)


def _thin_row_check(base_rates, ks, ws, min_legs):
    """What a perfect and a hopeless thin row score under each variant.

    A row that passes every leg it has should not out-rank a 10-leg company
    that passed all ten; equally, a row that failed every leg it has should not
    be dragged up to average. This prints both ends for a typical row.
    """
    typical = _mean(list(base_rates.values()))
    for label, perfect in (("all legs PASSED", True), ("all legs FAILED", False)):
        print(f"\nWhat a row scores by coverage — {label}")
        hdr = (f"{'legs':<6}" + "".join(f"{'k=' + str(k):>8}" for k in ks)
               + "".join(f"{'w=' + str(w):>8}" for w in ws))
        print(hdr)
        print("-" * len(hdr))
        for n in (3, 4, 5, 6, 8, 10):
            line = f"{n:<6}"
            earned = n if perfect else 0
            for k in ks:
                if n < min_legs:
                    line += f"{'n/a':>8}"
                else:
                    line += f"{round((earned + k * typical) / (n + k) * 10):>8}"
            for w in ws:
                if n < min_legs:
                    line += f"{'n/a':>8}"
                else:
                    row_rate = earned / n
                    imp = (10 - n) * (w * row_rate + (1 - w) * typical)
                    line += f"{round(min(10.0, earned + imp)):>8}"
            print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-legs", type=int, default=DEFAULT_MIN_LEGS,
                    help=f"legs required before a score is emitted (default {DEFAULT_MIN_LEGS})")
    ap.add_argument("--k", type=float, nargs="+", default=[0, 2, 3, 5],
                    help="shrinkage strengths to compare (default 0 2 3 5; 0 = no shrinkage)")
    ap.add_argument("--w", type=float, nargs="+", default=[0, 0.5, 1],
                    help="imputation blends to compare (default 0 0.5 1; "
                         "0 = universe base rate, 1 = row's own rate)")
    ap.add_argument("--csv", help="also write a per-company dump here")
    ap.add_argument("--movers", type=int, default=15,
                    help="how many biggest movers to list (default 15)")
    args = ap.parse_args()

    ks = [int(k) if float(k).is_integer() else k for k in args.k]
    ws = args.w
    k_labels = [f"k={k}" for k in ks]
    w_labels = [f"w={w:g}" for w in ws]
    labels = k_labels + w_labels

    rows = query(SQL, [])
    print(f"Loaded {len(rows)} companies from ttm_financials")

    # Exactly the production pipeline order (main.py:1762-1770): scrub, then
    # pegy, then score. The sector rename to ICB happens after scoring.
    _scrub_screener_metrics(rows)
    _attach_pegy(rows)

    base_rates = leg_base_rates(rows)
    print("\nUniverse base rate per leg (the shrinkage target)")
    for name, rate in sorted(base_rates.items(), key=lambda kv: -kv[1]):
        print(f"  {name:<10}{rate * 100:>5.0f}%")

    for r in rows:
        # risk_model is popped-through by the scrub only when screener_scores
        # covered the row; fall back the same way the scrub does.
        r["_model"] = r.get("risk_model") or _classify_risk_model(r)
        r["_before"] = _quality_score(r)
        _, r["_available"] = quality_legs(r)
        r["_icb"] = to_icb(r["sector"]) if r.get("sector") else "Unknown"
        r["_v"] = {}
        for k, lab in zip(ks, k_labels):
            r["_v"][lab] = quality_score_shrunk(r, base_rates, k, args.min_legs)
        for w, lab in zip(ws, w_labels):
            r["_v"][lab] = quality_score_imputed(r, base_rates, w, args.min_legs)

    # Invariant: at full coverage every variant should reproduce the current
    # score. Shrinkage breaks this by design (it pulls every row toward the
    # prior); imputation cannot, since there is nothing to impute.
    full = sum(1 for r in rows if r["_available"] == 10)
    print(f"\nFull-coverage rows ({full}) that MOVE — should be 0:")
    for lab in labels:
        broken = [r for r in rows
                  if r["_available"] == 10 and r["_before"] != r["_v"][lab]]
        note = ""
        if broken:
            note = "  e.g. " + ", ".join(
                f"{r['symbol']} {r['_before']}->{r['_v'][lab]}" for r in broken[:4])
        print(f"  {lab:<8}{len(broken):>4}{note}")

    _table("By sector (ICB)", lambda r: r["_icb"], rows, labels)
    _table("By risk model", lambda r: r["_model"], rows, labels)
    _histogram(rows, labels)
    _thin_row_check(base_rates, ks, ws, args.min_legs)

    for lab in labels:
        moved = [r for r in rows
                 if r["_before"] is not None and r["_v"][lab] is not None
                 and r["_v"][lab] != r["_before"]]
        ups = sorted(moved, key=lambda r: -(r["_v"][lab] - r["_before"]))
        downs = sorted(moved, key=lambda r: r["_v"][lab] - r["_before"])
        n_down = sum(1 for r in moved if r["_v"][lab] < r["_before"])
        print(f"\n{lab}: {len(moved)} of {len(rows)} change "
              f"({len(moved) - n_down} up, {n_down} down). Biggest {args.movers} up:")
        print(f"{'symbol':<10}{'name':<28}{'model':<14}{'legs':>5}{'before':>8}{'after':>7}")
        print("-" * 72)
        for r in ups[:args.movers]:
            print(f"{r['symbol']:<10}{(r['name'] or '')[:27]:<28}{r['_model']:<14}"
                  f"{r['_available']:>5}{r['_before']:>8}{r['_v'][lab]:>7}")
        if n_down:
            print("  biggest down: " + ", ".join(
                f"{r['symbol']} {r['_before']}->{r['_v'][lab]}" for r in downs[:6]))

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "name", "sector_icb", "risk_model",
                        "legs_available", "quality_before"]
                       + [f"quality_{lab}" for lab in labels])
            for r in rows:
                w.writerow([r["symbol"], r["name"], r["_icb"], r["_model"],
                            r["_available"], r["_before"]]
                           + [r["_v"][lab] for lab in labels])
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
