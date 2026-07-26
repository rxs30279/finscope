"""Distribution of the four factor scores by sector — an anomaly hunt.

Read-only. Nothing is written to the DB. This imports the production scrub and
score functions and reads the stored momentum/risk scores, so what it plots is
exactly what /api/screener and /watchlist serve today.

Why: quality_score turned out to be structurally capped for financials — the
scrub blanked the legs a bank can never have, and the score read a blanked leg
as a failed one, so no bank could clear 4/10 however good it was. That was
invisible in a mean and obvious in a distribution: the whole sector's box sat
against a ceiling no other sector had. This script looks for the same shape in
all four factors at once.

The signatures it flags, per (factor, sector) cell:
  CEILING   the sector's best name lands well below what the universe reaches
  FLOOR     the sector's worst name lands well above what the universe reaches
  FLAT      the middle 50% is a single value — the score does not discriminate
  SHIFT     the median sits far from the universe median
  N/A       the factor is unscoreable for much of the sector

A flag is a question, not a verdict: momentum is a universe-wide decile rank, so
a sector genuinely being in a downtrend is a real SHIFT, not a bug. What marks a
*defect* is a bound the data cannot cross — a ceiling or a floor — especially
one that lines up with a risk_model rather than with an economic story.

Usage:
    python backend/analysis/factor_score_distributions.py
    python backend/analysis/factor_score_distributions.py --by model
    python backend/analysis/factor_score_distributions.py --min-n 5 --csv out.csv
    python backend/analysis/factor_score_distributions.py --png charts.png
"""

import argparse
import os
import sys
from collections import defaultdict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

from db import query
from quality import effective_model
from sectors import to_icb
from main import (
    _attach_pegy,
    _classify_risk_model,
    _quality_score,
    _scrub_screener_metrics,
    _value_score,
)

# (key, display label). Momentum and risk come precomputed from screener_scores;
# quality and value are computed inline here exactly as the endpoint does.
FACTORS = [
    ("momentum_score", "Momentum"),
    ("quality_score", "Quality"),
    ("value_score", "Value"),
    ("risk_score", "Risk"),
]

# Anomaly thresholds, in score points on the shared 0-10 scale.
CEILING_GAP = 2.0   # universe max - sector max
FLOOR_GAP = 2.0     # sector min - universe min
SHIFT_GAP = 2.0     # |sector median - universe median|
NA_RATE = 0.30      # share of the sector with no score

# The production screener SQL (main.py:1619), unfiltered and trimmed to the
# columns the scrub and the two inline scores read, plus the stored scores.
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
           s.momentum_score, s.risk_score, s.risk_model
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


