"""Phase 0 exploratory analysis — does llm_score predict forward return?

Read-only. Joins scored Tier A/B rns_announcements to price_history and measures
excess forward return at 1d / 1w / 1m / 3m, faceted by score band, sentiment and
scoring model (llm_model — the DeepSeek "flash reasoning" switch). Prints a
calibration table + Spearman rank correlation; nothing is written to the DB.

This is a throwaway validation step for docs/rns-score-performance-plan.md — it
confirms (or kills) the signal before any monitoring table or page is built.

Conventions (see the plan doc for the reasoning):
  * Entry = the OPEN on the announcement day itself. RNS drops ~07:00, before the
    08:00 LSE open, so the news is priced into that day's session and the open is
    buyable at 08:00. (Entering the NEXT day starts the clock a full session late,
    after the reaction is priced — it flattens the entire signal.) The day-1
    reaction is decomposed into gap (prev close->open, pre-open & untradeable),
    intraday (open->close, tradeable), and since-news (prev close->close).
  * Horizon h = holding period in TRADING days from the entry day, measured to
    the close. 1d/1w/1m/3m -> 1/5/21/63 trading days -> close at index e+(h-1).
  * Excess return = stock_return - benchmark_return, where the benchmark is an
    equal-weighted daily-return index built from price_history itself, split
    AIM vs Main (index proxies like ^FTSE are not ingested into price_history,
    and AIM runs ~1.5x the vol of the index tiers). Raw return is kept too.
  * A horizon with insufficient elapsed time is 'open'; one that can never fill
    because the symbol stopped updating (delisting) is 'terminated'. Neither
    contaminates the matured-only stats.

Usage:
    python backend/analysis/rns_score_perf.py               # print summary
    python backend/analysis/rns_score_perf.py --csv out.csv # + per-row dump
    python backend/analysis/rns_score_perf.py --min-score 60 --sentiment positive
"""

import argparse
import os
import sys
from datetime import timedelta

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

import numpy as np
import pandas as pd

from db import query

# Holding period in trading days. close index = entry_index + (days - 1).
HORIZONS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63}

# Score bands aligned to the thresholds the digest analysis already found
# meaningful (the ~3.4x big-move lift sat around 76+). Right edge exclusive.
BANDS = [(0, 40), (40, 60), (60, 76), (76, 85), (85, 101)]

# A symbol whose last recorded bar is older than this behind the global latest
# date is treated as delisted/suspended -> unfillable horizons are 'terminated',
# not 'open'. ~10 calendar days covers a long weekend + bank holiday gap.
_STALE_DAYS = 10

# Guard the equal-weighted benchmark against bad ticks: a single fat-fingered
# yfinance bar (e.g. a 10x split glitch) would otherwise blow up the market mean.
_MKT_RET_CLAMP = (-0.5, 1.0)


def _band_label(score):
    for lo, hi in BANDS:
        if lo <= score < hi:
            return f"{lo}-{hi - 1}"
    return "?"


def _seg(ftse_index):
    """Coarse listing segment for the benchmark split."""
    return "AIM" if (ftse_index or "").upper().find("AIM") >= 0 else "Main"


def load_scored_rows(min_score=None):
    """Scored Tier A/B announcements with a resolved symbol and a listing label.

    llm_score/llm_sentiment/llm_model are the point-in-time values as written by
    the ranker (never re-scored), so this is already look-ahead safe.
    """
    where = ["r.llm_score IS NOT NULL", "r.symbol IS NOT NULL", "r.tier IN ('A','B')"]
    params = []
    if min_score is not None:
        where.append("r.llm_score >= %s")
        params.append(min_score)
    rows = query(
        f"""
        SELECT r.id, r.symbol, r.published_at, r.llm_score, r.llm_sentiment,
               r.llm_model, r.category, r.tier, m.ftse_index
        FROM rns_announcements r
        LEFT JOIN company_metadata m ON m.symbol = r.symbol
        WHERE {' AND '.join(where)}
        ORDER BY r.published_at
        """,
        params or None,
    )
    for r in rows:
        r["seg"] = _seg(r["ftse_index"])
    return rows


