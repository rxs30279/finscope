"""DeepSeek-backed LLM ranker for RNS announcements.

Takes rows that passed the rules-based coarse filter (tier A/B) and produces a
structured score + thesis + action + risks. Context assembled per-row:
  - headline, category, tier, keyword_hits, rules score
  - investegate AI summary + full announcement body text (scraped via
    rns._fetch_summary_and_body) — the body is the primary source, the
    summary a useful but sometimes lossy lead (see docs/rns-body-context-plan.md)
  - company_metadata: sector, industry, country, ftse_index
  - ttm_financials: market_cap, P/E, dividend yield, ROIC, ROE, margins,
    growth rates, debt/equity, quality_score, risk_score
  - analyst_snapshots: consensus, buy %, upside %, # analysts, fwd EPS growth
  - price_history: 1-month and 6-month price change
  - recent RNS history for the same ticker (last 120 days)
  - prior stated guidance for the same issuer, any age (see _load_prior_guidance)
    — lets a reiterated figure be told apart from a real upgrade

Uses DeepSeek's OpenAI-compatible API. Requires DEEPSEEK_API_KEY in env.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from dotenv import load_dotenv
from psycopg2.extras import Json

from admin_auth import require_admin_token
from rns import _query, _get_pool
from quality import quality_score_from_raw

load_dotenv()

router = APIRouter(prefix="/api/rns", tags=["rns-llm"])

_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# The v4 model names run in thinking (reasoning) mode unless told otherwise, so
# every call site picks explicitly. As of 2026-07-31 the ranker runs WITHOUT
# reasoning and the showcase vet runs WITH it — see _THINKING_DEFAULT below for
# why the budget moved. The news summariser and the fwd extraction stay off.
_THINKING_ON = {"thinking": {"type": "enabled"}}
_THINKING_OFF = {"thinking": {"type": "disabled"}}

# Blanket ranker mode. Reasoning was moved off the ranker and onto the showcase
# vet on 2026-07-31, on the reasoning that the two calls have opposite evidence:
#
#   * The ranker's reasoning has never been shown to change a score for the
#     better. Model and mode switched together on 2026-07-15, so every "v4 runs
#     hotter" observation confounds the two, and the only direct A/B (10 rows,
#     2026-07-31) ran entirely on rows scoring 5-55 — nowhere near the 76 bar
#     the digest actually turns on. It cost ~90% of output tokens for that.
#   * The vet's reasoning has a documented failure it might fix: 4 of 5 v4-flash
#     vet rationales drew the sequential half/quarter comparison backwards, all
#     on the arithmetic and none on the inputs (docs/rns-gate-block-plan.md §1).
#
# So the same spend buys an unmeasured maybe on one call and a known defect on
# the other. It is not a saving — the money moves, it does not stop.
#
# This is deliberately reversible in one env var rather than a code change,
# because the thing being traded is digest quality and the revert has to be
# available at 07:00 on a morning when something looks wrong. Set RNS_THINKING=on
# to restore reasoning; _FAST_CATEGORIES then applies again as before.
#
# The `:thinking` / `:fast` suffix in llm_model means this switch writes the A/B
# that was never run: rows either side of today are directly comparable in
# rns_score_perf.py once the 1m horizon fills. Do not remove that label.
_THINKING_DEFAULT = os.environ.get("RNS_THINKING", "off").strip().lower() not in (
    "off", "0", "false", "no",
)

# Categories ranked WITHOUT reasoning. DORMANT while _THINKING_DEFAULT is off
# (every category is fast now); kept whole because it is the shape the ranker
# returns to if RNS_THINKING=on, and the measurements below cost a morning each.
#
# Thinking mode took ranking calls from
# ~6.5s to 85-172s and made reasoning ~90% of output tokens, and the whole cost
# lands inside the 07:01 -> 07:30 digest window. It is worth paying where the
# score depends on reconciling figures the announcement reports; it is not worth
# paying where the score is essentially determined by the fact itself.
#
# Only board_change qualifies, on 90 days of ranked tier A/B rows (2026-07-31):
# 136 rows, 2.8k chars average, 94 of them under 4k chars with a mean score of
# 12.0. It is the one high-volume category whose mass is genuinely routine.
#
# SIZE THE PRIZE HONESTLY before extending this list. Measured saving is ~27s of
# model time per gated row, but ranking is 12-way concurrent and board_change is
# only ~2 of ~22 rows in a morning batch, so the wall-clock saving is a handful
# of seconds and the cost saving is a couple of percent of ~$4-8/month. The
# expensive rows are the results categories, and whether reasoning earns its keep
# THERE is the open question — see the thinking-on/off A/B this list must not
# pre-empt.
#
# Categories rejected on the 90-day view, after a 30-day view made them look
# inert (they all had 0 rows over the 76 bar, which hid that they cluster at
# 65-75 just under it):
#
#     drill_results     20 rows   16 ACTIONABLE, 7 at >=65, max 75
#     product_launch    21 rows   10 actionable, 4 at >=65, max 75
#     update_statement  16 rows    9 actionable, 1 at >=65, max 75
#
# At ~20 rows per 90 days each, gating them saves nothing measurable while
# risking exactly the tradeable row this feed exists to catch — see
# docs/rns-gate-block-plan.md on misclassification cost being asymmetric. Same
# argument rules out quarterly, clinical_trial, suspension and the long tail,
# and delisting is a live digest source (6 of 10 morning rows clear 76).
#
# board_change is kept despite reaching 85 once ("Consequential Board Changes",
# 2026-07-01) because that is 1 row in 136 and _FAST_REVIEW_SCORE below is the
# tripwire for it. Note that row had NO body — it scored 85 off the summary
# alone, so a body-length heuristic would not have rescued it either.
#
# Override without a deploy by setting RNS_FAST_CATEGORIES to a comma-separated
# list (empty string restores blanket thinking).
_FAST_CATEGORIES = frozenset(
    c.strip()
    for c in os.environ.get(
        "RNS_FAST_CATEGORIES",
        "board_change",
    ).split(",")
    if c.strip()
)


def _use_thinking(category: Optional[str]) -> bool:
    """Whether this row's ranking call runs in reasoning mode.

    With RNS_THINKING off (the default since 2026-07-31) no row reasons and the
    category is irrelevant. This is checked FIRST rather than by listing every
    category in RNS_FAST_CATEGORIES, because that env route cannot express it:
    the parse strips empty entries, so NULL- and unknown-category rows would go
    on reasoning however long the list got.

    With it on, unknown and NULL categories reason: the fast path is an explicit
    opt-out list, so a category added to rns._CATEGORIES later keeps the safe
    default until someone measures it.
    """
    if not _THINKING_DEFAULT:
        return False
    return (category or "") not in _FAST_CATEGORIES

# Concurrent DeepSeek calls per ranking run. The win is in overlapping network
# waits, not in saturating the API, and a run that gets itself rate-limited
# would trade a fast batch for a batch full of errors. Set to 1 to rank serially.
#
# History, because the number has moved twice and each move had a reason that
# has since expired:
#
# 5 -> 12 on 2026-07-31. Reasoning-mode calls are far slower than the ~6.5s/call
# this was originally sized against: the recovery run that day measured 16 rows
# in 439s at 5 workers = ~137s per call. At that latency a 48-row morning takes
# 48 * 137 / 5 = 22 min against an 07:30 digest, and the morning of 07-31
# genuinely had not finished when the email went out. 12 put it at ~9 min.
#
# 12 -> 5 on 2026-08-04, because that justification died hours after it was
# written: RNS_THINKING went to "off" the same afternoon, so _use_thinking()
# now short-circuits False for every row and NOTHING in the ranker reasons. The
# 137s/call regime the 12 was sized for no longer exists; at the ~6.5s baseline
# a 48-row morning is ~62s at 5 workers, which clears the ~07:12 send with
# minutes to spare. Note that 6.5s is the PRE-reasoning figure, not a
# measurement of the current fast path — fast mode was only ever measured for
# tokens (114-156), never for latency. If a morning runs long, that untested
# assumption is the first thing to check.
#
# Why come down at all, when the batch fits either way — two costs that were
# worth paying for a 22-minute batch and are not worth paying for a 1-minute
# one. Rate limiting is the bigger one and is still untested at 12. The other is
# the DB pool: _rank_one borrows at most one connection per thread, so 12
# concurrent borrowers left only 8 spare in db.py's pool of 20, and 5 leaves 15.
#
# Prefix caching is a THIRD, much weaker reason — worth recording mainly so it
# is not rediscovered and overweighted. The ranker's system prompt is ~3,690
# tokens and byte-identical across rows, so it is one big cacheable prefix; N
# workers starting together all miss it because none has populated it yet, which
# is 25% of a 48-row morning at 12 workers versus 10% at 5. But DeepSeek's cache
# persists across requests for hours, so on a morning where the prompt has not
# changed the prefix is already warm and every worker hits from the start. The
# cold start only really bites on the first batch after a prompt edit. Worth a
# few miss-tokens, not worth a decision on its own.
#
# Cost is unaffected either way — same tokens, just sent more or less in
# parallel. Set RNS_RANK_WORKERS in the Dokploy env to override without a deploy
# (the var is otherwise unset, so this default applies); 1 ranks serially.
_RANK_WORKERS = max(1, int(os.environ.get("RNS_RANK_WORKERS", "5")))

_client = None


def _get_client():
    """Lazy-initialised OpenAI-compatible client pointed at DeepSeek."""
    global _client
    if _client is None:
        if not _DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY not set in environment")
        from openai import OpenAI

        _client = OpenAI(api_key=_DEEPSEEK_API_KEY, base_url=_DEEPSEEK_BASE_URL)
    return _client


# ── Context assembly ──────────────────────────────────────────────────────────


def _load_candidate(row_id: int) -> Optional[dict]:
    """Load the announcement plus enrichment (company, fundamentals, analysts).

    If market_cap is missing from ttm_financials (e.g. the company isn't in the
    financials DB yet), falls back to a Yahoo Finance lookup via the shared
    market-cap cache in rns.py.
    """
    rows = _query(
        """
        SELECT a.id, a.published_at, a.wire, a.ticker, a.symbol, a.company_name,
               a.headline, a.headline_slug, a.url, a.tier, a.category,
               a.keyword_hits, a.score, a.summary, a.body, a.body_is_stub,
               m.sector, m.industry, m.country, m.ftse_index,
               -- Reporting currency of the accounts, needed to convert net_debt
               -- before it can be compared against a GBP market cap (see the
               -- leverage block in _build_messages).
               m.financial_currency,
               t.market_cap,
               CASE WHEN t.price_to_earnings > 999 OR t.price_to_earnings <= 0
                    THEN NULL ELSE t.price_to_earnings END AS price_to_earnings,
               CASE WHEN t.period_end_price > 0 AND t.dividends_per_share > 0
                    THEN t.dividends_per_share / t.period_end_price
                    ELSE NULL END AS dividend_yield,
               t.price_to_book, t.price_to_sales,
               t.roic, t.roe, t.roce, t.operating_margin, t.fcf_margin,
               t.revenue_growth, t.eps_cagr_10,
               t.debt_to_equity, t.current_ratio,
               t.net_debt, t.ebitda,
               t.gross_margin, t.net_income_margin,
               t.gross_margin_median, t.operating_margin_median,
               t.net_margin_median, t.roe_median, t.roic_median,
               t.revenue, t.fcf, t.period_end_price,
               pm.peer_margin_median,
               s.consensus, s.buy_pct, s.upside_pct, s.total_analysts,
               s.eps_growth_next_yr
        FROM rns_announcements a
        LEFT JOIN company_metadata m ON m.symbol = a.symbol
        LEFT JOIN LATERAL (
            SELECT market_cap, price_to_earnings, dividends_per_share, period_end_price,
                   price_to_book, price_to_sales,
                   roic, roe, roce, operating_margin, fcf_margin,
                   revenue_growth, eps_cagr_10,
                   debt_to_equity, current_ratio,
                   net_debt, ebitda,
                   gross_margin, net_income_margin,
                   gross_margin_median, operating_margin_median,
                   net_margin_median, roe_median, roic_median,
                   revenue, fcf
            FROM ttm_financials
            WHERE company_symbol = a.symbol
            ORDER BY period_end_date DESC NULLS LAST
            LIMIT 1
        ) t ON TRUE
        -- True industry-peer margin median for the WEAK MARGINS flag — NULL
        -- when the industry has <5 usable names (min group size kept in sync
        -- with PEER_MARGIN_MIN_GROUP in showcase.py). The stored
        -- t.net_margin_median above is the company's OWN multi-year median
        -- (consistency signal for the quality score), not a peer comparison.
        LEFT JOIN LATERAL (
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t2.net_income_margin)
                       AS peer_margin_median
            FROM ttm_financials t2
            JOIN company_metadata m2 ON m2.symbol = t2.company_symbol
            WHERE m2.industry = m.industry
              AND t2.net_income_margin IS NOT NULL
            HAVING COUNT(*) >= 5
        ) pm ON TRUE
        LEFT JOIN LATERAL (
            SELECT consensus, buy_pct, upside_pct, total_analysts,
                   eps_growth_next_yr
            FROM analyst_snapshots
            WHERE symbol = a.symbol
            ORDER BY snapshot_date DESC
            LIMIT 1
        ) s ON TRUE
        WHERE a.id = %s
    """,
        (row_id,),
    )

    cand = rows[0] if rows else None
    if cand is None:
        return None

    # If market_cap is missing from the DB, try a Yahoo Finance fallback
    if cand.get("market_cap") is None:
        symbol = cand.get("symbol")
        ticker = cand.get("ticker")
        if symbol or ticker:
            # Build the Yahoo Finance symbol
            if symbol:
                yahoo_sym = symbol
            else:
                yahoo_sym = f"{ticker.rstrip('.')}.L"
            # Use the shared market-cap fetcher from rns.py
            from rns import _fetch_market_caps_batch

            mc_map = _fetch_market_caps_batch([yahoo_sym])
            if yahoo_sym in mc_map:
                cand["market_cap"] = mc_map[yahoo_sym]

    return cand


def _load_price_change(symbol: Optional[str]) -> dict:
    """Compute 1-month and 6-month price changes, plus latest close."""
    if not symbol:
        return {}
    rows = _query(
        """
        SELECT
            (SELECT close FROM price_history WHERE symbol = %s
             ORDER BY date DESC LIMIT 1) AS latest,
            (SELECT close FROM price_history WHERE symbol = %s
             AND date <= CURRENT_DATE - INTERVAL '30 days'
             ORDER BY date DESC LIMIT 1) AS m1,
            (SELECT close FROM price_history WHERE symbol = %s
             AND date <= CURRENT_DATE - INTERVAL '180 days'
             ORDER BY date DESC LIMIT 1) AS m6
    """,
        (symbol, symbol, symbol),
    )
    if not rows:
        return {}
    r = rows[0]
    out = {"latest": r.get("latest")}
    if r.get("latest") and r.get("m1") and r["m1"] > 0:
        out["chg_1m"] = (r["latest"] - r["m1"]) / r["m1"]
    if r.get("latest") and r.get("m6") and r["m6"] > 0:
        out["chg_6m"] = (r["latest"] - r["m6"]) / r["m6"]
    return out


def _load_history(symbol: Optional[str], limit: int = 10) -> list[dict]:
    """Last `limit` RNS items for this issuer, excluding routine noise.

    120 days (not 60) so a half-year reporting cadence — Q1 in May, H1 in
    July, ~70 days apart — isn't excluded by construction. RNS ingest only
    began 2026-06-29, so this is a no-op until the table fills past 60 days
    deep; it becomes correct automatically as history accrues rather than
    needing a second change later.
    """
    if not symbol:
        return []
    return _query(
        """
        SELECT published_at, tier, category, headline
        FROM rns_announcements
        WHERE symbol = %s
          AND tier IN ('A', 'B')
          AND published_at >= NOW() - INTERVAL '120 days'
        ORDER BY published_at DESC
        LIMIT %s
    """,
        (symbol, limit),
    )


def _load_prior_guidance(symbol: Optional[str], exclude_id: Optional[int] = None) -> Optional[dict]:
    """Most recent prior announcement for this issuer that had an extracted
    guidance figure (see _save_ranking / guidance_metric), regardless of age —
    a reiterated guidance figure is only reiterated for as long as the company
    keeps saying it, which isn't bounded by the 120-day history window above.

    Returns None until an issuer has a second captured announcement; expect
    that to be rare for months given ingest only began 2026-06-29 (see
    docs/rns-body-context-plan.md Phase 3) and fill in as coverage grows.
    """
    if not symbol:
        return None
    rows = _query(
        """
        SELECT published_at, guidance_metric, guidance_value, guidance_period
        FROM rns_announcements
        WHERE symbol = %s
          AND guidance_metric IS NOT NULL
          AND id != %s
        ORDER BY published_at DESC
        LIMIT 1
    """,
        (symbol, exclude_id or 0),
    )
    return rows[0] if rows else None


def _format_market_cap(mc: Optional[float], ccy: str = "£") -> str:
    """Money format. `ccy` defaults to sterling because market_cap really is
    GBP — pass the reporting currency when formatting an unconverted figure
    from the accounts, which for 138 of 755 companies is NOT sterling."""
    if mc is None:
        return "unknown"
    if mc >= 1e9:
        return f"{ccy}{mc/1e9:.1f}bn"
    if mc >= 1e6:
        return f"{ccy}{mc/1e6:.0f}m"
    return f"{ccy}{mc:.0f}"


def _format_net_debt(nd: Optional[float], ccy: str = "£") -> str:
    """Sign-aware money format; negative net debt is surfaced as net cash."""
    if nd is None:
        return "n/a"
    if nd < 0:
        return f"{_format_market_cap(-nd, ccy)} net cash"
    return _format_market_cap(nd, ccy)


def _net_debt_line(raw: Optional[float], gbp: Optional[float], rep_ccy: str) -> str:
    """Net debt for the prompt, in a currency the label actually matches.

    The £ sign used to be hardcoded, so a dollar filer's net debt was printed
    as "£4.4bn" when it was $4.4bn — the same mislabel fixed in the vet prompt
    by c1d08f1, still live here until 2026-08-06. Prefer the GBP-converted
    figure so it agrees with the net-debt/mkt-cap ratio printed beside it; with
    no rate, show the real currency rather than a wrong symbol.
    """
    if raw is None:
        return "n/a"
    if gbp is not None:
        return _format_net_debt(gbp)
    return f"{_format_net_debt(raw, '')} {rep_ccy}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:+.1f}%"


def _fmt_num(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}"


# ── Quality & risk helpers ─────────────────────────────────────────────────
# The quality score used to be a hand-ported copy of main.py's, kept in sync by
# hand and drifting anyway: it summed the ten legs against a RAW ttm_financials
# row, so a bank was graded on its meaningless FCF margin (the NatWest +734%
# case) while the screener blanked that field and then counted the blank as a
# failure. Same company, two different scores. Both now route through
# quality.py; quality_score_from_raw applies the model blanking to a COPY, so
# the figures printed into the prompt below are untouched.


def _quality_score(r: dict) -> Optional[int]:
    """Quality score 0-10 for an unscrubbed ttm_financials row.

    None when too few legs survive to be meaningful (out-of-universe tickers
    with no financials, closed-end funds) — a 0 there would read as "failed
    every check" rather than "not measured", and the prompt renders None as
    n/a with an explicit instruction not to penalise the missing data.

    Printed into the prompt for context only. It no longer gates any flag:
    five of its ten legs are self-comparisons, so it is half a trend measure —
    see the note above quality_flag in _build_messages.
    """
    return quality_score_from_raw(r)


def _risk_score(cand: dict) -> Optional[int]:
    """Simple risk score 1-10 using debt/equity + current ratio + FCF margin.

    Lower = safer. Uses only ttm_financials data (no Altman Z or vol needed).
    1-3: low risk, 4-6: moderate, 7-10: high risk.
    """
    de = cand.get("debt_to_equity")
    cr = cand.get("current_ratio")
    fcfm = cand.get("fcf_margin")

    components = 0
    total = 0.0

    # Debt/equity component (0-10 scale)
    if de is not None and de > 0:
        components += 1
        if de < 0.3:
            total += 1  # very low debt
        elif de < 0.6:
            total += 2
        elif de < 1.0:
            total += 3
        elif de < 2.0:
            total += 5
        elif de < 4.0:
            total += 7
        else:
            total += 10  # dangerously leveraged

    # Current ratio component (0-10 scale)
    if cr is not None and cr > 0:
        components += 1
        if cr > 2.5:
            total += 1  # very liquid
        elif cr > 1.5:
            total += 2
        elif cr > 1.0:
            total += 4
        elif cr > 0.5:
            total += 7
        else:
            total += 10  # distress

    # FCF margin component (0-10 scale)
    if fcfm is not None:
        components += 1
        if fcfm > 0.10:
            total += 1  # strong FCF
        elif fcfm > 0.05:
            total += 2
        elif fcfm > 0.0:
            total += 4
        elif fcfm > -0.10:
            total += 7
        else:
            total += 10  # burning cash

    if components == 0:
        return None
    return max(1, min(10, round(total / components)))


# The output schema. Byte-identical on every row, so it lives in the SYSTEM
# message where DeepSeek's prefix cache can actually reach it — see
# docs/rns-earnings-quality-plan.md Phase 0. Sitting at the tail of the user
# message (its home until 2026-07-29) it followed ~14k chars of per-row body and
# was therefore billed at the cache-miss rate on every single call: the stable
# prefix was 3,742 of a 24,368-char prompt, 15%. Moved here it is ~36%.
#
# The cost of the move is distance from the point of use, and this project's
# whole experience is that the model holds an instruction poorly across a long
# body. So the ordering constraint — the one load-bearing instruction, because
# enumerate-then-score is what stops the model rationalising a number it has
# already picked — is ALSO restated at the tail of the user message
# (_SCHEMA_POINTER). Do not "tidy" that duplication away.
_JSON_SCHEMA_BLOCK = """