def _pct(xs, p):
    """Linear-interpolated percentile over a pre-sorted list (numpy-free)."""
    if not xs:
        return None
    if len(xs) == 1:
        return float(xs[0])
    i = (len(xs) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return float(xs[lo]) + (float(xs[hi]) - float(xs[lo])) * (i - lo)


def summarise(values):
    """Five-number summary + n, over the non-None values."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    return {
        "n": len(xs),
        "min": float(xs[0]),
        "q1": _pct(xs, 0.25),
        "med": _pct(xs, 0.50),
        "q3": _pct(xs, 0.75),
        "max": float(xs[-1]),
        "values": xs,
    }


def flags(s, universe):
    """Anomaly flags for one (factor, group) cell against the universe."""
    out = []
    if universe["max"] - s["max"] >= CEILING_GAP:
        out.append(f"CEILING max {s['max']:.0f} vs {universe['max']:.0f}")
    if s["min"] - universe["min"] >= FLOOR_GAP:
        out.append(f"FLOOR min {s['min']:.0f} vs {universe['min']:.0f}")
    if s["q3"] == s["q1"]:
        out.append(f"FLAT IQR=0 at {s['q1']:.0f}")
    if abs(s["med"] - universe["med"]) >= SHIFT_GAP:
        out.append(f"SHIFT med {s['med']:.1f} vs {universe['med']:.1f}")
    return out


def _fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def print_factor_table(label, key, groups, order, universe):
    print(f"\n{label}  (0-10; box = q1/median/q3, whisker = min/max)")
    hdr = (f"{'group':<24}{'n':>5}{'n/a':>5}{'min':>6}{'q1':>6}{'med':>6}"
           f"{'q3':>6}{'max':>6}  flags")
    print(hdr)
    print("-" * 96)
    for g in order:
        rows = groups[g]
        s = summarise([r[key] for r in rows])
        n_na = sum(1 for r in rows if r[key] is None)
        if s is None:
            print(f"{g[:23]:<24}{0:>5}{n_na:>5}{'':>30}  ALL N/A")
            continue
        line = (f"{g[:23]:<24}{s['n']:>5}{n_na:>5}{s['min']:>6.0f}{s['q1']:>6.1f}"
                f"{s['med']:>6.1f}{s['q3']:>6.1f}{s['max']:>6.0f}")
        fl = flags(s, universe)
        if n_na / max(1, len(rows)) >= NA_RATE:
            fl.append(f"N/A {n_na / len(rows) * 100:.0f}% unscored")
        print(line + "  " + "; ".join(fl))
    line = (f"{'ALL':<24}{universe['n']:>5}{'':>5}{universe['min']:>6.0f}"
            f"{universe['q1']:>6.1f}{universe['med']:>6.1f}{universe['q3']:>6.1f}"
            f"{universe['max']:>6.0f}")
    print(line)


def draw(rows, groups, order, group_label, path):
    """Four small multiples — one factor each, one horizontal box per group.

    Same group order and same 0-10 x-axis in every panel, so a bound that hits
    one sector in one factor reads as a step out of line rather than needing a
    number-by-number comparison.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    # Categorical slots 1-4, fixed order — identity only; each panel is one hue.
    HUES = ["#2a78d6", "#1baf7a", "#eda100", "#e34948"]

    ypos = list(range(len(order), 0, -1))  # first group at the top
    fig, axes = plt.subplots(
        1, 4, figsize=(17, 1.0 + 0.42 * len(order)), sharey=True)
    fig.patch.set_facecolor(SURFACE)

    for ax, (key, label), hue in zip(axes, FACTORS, HUES):
        ax.set_facecolor(SURFACE)
        data, pos = [], []
        for g, y in zip(order, ypos):
            vals = [r[key] for r in groups[g] if r[key] is not None]
            n_na = len(groups[g]) - len(vals)
            if vals:
                data.append(vals)
                pos.append(y)
            # A box drawn from a third of a group says something different from
            # a box drawn from all of it, and an absent box is the loudest
            # result of all — neither is visible in the geometry, so both get a
            # word. Quiet cells stay unlabelled (no number on every row).
            if not vals:
                ax.text(5.0, y, f"no score for any of {len(groups[g])}",
                        va="center", ha="center", fontsize=8.5, color=INK_2,
                        style="italic")
            elif n_na / len(groups[g]) >= NA_RATE:
                # In the gutter past the axis, so it can never sit on a whisker.
                ax.text(10.7, y, f"{n_na / len(groups[g]) * 100:.0f}% n/a",
                        va="center", ha="left", fontsize=7.5, color=INK_2)
        uni = summarise([r[key] for r in rows])
        if uni:
            ax.axvline(uni["med"], color=INK_2, lw=1, ls=(0, (4, 3)),
                       alpha=0.55, zorder=1)

        bp = ax.boxplot(data, positions=pos, vert=False, widths=0.62,
                        patch_artist=True, showfliers=True, zorder=2)
        for box in bp["boxes"]:
            box.set(facecolor=hue, edgecolor=hue, alpha=0.30, linewidth=1.2)
        for whisk in bp["whiskers"] + bp["caps"]:
            whisk.set(color=hue, linewidth=1.4)
        for med in bp["medians"]:
            med.set(color=hue, linewidth=2.4)
        for fl in bp["fliers"]:
            fl.set(marker="o", markersize=3.2, markerfacecolor=hue,
                   markeredgecolor=SURFACE, markeredgewidth=0.6, alpha=0.8)

        ax.set_title(label, color=INK, fontsize=12, pad=9, loc="left")
        ax.set_xlim(-0.4, 12.3)
        ax.set_xticks(range(0, 11, 2))
        ax.tick_params(colors=INK_2, labelsize=9, length=0)
        ax.xaxis.grid(True, color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ax.spines.values():
            side.set_visible(False)

    axes[0].set_yticks(ypos)
    axes[0].set_yticklabels([f"{g}  ({len(groups[g])})" for g in order],
                            fontsize=9.5, color=INK)
    axes[0].set_ylim(0.4, len(order) + 0.6)

    fig.suptitle(
        f"Factor score distribution by {group_label}  —  {len(rows)} companies"
        "   (dashed line = universe median)",
        color=INK, fontsize=13, x=0.005, ha="left", y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    print(f"\nWrote {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--by", choices=["sector", "model", "eff-model"], default="sector",
                    help="group by ICB sector (default), by the stored risk_model, "
                         "or by the model the scrub actually applied (eff-model)")
    ap.add_argument("--min-n", type=int, default=5,
                    help="drop groups smaller than this (default 5)")
    ap.add_argument("--png", default=os.path.join(_SCRIPT_DIR, "factor_distributions.png"),
                    help="where to write the chart")
    ap.add_argument("--no-png", action="store_true", help="tables only")
    ap.add_argument("--csv", help="also write a per-company dump here")
    args = ap.parse_args()

    rows = query(SQL, [])
    print(f"Loaded {len(rows)} companies from ttm_financials")

    # Exactly the production pipeline order (main.py:1660-1668): scrub, pegy,
    # then the two inline scores. Sector renames to ICB after scoring.
    _scrub_screener_metrics(rows)
    _attach_pegy(rows)
    for r in rows:
        r["quality_score"] = _quality_score(r)
        r["value_score"] = _value_score(r)
        r["_model"] = r.get("risk_model") or _classify_risk_model(r)
        # The model whose rules actually applied, which is NOT always _model: a
        # fund Yahoo files under Asset Management is name-matched up to "trust"
        # while classify_risk_model still calls it "financial". Grouping by the
        # stored model alone hides those rows inside the financial bucket,
        # which is where they were hiding.
        r["_eff"] = effective_model(r)
        r["_icb"] = to_icb(r.get("sector")) or "Unknown"

    mismatch = [r for r in rows if r["_eff"] != r["_model"]]
    if mismatch:
        print(f"\n{len(mismatch)} rows are blanked as trusts but carry risk_model "
              f"'{mismatch[0]['_model']}' — the scrub and the risk score disagree "
              "about the same company: "
              + ", ".join(r["symbol"] for r in mismatch[:8]) + ", ...")

    keyfn = {
        "sector": lambda r: r["_icb"],
        "model": lambda r: r["_model"],
        "eff-model": lambda r: r["_eff"],
    }[args.by]
    groups = defaultdict(list)
    for r in rows:
        groups[keyfn(r)].append(r)
    small = [g for g in groups if len(groups[g]) < args.min_n]
    for g in small:
        del groups[g]
    if small:
        print(f"Dropped {len(small)} groups under n={args.min_n}: {', '.join(sorted(small))}")
    order = sorted(groups, key=lambda g: -len(groups[g]))

    for key, label in FACTORS:
        universe = summarise([r[key] for r in rows])
        if universe is None:
            print(f"\n{label}: no scores at all")
            continue
        print_factor_table(label, key, groups, order, universe)

    print("\nFlag summary — a bound the data cannot cross is the defect shape")
    print(f"{'group':<24}{'factor':<12}flag")
    print("-" * 72)
    any_flag = False
    for g in order:
        for key, label in FACTORS:
            universe = summarise([r[key] for r in rows])
            s = summarise([r[key] for r in groups[g]])
            if not (s and universe):
                continue
            for f in flags(s, universe):
                any_flag = True
                print(f"{g[:23]:<24}{label:<12}{f}")
    if not any_flag:
        print("(none)")

    if not args.no_png:
        draw(rows, groups, order, args.by, args.png)

    if args.csv:
        import csv
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "name", "sector_icb", "risk_model", "scrubbed_as"]
                       + [k for k, _ in FACTORS])
            for r in rows:
                w.writerow([r["symbol"], r["name"], r["_icb"], r["_model"], r["_eff"]]
                           + [r[k] for k, _ in FACTORS])
        print(f"Wrote {args.csv}")


if __name__ == "__main__":
    main()