def load_price_series(symbols):
    """symbol -> DataFrame(date, open, close) sorted ascending, indexed 0..n-1."""
    if not symbols:
        return {}
    rows = query(
        """
        SELECT symbol, date, open, close
        FROM price_history
        WHERE symbol = ANY(%s)
        ORDER BY symbol, date
        """,
        (list(symbols),),
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    out = {}
    for sym, g in df.groupby("symbol"):
        out[sym] = g.reset_index(drop=True)
    return out


def build_benchmark():
    """seg -> DataFrame(date, level) — equal-weighted cumulative return index.

    Per-symbol daily returns are averaged across the whole active universe for
    each date, clamped to drop bad ticks, then compounded into an index level so
    a benchmark return between any two trading dates is level[d2]/level[d1]-1.
    """
    rows = query(
        f"""
        WITH labelled AS (
            SELECT p.symbol, p.date, p.close,
                   CASE WHEN COALESCE(m.ftse_index,'') ILIKE '%%AIM%%'
                        THEN 'AIM' ELSE 'Main' END AS seg
            FROM price_history p
            JOIN company_metadata m ON m.symbol = p.symbol AND m.is_active
        ),
        rets AS (
            SELECT seg, date,
                   close / NULLIF(LAG(close) OVER (
                       PARTITION BY symbol ORDER BY date), 0) - 1 AS ret
            FROM labelled
        )
        SELECT seg, date, AVG(ret) AS mkt_ret, COUNT(ret) AS n
        FROM rets
        WHERE ret IS NOT NULL AND ret BETWEEN {_MKT_RET_CLAMP[0]} AND {_MKT_RET_CLAMP[1]}
        GROUP BY seg, date
        ORDER BY seg, date
        """
    )
    df = pd.DataFrame(rows)
    out = {}
    if df.empty:
        return out
    df["date"] = pd.to_datetime(df["date"])
    df["mkt_ret"] = pd.to_numeric(df["mkt_ret"], errors="coerce").fillna(0.0)
    for seg, g in df.groupby("seg"):
        g = g.sort_values("date").reset_index(drop=True)
        g["level"] = (1.0 + g["mkt_ret"]).cumprod()
        out[seg] = g.set_index("date")["level"]
    return out


def _bench_return(bench, seg, entry_date, exit_date):
    """Benchmark return between two trading dates for a segment (None if absent)."""
    lvl = bench.get(seg)
    if lvl is None:
        return None
    try:
        return float(lvl.loc[exit_date]) / float(lvl.loc[entry_date]) - 1.0
    except KeyError:
        return None


def compute_returns(rows, series, bench, global_last):
    """One record per (announcement, horizon) with raw + excess return + status."""
    stale_cutoff = global_last - pd.Timedelta(days=_STALE_DAYS)
    out = []
    skipped_no_entry = 0
    for r in rows:
        g = series.get(r["symbol"])
        if g is None or g.empty:
            continue
        pub = pd.Timestamp(r["published_at"]).tz_localize(None).normalize()
        # Entry = the announcement day itself. RNS drops ~07:00, before the 08:00
        # LSE open, so the news is priced into THAT day's session — the entry open
        # is buyable at 08:00. Entering the *next* day (date > pub) starts the clock
        # a full session late, after the reaction is priced, which flattens the
        # whole signal. Pre-news reference = last close strictly before that day.
        prev = g[g["date"] < pub]
        after = g[g["date"] >= pub]
        if after.empty:
            continue
        e = int(after.index[0])  # entry row = first trading day on/after publish
        entry_open = g.at[e, "open"]
        if pd.isna(entry_open) or entry_open <= 0:
            skipped_no_entry += 1
            continue
        entry_date = g.at[e, "date"]
        sym_last = g["date"].iloc[-1]
        pre_close = float(prev["close"].iloc[-1]) if not prev.empty and pd.notna(prev["close"].iloc[-1]) else None
        # Overnight gap = the pre-open reaction, where most of the signal lives.
        # Untradeable at pre_close, so kept as a diagnostic, not an entry price.
        gap = (float(entry_open) / pre_close - 1.0) if pre_close else None
        base = {
            "id": r["id"], "symbol": r["symbol"], "seg": r["seg"],
            "published_at": r["published_at"], "llm_score": r["llm_score"],
            "band": _band_label(r["llm_score"]),
            "sentiment": r["llm_sentiment"] or "unknown",
            "model": r["llm_model"] or "unknown",
            "category": r["category"], "entry_date": entry_date.date(),
            "entry_open": entry_open, "pre_close": pre_close, "gap": gap,
        }
        for hname, hdays in HORIZONS.items():
            idx = e + (hdays - 1)
            rec = dict(base, horizon=hname)
            if idx < len(g):
                exit_date = g.at[idx, "date"]
                exit_close = g.at[idx, "close"]
                if pd.isna(exit_close):
                    rec.update(status="open", raw=None, excess=None, since_news=None)
                else:
                    raw = float(exit_close) / float(entry_open) - 1.0
                    br = _bench_return(bench, r["seg"], entry_date, exit_date)
                    rec.update(
                        status="matured", raw=raw,
                        excess=(raw - br) if br is not None else None,
                        # since_news = pre-news close -> horizon close (includes the
                        # gap): the full news reaction, not the tradeable-from-open one.
                        since_news=(float(exit_close) / pre_close - 1.0) if pre_close else None,
                    )
            else:
                # Not enough bars yet: delisted -> terminated, else still pending.
                rec.update(
                    status="terminated" if sym_last < stale_cutoff else "open",
                    raw=None, excess=None, since_news=None,
                )
            out.append(rec)
    return pd.DataFrame(out), skipped_no_entry


# ── Reporting ─────────────────────────────────────────────────────────────────


def _spearman(a, b):
    """Rank correlation without scipy: Pearson on the ranks."""
    if len(a) < 3:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def _fmt_pct(x):
    return "  n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.2f}%"


def _print_day1_decomp(df):
    """Where the first-day reaction lands: gap vs tradeable-intraday vs since-news.

    Uses the 1d horizon rows (raw = open->close intraday; gap = prev close->open;
    since_news = prev close->close). The gap is the pre-open reaction, which is
    NOT buyable at the pre-news close — the tradeable-from-open column is what an
    08:00 buyer actually captures. Matured for every announcement (needs 1 day).
    """
    d1 = df[(df["horizon"] == "1d") & df["gap"].notna()].copy()
    if d1.empty:
        return
    print("\n-- Day-1 reaction decomposition (medians; gap is pre-open, untradeable) --")
    print(f"   {'band':<8}{'sent':<10}{'n':>5}{'gap':>11}{'intraday':>11}{'since-news':>12}{'gap hit%':>10}")
    for lo, hi in BANDS:
        band = f"{lo}-{hi - 1}"
        for sent in ("positive", "negative", "neutral"):
            c = d1[(d1["band"] == band) & (d1["sentiment"] == sent)]
            if len(c) < 2:
                continue
            intraday = c["raw"].median()
            print(f"   {band:<8}{sent:<10}{len(c):>5}"
                  f"{c['gap'].median() * 100:>10.2f}%"
                  f"{intraday * 100:>10.2f}%"
                  f"{c['since_news'].median() * 100:>11.2f}%"
                  f"{(c['gap'] > 0).mean() * 100:>9.0f}%")
    print("\n   Spearman(score, X) by sentiment:")
    print(f"   {'sentiment':<10}{'gap':>10}{'intraday':>10}{'since-news':>12}")
    for sent in ("positive", "negative", "neutral"):
        c = d1[d1["sentiment"] == sent]
        if len(c) < 3:
            continue
        rg = _spearman(c["llm_score"].to_numpy(), c["gap"].to_numpy())
        ri = _spearman(c["llm_score"].to_numpy(), c["raw"].to_numpy())
        sn = c[["llm_score", "since_news"]].dropna()
        rs = _spearman(sn["llm_score"].to_numpy(), sn["since_news"].to_numpy()) \
            if len(sn) >= 3 else float("nan")
        print(f"   {sent:<10}{rg:>10.3f}{ri:>10.3f}{rs:>12.3f}")


def print_report(df):
    if df.empty:
        print("No rows to analyse.")
        return

    total_ann = df["id"].nunique()
    span_lo = pd.to_datetime(df["published_at"]).min()
    span_hi = pd.to_datetime(df["published_at"]).max()
    print(f"\n=== RNS score vs forward return -- {total_ann} scored A/B announcements ===")
    print(f"    published span: {span_lo:%Y-%m-%d} -> {span_hi:%Y-%m-%d} "
          f"({(span_hi - span_lo).days} calendar days of scored history)")
    print("    NB: 1m/3m need >=21/63 trading days elapsed since the announcement;")
    print("        with this little history they stay 'open' until enough time passes.")

    # Coverage: how much of each horizon has actually matured.
    print("\n-- Horizon maturity --")
    cov = df.groupby(["horizon", "status"]).size().unstack(fill_value=0)
    cov = cov.reindex(list(HORIZONS), fill_value=0)
    print(cov.to_string())

    mat = df[(df["status"] == "matured") & df["excess"].notna()].copy()
    if mat.empty:
        print("\nNothing matured with a benchmark yet -- come back once horizons fill in.")
        return

    print("\n-- Model segments present (llm_model) --")
    for m, n in mat["model"].value_counts().items():
        print(f"   {m:<32} {n} matured horizon-rows")

    _print_day1_decomp(df)

    def _calib(sub, title):
        print(f"\n-- Calibration: {title} (excess return vs equal-weighted benchmark) --")
        print(f"   {'band':<8}{'sent':<10}" + "".join(f"{h:>26}" for h in HORIZONS))
        print(f"   {'':<8}{'':<10}" + "".join(f"{'median | hit% | n':>26}" for _ in HORIZONS))
        for band, _ in [(f"{lo}-{hi - 1}", None) for lo, hi in BANDS]:
            for sent in ("positive", "negative", "neutral"):
                cells = []
                any_data = False
                for h in HORIZONS:
                    c = sub[(sub["band"] == band) & (sub["sentiment"] == sent) & (sub["horizon"] == h)]
                    if len(c):
                        any_data = True
                        med = c["excess"].median()
                        hit = (c["excess"] > 0).mean()
                        cells.append(f"{med * 100:+6.2f} | {hit * 100:4.0f} | {len(c):>4}")
                    else:
                        cells.append(f"{'-':>19}")
                if any_data:
                    print(f"   {band:<8}{sent:<10}" + "".join(f"{c:>26}" for c in cells))

    _calib(mat, "all models pooled")

    # Per-model calibration for the models with enough data (the flash-reasoning
    # switch is the whole reason for the study — show old vs new side by side).
    for model in mat["model"].value_counts().index:
        sub = mat[mat["model"] == model]
        if len(sub) >= 20:
            _calib(sub, f"model = {model}")

    # Continuous rank correlation: score vs excess, per horizon, sign-split by
    # sentiment (magnitude should predict UP for positive, DOWN for negative).
    print("\n-- Spearman(score, excess) by horizon & sentiment --")
    print(f"   {'sentiment':<10}" + "".join(f"{h:>10}" for h in HORIZONS))
    for sent in ("positive", "negative", "neutral"):
        cells = []
        for h in HORIZONS:
            c = mat[(mat["sentiment"] == sent) & (mat["horizon"] == h)]
            rho = _spearman(c["llm_score"].to_numpy(), c["excess"].to_numpy()) if len(c) >= 3 else float("nan")
            cells.append(f"{rho:>10.3f}" if not np.isnan(rho) else f"{'n/a':>10}")
        print(f"   {sent:<10}" + "".join(cells))
    print("\n(positive-sentiment rho should be > 0 and negative < 0 if score carries signal)")


def _write_explanation_sheet(writer, df):
    """Add a formatted 'explanation' sheet (first tab) describing the workbook."""
    from openpyxl.styles import Font, Alignment

    wb = writer.book
    ws = wb.create_sheet("explanation", 0)
    ws.column_dimensions["A"].width = 118
    ws.sheet_view.showGridLines = False

    # Dynamic summary numbers so the doc always matches the data in the file.
    pa = pd.to_datetime(df["published_at"], utc=True)
    span = f"{pa.min():%Y-%m-%d} to {pa.max():%Y-%m-%d}"
    uniq = df.drop_duplicates("id")
    total = len(uniq)
    models = "; ".join(f"{m} ({n})" for m, n in uniq["model"].value_counts().items())
    mat = df[df["status"] == "matured"].groupby("horizon").size().reindex(list(HORIZONS), fill_value=0)
    matured = ", ".join(f"{h}: {int(mat[h])}" for h in HORIZONS)

    lines = [
        ("title", "RNS Score vs Forward Return - analysis workbook"),
        ("meta", f"Generated by backend/analysis/rns_score_perf.py  |  data as of {pa.max():%Y-%m-%d}"),
        ("gap", ""),
        ("h", "WHAT THIS IS"),
        ("body", "Does the LLM impact score (llm_score, 0-100) on an RNS announcement predict the "
                 "subsequent share-price move? This workbook joins every scored announcement to our "
                 "daily price history and measures the reaction at 1 day / 1 week / 1 month / 3 months, "
                 "split by score band, news sentiment and the scoring model."),
        ("gap", ""),
        ("h", "DATA & SCOPE"),
        ("body", f"Announcements analysed: {total}.  Published span: {span} "
                 "(scored history only reaches back to 2026-06-29 - the point-in-time scores before "
                 "that were pruned, so this is all we have)."),
        ("bullet", f"Scoring models present (unique announcements): {models}. "
                   "deepseek-chat is the old model; deepseek-v4-flash:thinking is the new 'flash "
                   "reasoning' model live since ~2026-07-15. Segment by this to compare them."),
        ("bullet", "Source: Tier A/B rns_announcements (the only tiers the LLM scores) joined to "
                   "price_history (daily OHLCV, split/dividend-adjusted). Rows with no resolved "
                   "symbol are excluded (no price series to join)."),
        ("gap", ""),
        ("h", "HOW RETURNS ARE MEASURED  (read this - it changes the numbers)"),
        ("bullet", "ENTRY = the OPEN on the announcement day itself. RNS drops ~07:00, before the "
                   "08:00 London open, so the news is priced into that day's session and the open is "
                   "the first price you could actually buy at. (An earlier version entered the NEXT "
                   "day and found 'no signal' - that was an off-by-one bug: it started measuring after "
                   "the reaction was already priced. Fixed.)"),
        ("bullet", "The first-day move is split into three parts:"),
        ("indent", "gap = previous close -> announcement-day open. The pre-open reaction. This is where "
                   "most of the signal lives, but you CANNOT buy at the previous close, so it is not "
                   "tradeable - it's diagnostic only."),
        ("indent", "intraday (shown as 'raw' at the 1d horizon) = open -> close. What an 08:00 buyer "
                   "actually captures on day one."),
        ("indent", "since_news = previous close -> close. The full reaction including the gap."),
        ("bullet", "Horizons 1d/1w/1m/3m = 1/5/21/63 TRADING days from the entry day, measured to the "
                   "close. A horizon stays 'open' until enough time has elapsed; 'terminated' means the "
                   "symbol stopped trading (delisting) before it could mature."),
        ("bullet", "EXCESS return = the stock's return minus an equal-weighted benchmark built from our "
                   "own universe (split AIM vs Main, since AIM is far more volatile). This strips out "
                   "market beta so a score isn't credited for a rising tide. 'raw' is before this "
                   "adjustment."),
        ("bullet", "Score bands: 0-39 / 40-59 / 60-75 / 76-84 / 85-100 (the 76/85 cuts are where prior "
                   "analysis saw a lift).  Sentiment (llm_sentiment): positive / negative / neutral - "
                   "the DIRECTION of the news. Always split by it: score is magnitude, so pooling "
                   "positive and negative high-scorers makes them cancel out."),
        ("gap", ""),
        ("h", "KEY FINDINGS (indicative - small samples)"),
        ("bullet", "The signal is STRONG but mostly UNTRADEABLE. For positive news the open gap rises "
                   "monotonically with score (85+ band ~+7.6% median, 77% up; Spearman(score,gap) ~+0.34). "
                   "Negative news mirrors it (~-0.45; big down-gaps). Neutral ~0."),
        ("bullet", "Most of that lands in the pre-open gap you can't buy. The tradeable-from-open drift "
                   "after 08:00 is small (85+ positives ~+0.4% intraday). So the score mostly AGREES "
                   "with the market's instant open reaction rather than predicting what happens after."),
        ("bullet", "Negative news tends to over-react at the gap then bounce intraday - a possible "
                   "mean-reversion trade."),
        ("bullet", f"Matured rows per horizon: {matured}. 1m/3m are all still 'open' - not enough time "
                   "has passed. Re-run in late Aug (1m) / late Sep 2026 (3m) to fill them in."),
        ("gap", ""),
        ("h", "SHEETS IN THIS WORKBOOK"),
        ("bullet", "day1_decomposition - gap / intraday / since-news medians + gap hit-rate, by band x sentiment."),
        ("bullet", "calibration_excess - tradeable-from-open excess return (median, mean, hit%) by band x sentiment x horizon."),
        ("bullet", "coverage - how many announcements have matured vs are still open, per horizon."),
        ("bullet", "per_row - one row per (announcement, horizon): the raw underlying data behind every table."),
        ("gap", ""),
        ("h", "COLUMN GLOSSARY (per_row sheet)"),
        ("bullet", "id / symbol / company - the announcement and the stock.  seg - AIM or Main (benchmark bucket)."),
        ("bullet", "published_at - RNS timestamp (UTC).  llm_score - 0-100 impact score.  band - its score band."),
        ("bullet", "sentiment - llm_sentiment (news direction).  model - llm_model that scored it.  category - RNS type."),
        ("bullet", "entry_date / entry_open - the announcement-day trading date and its open (the entry price)."),
        ("bullet", "pre_close - previous close (pre-news reference).  status - matured / open / terminated for this horizon."),
        ("bullet", "gap_% - previous close -> entry open (pre-open reaction).  raw_% - entry open -> horizon close (tradeable)."),
        ("bullet", "excess_% - raw minus the benchmark over the same window.  since_news_% - previous close -> horizon close."),
        ("gap", ""),
        ("h", "CAVEATS"),
        ("bullet", "High score bands often have n < 15 - treat medians as directional, not precise. Means are outlier-sensitive."),
        ("bullet", "The gap edge is real but not capturable at the pre-news price; only the from-open columns are tradeable."),
        ("bullet", "Benchmark is our own equal-weighted universe, not an official FTSE index (^FTSE isn't in our price data)."),
    ]

    title_font = Font(bold=True, size=14)
    meta_font = Font(italic=True, size=9, color="666666")
    h_font = Font(bold=True, size=11, color="1F4E78")
    wrap = Alignment(wrap_text=True, vertical="top")
    indent_wrap = Alignment(wrap_text=True, vertical="top", indent=4)
    bullet_wrap = Alignment(wrap_text=True, vertical="top", indent=1)

    r = 1
    for kind, text in lines:
        if kind == "gap":
            r += 1
            continue
        cell = ws.cell(row=r, column=1, value=("- " + text) if kind == "bullet" else text)
        if kind == "title":
            cell.font = title_font
        elif kind == "meta":
            cell.font = meta_font
        elif kind == "h":
            cell.font = h_font
        cell.alignment = indent_wrap if kind == "indent" else (bullet_wrap if kind == "bullet" else wrap)
        # Roughly size the row height to the wrapped text (~135 chars/line at width 118).
        approx_lines = max(1, (len(str(text)) // 135) + 1)
        if kind not in ("title", "meta", "h"):
            ws.row_dimensions[r].height = 15 * approx_lines
        r += 1


def _export_frames(df):
    """Build the sheet DataFrames for the Excel workbook (sheet name -> frame)."""
    band_order = [f"{lo}-{hi - 1}" for lo, hi in BANDS]
    sents = ("positive", "negative", "neutral")

    # Sheet 1: day-1 reaction decomposition (matured for everything).
    d1 = df[(df["horizon"] == "1d") & df["gap"].notna()]
    dec_rows = []
    for band in band_order:
        for sent in sents:
            c = d1[(d1["band"] == band) & (d1["sentiment"] == sent)]
            if len(c) == 0:
                continue
            dec_rows.append({
                "band": band, "sentiment": sent, "n": len(c),
                "gap_median_%": round(c["gap"].median() * 100, 2),
                "intraday_median_%": round(c["raw"].median() * 100, 2),
                "since_news_median_%": round(c["since_news"].median() * 100, 2),
                "gap_hit_%": round((c["gap"] > 0).mean() * 100, 0),
            })
    day1 = pd.DataFrame(dec_rows)

    # Sheet 2: calibration — tradeable-from-open excess return by band x sent x horizon.
    mat = df[(df["status"] == "matured") & df["excess"].notna()]
    cal_rows = []
    for band in band_order:
        for sent in sents:
            for h in HORIZONS:
                c = mat[(mat["band"] == band) & (mat["sentiment"] == sent) & (mat["horizon"] == h)]
                if len(c) == 0:
                    continue
                cal_rows.append({
                    "band": band, "sentiment": sent, "horizon": h, "n": len(c),
                    "excess_median_%": round(c["excess"].median() * 100, 2),
                    "excess_mean_%": round(c["excess"].mean() * 100, 2),
                    "hit_%": round((c["excess"] > 0).mean() * 100, 0),
                })
    calibration = pd.DataFrame(cal_rows)

    # Sheet 3: maturity/coverage.
    coverage = (df.groupby(["horizon", "status"]).size().unstack(fill_value=0)
                .reindex(list(HORIZONS), fill_value=0).reset_index())

    # Sheet 4: full per-(announcement, horizon) rows. Percent columns for readability.
    per_row = df.copy()
    # Excel cannot store tz-aware datetimes — flatten published_at to naive UTC.
    if "published_at" in per_row:
        per_row["published_at"] = (
            pd.to_datetime(per_row["published_at"], utc=True).dt.tz_localize(None)
        )
    for col in ("gap", "raw", "excess", "since_news"):
        if col in per_row:
            per_row[col + "_%"] = (per_row[col] * 100).round(2)
    per_row = per_row.drop(columns=[c for c in ("gap", "raw", "excess", "since_news") if c in per_row])

    return {
        "day1_decomposition": day1,
        "calibration_excess": calibration,
        "coverage": coverage,
        "per_row": per_row,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-score", type=int, default=None, help="only analyse rows at/above this score")
    ap.add_argument("--sentiment", choices=["positive", "negative", "neutral"], help="restrict to one sentiment")
    ap.add_argument("--csv", help="also dump per-(announcement,horizon) rows to this CSV")
    ap.add_argument("--xlsx", help="also write a multi-sheet Excel workbook to this path")
    args = ap.parse_args()

    print("Loading scored A/B announcements ...")
    rows = load_scored_rows(min_score=args.min_score)
    if args.sentiment:
        rows = [r for r in rows if (r["llm_sentiment"] or "") == args.sentiment]
    print(f"  {len(rows)} scored rows")
    if not rows:
        return

    symbols = {r["symbol"] for r in rows}
    print(f"Loading price history for {len(symbols)} symbols ...")
    series = load_price_series(symbols)
    print("Building equal-weighted benchmark (AIM / Main) ...")
    bench = build_benchmark()

    global_last = max((g["date"].iloc[-1] for g in series.values()), default=pd.Timestamp.now())
    df, skipped = compute_returns(rows, series, bench, global_last)
    if skipped:
        print(f"  ({skipped} rows skipped -- no usable entry open)")

    print_report(df)

    if args.csv and not df.empty:
        df.to_csv(args.csv, index=False)
        print(f"\nPer-row results written to {args.csv}")

    if args.xlsx and not df.empty:
        frames = _export_frames(df)
        with pd.ExcelWriter(args.xlsx, engine="openpyxl") as xw:
            for sheet, frame in frames.items():
                frame.to_excel(xw, sheet_name=sheet, index=False)
            _write_explanation_sheet(xw, df)  # prepended as the first tab
        print(f"\nExcel workbook ({len(frames) + 1} sheets) written to {args.xlsx}")


if __name__ == "__main__":
    main()