Produce a JSON object with these fields exactly, IN THIS ORDER — fill in
guidance_checks and earnings_quality first and let them constrain the score,
do not pick a score and then justify it:
  guidance_checks  array, one entry for EVERY forward-looking guidance
                   statement in the announcement text — every period, not
                   just the most prominent or the most recently mentioned
                   one. A single paragraph often carries two (e.g. a
                   reiterated near-year figure and a new out-year comment);
                   both get an entry. Empty array if the announcement makes
                   no forward statement. Each entry:
                     metric          e.g. "Adjusted Operating Profit"
                     period          e.g. "FY2026"
                     guided_value    as printed, e.g. "> £40m" or
                                     "to exceed current market expectations"
                     consensus_value the company-compiled consensus for that
                                     SAME period if the announcement prints
                                     one, else null — match on period, do not
                                     borrow another year's figure
                     vs_prior        one of: "raised", "reiterated",
                                     "lowered", "new", "unknown"
                     vs_consensus    one of: "above", "in_line", "below",
                                     "no_consensus_stated"
                   These two are INDEPENDENT and must both be filled in. A
                   figure can be reiterated and below consensus at the same
                   time (the company's expectation is unchanged, but
                   consensus has moved past it since) — that combination is
                   the single most important thing this field exists to
                   catch, so never let one of the two answers stand in for
                   the other.
                     vs_prior is about the company's own EXPECTATION, not
                   the digits: if the announcement says it is upgrading,
                   raising or narrowing-upward its outlook, that is
                   "raised" even when the printed figure is a pre-existing
                   multi-year range being restated and no new number is
                   given. Take the company at its word on direction. Use
                   "new" for first-time guidance and "unknown" when there
                   is nothing to compare against.
                     vs_consensus is ONLY about a consensus figure printed
                   in this announcement. "no_consensus_stated" is the
                   common case and carries no information either way — most
                   announcements print no consensus footnote. It is never
                   evidence that guidance fails to beat expectations.
  earnings_quality array, one entry for EVERY material income or charge line
                   the announcement itself quantifies — what the reported
                   result is MADE OF, as distinct from the forward guidance
                   above. Empty array if it quantifies none.
                     ALWAYS INCLUDE TOP-LINE REVENUE/TURNOVER. On any
                   results or trading-update announcement, emit an entry for
                   the headline revenue/turnover figure with its prior-period
                   comparator even when nothing about it is remarkable and
                   the story is about a different line (margin, one-off,
                   profit) — a downstream sequential-trend check needs this
                   figure on every row, not just the ones where revenue is
                   the story. Still governed by the rules below: no prior
                   figure invented if the announcement does not print one.
                     RATES COUNT AS LINES. Where the announcement prints a
                   normalised rate next to an absolute figure — a bank's loan
                   loss rate or cost of risk in bps, an impairment ratio, a
                   margin — that rate gets its OWN entry with its own
                   prior_value, in ADDITION to the entry for the absolute
                   amount. Never emit only the absolute one. A charge in £bn
                   grows with the size of the book, so it says little on its
                   own; the rate is the figure that shows whether anything
                   actually deteriorated, which is why the company reports it.
                     A ONE-OFF IS RARELY PRINTED NEXT TO THE LINE IT
                   FLATTERS. Insurers, banks and any issuer reporting on an
                   adjusted basis disclose the non-repeating part somewhere
                   else — a starred footnote under a ratio table ("*Prior year
                   tax credit of $64.5m has not been annualised"), a
                   reserve-development or notable-items note, an
                   alternative-performance-measure reconciliation — often
                   thousands of words after the headline figure it explains.
                   Read the whole announcement for these, not just the text
                   around each line. Each one must appear in the
                   one_off_named of THE RESULT LINE IT FLATTERS — the headline
                   figure a reader would otherwise take at face value.
                   Worked example: an insurer's highlights print "Adjusted
                   operating profit before tax $331.0m" and a note twenty
                   paragraphs later reads "Prior-year development recognised
                   for the period is favorable and amounts to $173.7
                   million". The required entry is item "Adjusted operating
                   profit before tax", value "$331.0m", one_off_named
                   "favourable prior-year development of $173.7 million".
                     Many such figures are ALSO reported metrics in their own
                   right, and you may keep that separate entry
                   ("Prior-year development", $173.7m) — but with its
                   one_off_named null, and never as a substitute for naming it
                   on the line it flatters. Listing the one-off as a line of
                   its own and stopping there is the most common way to get
                   this wrong: it records that the figure exists while hiding
                   the only thing worth knowing, which is how much of the
                   headline it accounts for. Whenever an entry's value and its
                   one_off_named are the same amount, the attribution you
                   actually owe is on some OTHER line.
                     A PRINTED "EXCLUDING" PAIR IS A NAMED ONE-OFF. When the
                   announcement gives both a headline figure and a version of
                   it excluding something — "total income £8,862m" and "total
                   income excluding notable items £8,672m", reported vs
                   adjusted vs underlying — the company has itself named what
                   the difference is made of. Name it on the HEADLINE entry
                   (one_off_named "notable items of £190m"), quantified with
                   the figure the announcement gives for it. Do not treat
                   emitting the excluding-line, or an entry for the notable
                   items themselves, as having discharged this — those record
                   that an adjustment exists without ever saying it is what
                   the headline growth is made of.
                     Where a one-off affects both an absolute figure and a
                   ratio, attach it to the ABSOLUTE figure — a percentage
                   cannot show how much of itself the one-off accounts for.
                   The ratio still gets its own entry, without the one-off.
                     What has to be named in the announcement is the
                   CONTRIBUTOR, not the connection: you may join a note to the
                   line it plainly qualifies, but you still may not invent a
                   one-off nobody named.
                     KEEP IT TO THE MATERIAL LINES — at most about 8 entries.
                   Material means the line moves the result or changes how the
                   result should be read, not merely that a number appears in
                   the text. Do not pad the array with every quantified figure
                   in the announcement. Where you have to choose, keep, in this
                   order: (a) any line carrying a named one-off, (b) any
                   normalised rate that has a prior comparator, (c) the largest
                   income and charge lines. Drop routine detail before you drop
                   any of those.
                   Each entry:
                     item          the line as printed, e.g. "Credit
                                   impairment charges", "Loan loss rate
                                   (LLR)", "USCB income"
                     period        which period this figure covers, e.g.
                                   "H1 2026" or "Q2 2026". Mandatory. The same
                                   metric is routinely printed for both a half
                                   and a quarter within a few lines of each
                                   other, so a figure without its period is
                                   worse than useless — never merge two
                                   periods into one entry.
                     value         as printed, e.g. "£1.4bn", "62bps",
                                   "increased 38%"
                     prior_value   the comparator the announcement prints for
                                   the SAME line and SAME period a year
                                   earlier, as printed (e.g. "£1.1bn",
                                   "52bps"), else null
                     kind          "income" or "cost_or_charge"
                     one_off_named the non-repeating contributor the
                                   announcement ITSELF names as affecting this
                                   line, quoted as printed — whether named
                                   inline ("c.£225m gain from the sale of the
                                   AA co-branded cards portfolio") or in a
                                   footnote or note ("favourable prior-year
                                   development of $173.7 million"), else null.
                                   Copy the company's own words;
                                   do not judge for yourself whether an item
                                   recurs, and never infer a one-off the
                                   announcement does not name.
                                   Direction-neutral: a one-off charge that
                                   flatters the underlying trend gets an entry
                                   exactly as a one-off gain does.
  score            integer 0-100; price-impact likelihood × magnitude.
                   Weigh every guidance_checks entry, not just the most
                   favourable one. In particular:
                   - reiterated + below consensus is a NEGATIVE, however
                     positively the announcement phrases it, and it caps how
                     positive the whole item can be even when another entry
                     is above consensus;
                   - raised + no_consensus_stated is still a genuine
                     catalyst — do not mark an upgrade down merely because
                     no consensus figure was printed;
                   - reiterated + no_consensus_stated is neutral: no new
                     information, so no catalyst.
                   Weigh earnings_quality too: income growth carrying a named
                   one-off contributor is worth less than its headline rate,
                   and a charge or loss RATE rising year on year is a negative
                   however positively the announcement is phrased.
                   Absent content scores DOWN, not up. Where the body reads
                   "(body unavailable ...)" or "(not available)" the item is a
                   filing notice pointing at a document you cannot see: score
                   the headline alone and keep it near the noise floor.
                   Uncertainty is not a reason to hedge upward — "could be
                   significant if the figures differ" is true of every unread
                   document ever filed, so it distinguishes nothing. A results
                   headline whose figures you cannot read is a filing notice,
                   not a result. This is the OPPOSITE of the quality n/a rule:
                   missing financial COVERAGE must not be penalised, missing
                   announcement CONTENT must be.
                   The number must agree with the words. If the thesis calls
                   the item routine, or says it is unlikely to move the share
                   price, or action is "ignore", the score belongs below 20 —
                   never write a dismissive thesis and attach a mid-range
                   score to it.
  confidence       one of: "high", "medium", "low"
  thesis           one sentence: why this matters (or why it doesn't)
  action           one of: "watch", "research", "ignore"
  risks            one sentence: what would invalidate the thesis
  sentiment        one of: "positive", "negative", "neutral" — the direction
                   of this news for existing shareholders, independent of
                   size/impact
  guidance_metric  one entry from guidance_checks, echoed here (e.g.
                   "FY2026 Adjusted Operating Profit"), or null if
                   guidance_checks is empty. This is the one figure carried
                   forward and shown against the issuer's NEXT announcement,
                   so it must be comparable: pick the entry with a hard
                   number covering the nearest period. Only fall back to a
                   qualitative entry ("ahead of expectations", "in line") if
                   no entry has a number at all — such a value is useless
                   for the later comparison.
  guidance_value   that entry's figure/range/threshold as text (e.g.
                   "> £40m"), or null
  guidance_period  that entry's period (e.g. "FY2026"), or null

Return JSON only — no preamble, no code fence."""

# Tail of the user message. Restates only the ordering constraint, so the
# instruction that must survive ~14k chars of body is the last thing read.
_SCHEMA_POINTER = """Produce the JSON object exactly as specified in the system instructions.
Fill in guidance_checks and earnings_quality FIRST and let them constrain the
score — do not pick a score and then justify it."""


def _build_messages(
    cand: dict,
    history: list[dict],
    price: dict,
    prior_guidance: Optional[dict] = None,
) -> list[dict]:
    """Construct the DeepSeek chat messages. Forces JSON output via prompt."""
    system = (
        "You rank UK stock announcements (RNS feed) on how likely they are to "
        "move the share price materially. Be sceptical — most announcements are "
        "noise. An item is only 'high-impact' if it changes the investment case "
        "(earnings, M&A, strategy, solvency). Routine updates are low-impact. "
        "Always weigh company size: a £50m contract is transformational for a "
        "£100m microcap, trivial for a FTSE100. That size discount is for "
        "routine operational news — a contract win, a small buyback, a minor "
        "product launch. It does NOT apply to genuine consensus-moving events: "
        "a results beat or miss, a raised or lowered full-year outlook, or any "
        "news that surprises versus what the market priced in is a real "
        "catalyst at ANY market cap, FTSE100 included — don't compress it into "
        "a low score just because the company is large. Use positioning context "
        "too — news that contradicts analyst consensus has more surprise; news "
        "that confirms a stock that's already rallied or fallen sharply is "
        "largely priced in. "
        "Scrutinise the balance sheet: we avoid highly-indebted companies. Always "
        "weigh net debt against both market cap and profits. Net debt above 3x "
        "EBITDA is a serious red flag, and net debt that exceeds the market cap "
        "means equity holders sit behind a heavy debt load — in both cases treat "
        "the company with caution, call it out in the risks, and hold the score "
        "down unless the announcement directly and materially de-levers the "
        "balance sheet. "
        "Weigh business quality too. A net margin "
        "below the industry median (judge margins peer-relative — a thin margin "
        "is normal in some industries and fine when capital returns are strong; "
        "below the industry's own norm with weak returns is the red flag, "
        "loss-making doubly so), or a deteriorating margin / EPS trend means the "
        "underlying business is weak and converts good news into shareholder "
        "value poorly. For a positive catalyst on such a low-quality name, temper "
        "the score and flag the fragile fundamentals in the risks rather than "
        "taking the upgrade at face value. A quality score of n/a means the "
        "company is outside our financials coverage, NOT that quality is low — "
        "judge business quality from the announcement text itself and do not "
        "penalise the score for the missing data. "
        "The Quality figure is marked '(vs own history)' because that is what "
        "it measures: the company against its OWN past returns and margins. A "
        "low reading means this period sits below the company's recent best, "
        "NOT that the business is weak — a strong company coming off a peak "
        "year scores low on it. Never cite it as evidence of weak fundamentals. "
        "Judge business quality from the peer-relative margin line, the "
        "leverage line and the announcement itself. "
        "When the announcement text states a company-compiled analyst "
        "consensus figure, compare the guided figure against it and say which "
        "side of consensus the guidance falls on — reiterated guidance "
        "('continues to expect') against a consensus that has since moved "
        "past it is not an upgrade even if the same number beat consensus "
        "months ago. If 'Prior guidance from this issuer' below shows the "
        "same figure as today's announcement, treat today's as a reiteration, "
        "not new news, regardless of how the headline phrases it. "
        "One announcement often carries several guidance statements covering "
        "different periods, sometimes in the same sentence — a reiterated "
        "near-year figure alongside a new out-year comment. Enumerate every "
        "one of them in guidance_checks before you choose a score, scoring "
        "each on BOTH axes: changed-or-not versus the company's own prior "
        "guidance, and above-or-below any consensus printed for that same "
        "period. Those are different questions and a figure can be "
        "unchanged and below consensus at once. The most eye-catching "
        "statement is usually the vaguest one (an out-year 'ahead of "
        "expectations' with no figure attached); it must not mask a "
        "near-year figure that consensus has already overtaken. "
        "Multi-year targets reaffirmed rather than raised, when current "
        "performance already exceeds them, can be a negative signal — the "
        "market may have wanted an upgrade. Weigh this one lightly against "
        "the rest of the analysis; it is a market-psychology judgement, not a "
        "reading-comprehension one. "
        "Judge the composition of the reported numbers, not only the outlook. "
        "Headline growth the announcement itself attributes in part to a "
        "disposal gain, an acquisition or another named non-repeating item is "
        "worth less than the headline rate implies, and a charge or loss RATE "
        "that has risen year on year is a deterioration however positively the "
        "announcement frames the result. Enumerate those lines in "
        "earnings_quality before you choose a score, copying the company's own "
        "words rather than deciding for yourself what recurs. "
        "Return STRICT JSON only."
        + _JSON_SCHEMA_BLOCK
    )

    hist_lines = (
        "\n".join(
            f"  - {h['published_at'].strftime('%Y-%m-%d')}  [{h['tier']}] "
            f"{h['category'] or '?'}: {h['headline']}"
            for h in history
        )
        or "  (no prior tier A/B items in last 60 days)"
    )

    pe = cand.get("price_to_earnings")
    dy = cand.get("dividend_yield")
    consensus = cand.get("consensus")
    buy_pct = cand.get("buy_pct")
    upside = cand.get("upside_pct")
    n_analysts = cand.get("total_analysts")

    valuation_line = f"P/E {_fmt_num(pe)}, " f"div yield {_fmt_pct(dy)}"
    if consensus or n_analysts:
        analyst_line = (
            f"{consensus or '?'} (buy {_fmt_pct(buy_pct/100 if buy_pct is not None else None)}, "
            f"upside {_fmt_pct(upside/100 if upside is not None else None)}, "
            f"{n_analysts or 0} analysts)"
        )
    else:
        analyst_line = "(no analyst coverage)"

    price_line = (
        f"1m {_fmt_pct(price.get('chg_1m'))}, " f"6m {_fmt_pct(price.get('chg_6m'))}"
    )

    # ── Enriched financial health section ──────────────────────────────────
    qs = _quality_score(cand)
    rs = _risk_score(cand)

    roic = cand.get("roic")
    roe = cand.get("roe")
    op_margin = cand.get("operating_margin")
    fcf_margin = cand.get("fcf_margin")
    rev_growth = cand.get("revenue_growth")
    eps_cagr = cand.get("eps_cagr_10")
    de = cand.get("debt_to_equity")
    cr = cand.get("current_ratio")
    pb = cand.get("price_to_book")
    ps = cand.get("price_to_sales")
    fwd_eps = cand.get("eps_growth_next_yr")

    # ── Leverage: net debt vs market cap and profits ────────────────────────
    # We avoid highly-indebted companies. Net debt / EBITDA above ~3x is a red
    # flag, and net debt that dwarfs the market cap means equity holders sit
    # behind a large debt load (enterprise value is mostly debt).
    #
    # CURRENCY: net_debt and ebitda are both in the REPORTING currency, so
    # net debt / EBITDA needs no conversion. market_cap is in GBP, so net debt
    # / market cap does — without it every dollar filer read as ~1.27x more
    # indebted than it is, and Harbour Energy's $4.42bn net debt tripped the
    # flag against a £3.66bn cap when the true ratio is below 1 (2026-08-06).
    # A missing rate makes the ratio None, which drops the flag rather than
    # guessing it — this only ever tempers a score, so silence is the safe
    # failure. Mirrors the same fix in showcase.py's selection SQL.
    net_debt = cand.get("net_debt")
    ebitda = cand.get("ebitda")
    mcap = cand.get("market_cap")

    from showcase import _fx_to_gbp  # deferred — avoids a circular import

    rep_ccy = (cand.get("financial_currency") or "GBP").upper().strip() or "GBP"
    fx = _fx_to_gbp().get(rep_ccy)
    net_debt_gbp = (net_debt * fx) if (net_debt is not None and fx) else None

    nd_to_mktcap = (
        (net_debt_gbp / mcap) if (net_debt_gbp is not None and mcap and mcap > 0) else None
    )
    nd_to_ebitda = (net_debt / ebitda) if (net_debt is not None and ebitda and ebitda > 0) else None
    leverage_flag = ""
    if nd_to_ebitda is not None and nd_to_ebitda > 3:
        leverage_flag = "  !! HIGH LEVERAGE (net debt > 3x profit)"
    elif nd_to_mktcap is not None and nd_to_mktcap > 1:
        leverage_flag = "  !! net debt exceeds market cap"

    # ── Quality: weak or below-peer-margin businesses convert good news ──────
    # poorly. Margins are judged against the industry-peer median — thin-margin
    # industries aren't penalised wholesale, but a name below its peers (or
    # loss-making) is fragile and a positive catalyst deserves a tempered score.
    # Escape hatch: profitable + strong ROCE passes without the flag — a
    # low-margin/high-ROCE model (reseller, distributor) is structure, not
    # fragility. Floors (0.02 fallback, 0.15 ROCE) kept in sync with the
    # showcase selection gates in showcase.py.
    #
    # There used to be a second, PRECEDING branch here firing
    # "!! LOW QUALITY (weak fundamentals)" on quality_score <= 3. It was removed
    # 2026-07-30: five of that score's ten legs compare a company against its
    # OWN historical median (quality.py quality_legs), so it is half a *trend*
    # measure, and a sound business having a below-peak year read as "weak
    # fundamentals". Greggs — 19.5% ROE, 16.5% ROCE, net margin above its
    # industry median, £46m NET CASH — scored 3/10 and was branded weak; so
    # were Shell, JD Sports, B&M, Renishaw and Persimmon (39 names, 259 -> 220
    # flagged of 531). Because it sat in front of the margin test as an `if`
    # with this as its `elif`, it also SHADOWED the correct, industry-relative
    # judgement below for exactly those names.
    #
    # Do not "restore" it by thresholding quality_score again, and do not push
    # the fix down into quality.py — that score is user-facing in the screener
    # column and filter, the company ScoreStrip, /most-shorted, showcase and
    # news, and it is doing its documented job there. The weakness test that
    # belongs in a *ranker* prompt is the peer-relative one below.
    nim = cand.get("net_income_margin")
    nim_median = cand.get("peer_margin_median")
    roce = cand.get("roce")
    margin_floor = max(0.0, nim_median) if nim_median is not None else 0.02
    margin_ok = (
        nim is None
        or nim >= margin_floor
        or (nim > 0 and roce is not None and roce >= 0.15)
    )
    quality_flag = ""
    if not margin_ok:
        quality_flag = (
            "  !! WEAK MARGINS (loss-making)" if nim < 0
            else "  !! WEAK MARGINS (below industry median)"
        )

    # Labelled with what it actually measures. The bare "3/10" invited the model
    # to read a half-trend score as a verdict on the business — which is exactly
    # what it did on Greggs, quoting "low quality score indicates weak
    # fundamentals" straight back into llm_risks. Suffix only when there IS a
    # score; "n/a (vs own history)" would be nonsense.
    quality_str = f"{qs}/10 (vs own history)" if qs is not None else "n/a"
    risk_str = f"{rs}/10" if rs is not None else "n/a"
    risk_label = ""
    if rs is not None:
        if rs <= 3:
            risk_label = " (low risk)"
        elif rs <= 6:
            risk_label = " (moderate)"
        else:
            risk_label = " (high risk)"

    health_lines = (
        f"  ROIC:         {_fmt_pct(roic)}   ROE: {_fmt_pct(roe)}\n"
        f"  Op. margin:   {_fmt_pct(op_margin)}   FCF margin: {_fmt_pct(fcf_margin)}\n"
        f"  Revenue gr:   {_fmt_pct(rev_growth)}   EPS CAGR 10Y: {_fmt_pct(eps_cagr)}\n"
        f"  D/E:          {_fmt_num(de, 2)}   Current ratio: {_fmt_num(cr, 2)}\n"
        f"  Net debt:     {_net_debt_line(net_debt, net_debt_gbp, rep_ccy)}"
        f"   Net debt/EBITDA: {_fmt_num(nd_to_ebitda, 1)}x"
        f"   Net debt/mkt cap: {_fmt_num(nd_to_mktcap, 1)}x{leverage_flag}\n"
        f"  P/B:          {_fmt_num(pb, 2)}x   P/S: {_fmt_num(ps, 2)}x\n"
        f"  Net margin:   {_fmt_pct(nim)} (industry median {_fmt_pct(nim_median)})"
        f"   Gross margin: {_fmt_pct(cand.get('gross_margin'))}\n"
        f"  Quality:      {quality_str}   Risk: {risk_str}{risk_label}{quality_flag}"
    )

    if fwd_eps is not None:
        health_lines += (
            f"\n  Fwd EPS gr:   {_fmt_pct(fwd_eps)}  ({n_analysts or 0} analysts)"
        )

    if cand.get("body_is_stub"):
        body_text = "(body unavailable — announcement links to an external document)"
    else:
        body_text = cand.get("body") or "(not available)"

    if prior_guidance:
        pg_period = prior_guidance.get("guidance_period") or "?"
        pg_metric = prior_guidance.get("guidance_metric") or "?"
        pg_value = prior_guidance.get("guidance_value") or "?"
        pg_date = prior_guidance["published_at"].strftime("%Y-%m-%d")
        guidance_line = f"  {pg_date}  {pg_period} {pg_metric}: {pg_value}"
    else:
        guidance_line = "  (none captured yet for this issuer)"

    user = f"""Announcement
  Ticker:       {cand.get('ticker') or '?'}
  Company:      {cand.get('company_name') or '?'}
  Sector:       {cand.get('sector') or '?'}
  Industry:     {cand.get('industry') or '?'}
  Country:      {cand.get('country') or '?'}
  FTSE index:   {cand.get('ftse_index') or '?'}
  Market cap:   {_format_market_cap(cand.get('market_cap'))}
  Published:    {cand['published_at'].strftime('%Y-%m-%d %H:%M')}
  Wire:         {cand.get('wire')}
  Headline:     {cand.get('headline')}
  Rules tier:   {cand.get('tier')}  (category={cand.get('category')}, rules_score={cand.get('score')})
  Keyword hits: {', '.join(cand.get('keyword_hits') or []) or '(none)'}

Market context
  Valuation:    {valuation_line}
  Analysts:     {analyst_line}
  Price change: {price_line}

Financial health
{health_lines}

Investegate AI summary
{cand.get('summary') or '(not available)'}

Announcement text (verbatim, may be truncated) — this is the primary source;
the summary above is a useful lead but can omit or misread material detail
  {body_text}

Prior guidance from this issuer (most recent captured; may be from any date)
{guidance_line}

Recent issuer RNS history (tier A/B only, last 120 days)
{hist_lines}

{_SCHEMA_POINTER}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── LLM call + persistence ────────────────────────────────────────────────────


def _log_cache_usage(tag: str, resp) -> None:
    """Print DeepSeek prefix-cache hit/miss token counts for one response.

    The fields are DeepSeek extensions to the OpenAI usage shape, so they are
    read defensively — absent fields log as n/a rather than raising.
    """
    usage = getattr(resp, "usage", None)
    hit = getattr(usage, "prompt_cache_hit_tokens", None)
    miss = getattr(usage, "prompt_cache_miss_tokens", None)
    # Completion tokens are logged alongside the cache counters because the
    # completion budget is the side that actually broke: earnings_quality grew
    # the answer past a max_tokens sized for the old one, and with only cache
    # counters in the log the failure looked like the model emitting bad JSON.
    # The split matters too — reasoning shares the budget with the answer.
    out = getattr(usage, "completion_tokens", None)
    reasoning = getattr(
        getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None
    )
    print(f"[{tag}] cache hit={hit if hit is not None else 'n/a'} "
          f"miss={miss if miss is not None else 'n/a'} tokens; "
          f"completion={out if out is not None else 'n/a'} "
          f"(reasoning {reasoning if reasoning is not None else 'n/a'})")


# Reasoning tokens share the completion budget, so the cap must leave room for
# the chain of thought as well as the JSON answer.
#
# History, because each step was sized off measurement rather than guessed:
# 4000 -> 8000 when earnings_quality shipped. The 4000 cap was sized for a
# ~400-token answer; an announcement with several income and charge lines emits
# 700-1,200 tokens of JSON on top of reasoning that itself ran 2,500 tokens on a
# typical BARC call. At 4000, BARC 9689888 failed 7 of 7 validation runs and 19
# of 56 calls across the target set died. At 6000 it still burned the whole
# budget on 1 of 7.
#
# 8000 -> 32000 on 2026-07-31, after 21 of 48 rows in the morning batch — every
# one of them a large-cap interim or prelim — came back empty. Measured need on
# three of them, re-run at 32000 and all finishing with valid JSON:
#
#     NWG 9697081   reasoning  7,945 + answer 1,693 = 9,638
#     IAG 9696992   reasoning 17,067 + answer 1,278 = 18,345
#     ITV 9697040   reasoning 16,075 + answer 1,749 = 17,824
#
# So 8000 was not marginally short, it was less than half. Note the trigger is
# announcement *complexity*, not size: IAG's body is 14k chars and ITV's 18k,
# while 167k-char rows scored fine on the old cap.
#
# The failure mode is silent and expensive. Reasoning consumes the whole budget,
# the model emits zero answer tokens, json.loads raises on an empty string, and
# _rank_pending's per-row isolation turns that into a row that is never scored,
# never flagged and never in the digest — on exactly the large caps this field
# exists to judge. Worse, it is indistinguishable in the DB from a row that was
# never attempted, because llm_processed_at stays NULL either way.
#
# A cap is not a target: it bills what is generated, so raising it costs nothing
# on calls that were already finishing, and every call it rescues was previously
# 100% wasted spend and latency. Watch the completion counts in the log rather
# than assuming 32000 holds forever.
_MAX_COMPLETION_TOKENS = int(os.environ.get("RNS_MAX_COMPLETION_TOKENS", "32000"))

# Fast-path budget. With reasoning disabled the answer is the whole completion,
# and the answer is what the 4000 -> 8000 step above was actually sized for:
# 700-1,200 tokens of JSON on a row with several income and charge lines, on top
# of a ~400-token typical answer. 4000 is ~3x the worst measured answer, and the
# retry at double still covers a surprise. Keeping it low is the point — it caps
# what a fast-path row can cost if a future prompt change makes it verbose.
_FAST_MAX_COMPLETION_TOKENS = int(os.environ.get("RNS_FAST_MAX_COMPLETION_TOKENS", "4000"))

# Safety net for the category gate. A 10-row A/B on 2026-07-31 (thinking off vs
# on, same prompt, same rows) found the two modes agree exactly on only 3 of 10
# and the fast path runs a mean +4 higher, max delta 20. That is tolerable ONLY
# because every one of those rows scored 5-55, nowhere near the digest's 76 bar
# — which is why these categories were picked. Some of the delta is not even a
# mode effect: at temperature 0.2 thinking mode disagreed with its own stored
# score on several of the same rows.
#
# So the gate's assumption is "these categories don't produce digest rows". If
# that stops being true, the log must say so — the alternative is finding out
# via a story the feed under-scored, and a missed tradeable announcement is the
# expensive error here. Set below the 76 bar to give warning, not a post-mortem.
_FAST_REVIEW_SCORE = int(os.environ.get("RNS_FAST_REVIEW_SCORE", "65"))


# Sampling temperature, named because it is a calibration constant rather than a
# tunable: every stored llm_score was produced at this value, as were the
# digest's 76 bar and the 76+/80+ thresholds. Changing it re-bases the whole feed
# against its own history.
#
# It only reaches the FAST path in practice. deepseek-v4-flash ignores
# temperature in thinking mode (confirmed 2026-08-05), so it does nothing at all
# for reasoning-on callers — notably the showcase vet, whose run-to-run score
# spread therefore cannot be fixed by turning this down. See the note beside
# showcase._VET_MAX_COMPLETION_TOKENS before spending time on that idea again.
_DEFAULT_TEMPERATURE = 0.2


class TruncatedResponse(RuntimeError):
    """The model ran out of completion budget before finishing its answer.

    Distinct from a JSONDecodeError because the two want opposite fixes — this
    one means raise the budget, that one means the model emitted junk — and
    because the truncated body is usually empty, which makes them look identical
    at the call site.
    """


def _call_deepseek(
    messages: list[dict],
    thinking: bool = True,
    budget: Optional[int] = None,
    tag: Optional[str] = None,
) -> dict:
    """One JSON-returning DeepSeek call with the truncation retry.

    `thinking=False` is the fast path — same prompt and same schema, no
    reasoning chain, and a budget sized for the answer alone.

    `budget` and `tag` exist for callers outside the ranker (the showcase vet).
    They are here rather than duplicated at the call site because the truncation
    handling below is the part that must not be got wrong twice: a silent
    finish_reason='length' is indistinguishable from a row that was never
    attempted, which is exactly how 21 large caps went unscored on 2026-07-31.

    Thinking defaults to True so that a caller which hasn't thought about the
    mode gets the thorough one.
    """
    client = _get_client()
    # One retry at double the budget. Reasoning length is nondeterministic, so a
    # row that overruns is often fine on a second pass; before this existed the
    # only retry was the next 15-minute sweep, which meant a row could miss the
    # 07:30 digest entirely while still eventually scoring an hour later.
    base = budget or (_MAX_COMPLETION_TOKENS if thinking else _FAST_MAX_COMPLETION_TOKENS)
    budgets = (base, base * 2)
    # Named apart from the `budget` parameter on purpose — shadowing it here
    # would make the retry silently depend on which line read it first.
    for attempt, attempt_budget in enumerate(budgets, start=1):
        resp = client.chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=_DEFAULT_TEMPERATURE,
            max_tokens=attempt_budget,
            extra_body=_THINKING_ON if thinking else _THINKING_OFF,
        )
        label = tag or ("rns_llm" if thinking else "rns_llm:fast")
        _log_cache_usage(label, resp)
        choice = resp.choices[0]
        if getattr(choice, "finish_reason", None) != "length":
            return json.loads(choice.message.content)
        # Log loudly: this is the one-line diagnosis that the investigation
        # above cost a morning to reach.
        used = getattr(getattr(resp, "usage", None), "completion_tokens", "n/a")
        print(f"[{label}] !! response hit max_tokens at {attempt_budget} "
              f"(completion tokens: {used}) — "
              + ("retrying at double" if attempt < len(budgets) else "giving up"))
    raise TruncatedResponse(
        f"model exhausted {budgets[-1]} completion tokens without finishing"
    )


# The two guidance axes, kept as explicit whitelists. Anything the model
# invents outside these lands as "unknown"/"no_consensus_stated" rather than
# being stored verbatim — showcase's gate matches on exact values, so an
# unrecognised label must fail safe (not disqualifying) rather than silently
# never matching.
_VS_PRIOR = ("raised", "reiterated", "lowered", "new", "unknown")
_VS_CONSENSUS = ("above", "in_line", "below", "no_consensus_stated")


def _clean_guidance_checks(raw) -> Optional[list]:
    """Normalise the model's guidance_checks array before it is stored.

    Returns None (SQL NULL) when the model emitted nothing usable, so
    "no guidance in this announcement" and "the model didn't answer" are not
    conflated with an empty-but-present array.
    """
    if not isinstance(raw, list):
        return None
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        vs_prior = str(entry.get("vs_prior") or "").lower().strip()
        vs_consensus = str(entry.get("vs_consensus") or "").lower().strip()
        out.append(
            {
                "metric": (str(entry.get("metric") or "").strip()[:200] or None),
                "period": (str(entry.get("period") or "").strip()[:50] or None),
                "guided_value": (
                    str(entry.get("guided_value") or "").strip()[:200] or None
                ),
                "consensus_value": (
                    str(entry.get("consensus_value") or "").strip()[:200] or None
                ),
                "vs_prior": vs_prior if vs_prior in _VS_PRIOR else "unknown",
                "vs_consensus": (
                    vs_consensus
                    if vs_consensus in _VS_CONSENSUS
                    else "no_consensus_stated"
                ),
            }
        )
    return out or None


# The two composition kinds, same whitelist discipline as _VS_PRIOR above.
# Anything else lands as "unclear", which showcase's earnings-quality gate
# never matches — an unrecognised label must fail open, because dropping a
# tradeable announcement is the high-severity error in this system.
_EQ_KIND = ("income", "cost_or_charge")


def _clean_earnings_quality(raw) -> Optional[list]:
    """Normalise the model's earnings_quality array before it is stored.

    Same contract as _clean_guidance_checks: None (SQL NULL) when nothing
    usable came back, so "this announcement quantifies no income or charge
    lines" is distinguishable from "the model didn't answer".

    Entries with no `item` are dropped — there is nothing to adjudicate and
    nothing readable to log. Everything else is kept verbatim as printed:
    parsing the numbers is showcase's job, deliberately, so that a parse
    failure there is visible against a stored quote rather than hidden behind
    a value this function guessed at.
    """
    if not isinstance(raw, list):
        return None
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        item = str(entry.get("item") or "").strip()[:200]
        if not item:
            continue
        kind = str(entry.get("kind") or "").lower().strip()
        out.append(
            {
                "item": item,
                "period": (str(entry.get("period") or "").strip()[:50] or None),
                "value": (str(entry.get("value") or "").strip()[:200] or None),
                "prior_value": (
                    str(entry.get("prior_value") or "").strip()[:200] or None
                ),
                "kind": kind if kind in _EQ_KIND else "unclear",
                "one_off_named": (
                    str(entry.get("one_off_named") or "").strip()[:300] or None
                ),
            }
        )
    return out or None


def _save_ranking(ann_id: int, result: dict, model: str) -> None:
    # Sentiment is constrained to the three known values — anything else the
    # model invents is stored as NULL so _sentiment falls back to its scan.
    sentiment = (result.get("sentiment") or "").lower().strip()
    if sentiment not in ("positive", "negative", "neutral"):
        sentiment = None
    guidance_checks = _clean_guidance_checks(result.get("guidance_checks"))
    earnings_quality = _clean_earnings_quality(result.get("earnings_quality"))
    # Optional — most announcements state no explicit forward guidance figure.
    guidance_metric = (result.get("guidance_metric") or "").strip()[:200] or None
    guidance_value = (result.get("guidance_value") or "").strip()[:200] or None
    guidance_period = (result.get("guidance_period") or "").strip()[:50] or None
    # A metric without a value (or vice versa) isn't a usable data point for
    # the next announcement's comparison — drop the pair rather than store a
    # half-filled row that _load_prior_guidance would surface as garbage.
    if not (guidance_metric and guidance_value):
        guidance_metric = guidance_value = guidance_period = None
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE rns_announcements
            SET llm_score        = %s,
                llm_confidence   = %s,
                llm_thesis       = %s,
                llm_action       = %s,
                llm_risks        = %s,
                llm_sentiment    = %s,
                llm_model        = %s,
                llm_processed_at = NOW(),
                guidance_metric  = %s,
                guidance_value   = %s,
                guidance_period  = %s,
                guidance_checks  = %s,
                earnings_quality = %s
            WHERE id = %s
        """,
            (
                _clip_int(result.get("score"), 0, 100),
                (result.get("confidence") or "").lower()[:10] or None,
                (result.get("thesis") or "")[:500] or None,
                (result.get("action") or "").lower()[:10] or None,
                (result.get("risks") or "")[:500] or None,
                sentiment,
                model,
                guidance_metric,
                guidance_value,
                guidance_period,
                Json(guidance_checks) if guidance_checks is not None else None,
                Json(earnings_quality) if earnings_quality is not None else None,
                ann_id,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _clip_int(v, lo: int, hi: int) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _rank_one(row_id: int) -> dict:
    cand = _load_candidate(row_id)
    if cand is None:
        raise ValueError(f"row {row_id} not found")
    history = _load_history(cand.get("symbol"))
    price = _load_price_change(cand.get("symbol"))
    prior_guidance = _load_prior_guidance(cand.get("symbol"), exclude_id=row_id)
    messages = _build_messages(cand, history, price, prior_guidance)
    thinking = _use_thinking(cand.get("category"))
    result = _call_deepseek(messages, thinking=thinking)
    # The mode suffix makes the reasoning cutover visible in llm_model so score
    # distributions can be compared across it. It now also records which mode
    # ranked each row, which is the only way a later A/B can separate the two
    # populations — the July switch was unmeasurable precisely because model and
    # mode changed together with nothing in the row to tell them apart.
    _save_ranking(row_id, result, f"{_DEEPSEEK_MODEL}:{'thinking' if thinking else 'fast'}")
    score = _clip_int(result.get("score"), 0, 100)
    # Only the CATEGORY gate gets this tripwire. It means "a category we gated as
    # never approaching the bar just approached it" — which is only a surprise
    # while other rows are still reasoning. Under the blanket switch every row is
    # fast and every digest row would trip it, turning the one loud line that
    # matters into several per morning that nobody reads.
    if _THINKING_DEFAULT and not thinking and score is not None and score >= _FAST_REVIEW_SCORE:
        print(f"[rns_llm] !! fast-path row scored {score} — id={row_id} "
              f"category={cand.get('category')}. This category was gated because it "
              "produced no rows near the digest bar; re-check RNS_FAST_CATEGORIES.")
    return {"id": row_id, "thinking": thinking, **result}


def _rank_pending(limit: int = 50, tiers: tuple = ("A", "B"), hours: int = 72) -> dict:
    """Rank recent tier A/B rows that haven't been processed yet.

    Ranking is I/O-bound — nearly all of each row's ~8-16s is spent waiting on
    DeepSeek — so the calls run through a small thread pool rather than end to
    end. Sequentially a 43-story morning took ~340s, which pushed the batch's
    completion right up against the 07:30 digest send; concurrency is what makes
    an earlier send safe. `RNS_RANK_WORKERS=1` restores the serial behaviour.

    Note this is deliberate, bounded concurrency inside ONE run. It is not the
    same as the overlapping cron runs that used to rank in parallel by accident,
    re-doing each other's rows — see run_rns.py's pipeline lock.
    """
    rows = _query(
        """
        SELECT id
        FROM rns_announcements
        WHERE tier = ANY(%s)
          AND llm_processed_at IS NULL
          AND published_at >= NOW() - (%s || ' hours')::interval
        ORDER BY published_at DESC
        LIMIT %s
    """,
        (list(tiers), str(hours), limit),
    )

    ranked = errors = 0
    # Counted so the cron log shows how the batch split across the two modes —
    # the fast path is only worth keeping if it is actually taking rows, and a
    # classifier change upstream could quietly empty it.
    fast = 0

    def _attempt(row_id: int) -> Optional[bool]:
        """Returns the mode the row ranked in, or None if it failed. The counters
        are accumulated by the consumer, not here — `_attempt` runs on several
        threads at once and `+=` on a shared int can lose an update."""
        try:
            return _rank_one(row_id)["thinking"]
        except Exception as e:
            # Per-row isolation, unchanged from the serial version: one bad row
            # (or one rate-limited call) must never sink the rest of the batch.
            print(f"[rns_llm] rank failed for {row_id}: {e}")
            return None

    workers = min(_RANK_WORKERS, len(rows))
    if workers > 1:
        # Build the shared client once here rather than letting several threads
        # race _get_client()'s lazy init and construct throwaway duplicates.
        _get_client()
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rns-rank") as pool:
            modes = list(pool.map(_attempt, [r["id"] for r in rows]))
    else:
        modes = [_attempt(r["id"]) for r in rows]

    # `mode is None` is the failure case. Testing truthiness here would count
    # every successful fast-path row as an error, since fast rows report False.
    for mode in modes:
        if mode is None:
            errors += 1
        else:
            ranked += 1
            fast += not mode

    result = {"candidates": len(rows), "ranked": ranked, "fast": fast, "errors": errors}
    print(f"[rns_llm] ranking done — {result}")
    return result


def _rank_pending_locked(limit: int = 50, tiers: tuple = ("A", "B"), hours: int = 72) -> dict:
    """_rank_pending under the pipeline lock — the entry point for POST /rank.

    The cron entry points (run_rns.py, refresh_rns.py) already take this lock,
    for the reason spelled out in run_rns.main: _rank_pending selects on
    `llm_processed_at IS NULL` with no per-row claim, so anything ranking
    concurrently re-ranks whatever the other run hasn't written back yet —
    duplicate DeepSeek calls that pay twice for identical scores. The HTTP route
    ran the same function outside the lock, which made a manual rank during the
    07:00 batch (exactly when someone is most likely to reach for it) the one
    case the lock was built to prevent.

    Losing the race is a normal outcome, not an error: the in-flight run is
    already ranking these rows, so there is nothing for this call to do.
    """
    # Lazy: refresh_rns imports this module at module level, so importing it up
    # top would be circular. It owns the key so both entry points share one
    # definition (see its comment) — don't re-declare the constant here.
    from db import advisory_lock
    from refresh_rns import RNS_PIPELINE_LOCK_KEY

    with advisory_lock(RNS_PIPELINE_LOCK_KEY) as acquired:
        if not acquired:
            print("[rns_llm] pipeline run already in flight — skipping manual rank")
            return {"candidates": 0, "ranked": 0, "errors": 0, "skipped": "locked"}
        return _rank_pending(limit, tiers, hours)


# ── API endpoints ─────────────────────────────────────────────────────────────


@router.post("/rank", dependencies=[Depends(require_admin_token)])
def rank(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    hours: int = Query(72, ge=1, le=168),
):
    """Kick off LLM ranking for pending tier A/B rows.

    The lock is taken inside the background task, not here: this handler returns
    before the task runs, so a lock held across the response would be released
    the moment the work started.
    """
    background_tasks.add_task(_rank_pending_locked, limit, ("A", "B"), hours)
    return {"status": "ranking started", "limit": limit, "hours": hours}


@router.post("/rank/{row_id}", dependencies=[Depends(require_admin_token)])
def rank_one(row_id: int):
    """Rank a single announcement synchronously (for debugging)."""
    try:
        return _rank_one(row_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/ranked")
def get_ranked(
    min_llm_score: int = Query(60, ge=0, le=100),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=500),
    response: Response = None,
):
    """LLM-ranked feed for the morning screen."""
    # Populated periodically by the LLM ranking job — a 5-min edge cache is plenty.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=900"
    return _query(
        """
        SELECT id, published_at, ticker, symbol, company_name, headline, url,
               tier, category, score,
               llm_score, llm_confidence, llm_thesis, llm_action, llm_risks,
               llm_sentiment, llm_model, llm_processed_at
        FROM rns_announcements
        WHERE llm_processed_at IS NOT NULL
          AND llm_score >= %s
          AND published_at >= NOW() - (%s || ' hours')::interval
        ORDER BY llm_score DESC, published_at DESC
        LIMIT %s
    """,
        (min_llm_score, str(hours), limit),
    )
