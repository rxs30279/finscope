"""High Impact RNS — curated showcase of high-impact, positive RNS stories.

Pipeline (all driven from run_rns.py after the LLM ranking stage):
  1. flag_high_impact_candidates() — rules pick candidates (high llm_score,
     positive sentiment, performance-report category, market-cap floor), then an
     LLM vet SCORES each one and that score decides publication (migration 029,
     2026-08-03): vet_score >= 75 lands as status='approved', live on the public
     page; below it lands as status='shadow' and is never rendered. The vet was
     advisory before that and much of the surrounding prose still reads that way
     — treat "advisory" anywhere in this file as pre-029 wording. There is no
     human approval gate — the admin archives unsuitable entries after the fact.
     Each announcement is vetted once, and only once: the cron re-runs this
     every 15 minutes over a 48h window, so re-selecting a scored row means
     re-paying for a verdict already stored (fixed 2026-08-05).
  2. record_followups() — copies subsequent tier A/B announcements for each
     tracked company into high_impact_rns_followups, so bad news that surfaces
     AFTER selection (Luceco-style CEO exit) is captured even though Tier C
     source rows still prune at 14 days (A/B rows themselves are now kept).

Entries stay on the public page indefinitely — there is no auto-archive; the
admin archives a story manually when it no longer belongs.

Endpoints serve the approved (public) and pending (admin) lists enriched with the
same per-stock metrics as the watchlist plus MQVR scores, days-since / %-since the
story, and the follow-up tally. Story data is snapshotted at flag time; Tier C
rns_announcements rows still prune after 14 days (run_rns.py) but Tier A/B rows
are retained indefinitely as prior-news history (see _prune_old).

Main-module helpers (_watchlist_rows, the score functions) are imported lazily
inside functions to avoid a circular import at load time — main.py registers this
router before those helpers are defined.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import re
import tempfile
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import Json

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from admin_auth import require_admin_token

router = APIRouter(prefix="/api/showcase", tags=["showcase"])

# ── Tunables ──────────────────────────────────────────────────────────────────
# The auto-flag is deliberately strict: this is a small, curated showcase, so a
# missed candidate is cheap (nothing appears) while a weak one wastes a review.
#
# TWO thresholds since migration 029, because there are now two scores. The
# ranker's llm_score decides who is worth an expensive second look; the vet's
# vet_score decides who is published. They are NOT the same question — see
# _vet_messages for the rubric split — so do not collapse them back into one
# number without reading that comment first.
#
# Entry to the vet. Was 75 and did double duty as the publish floor until
# 2026-08-03. Dropped to 60 so the vet can PROMOTE a story the ranker
# underrated: the 60-74 band is ~48 rows/month that previously got no second
# look at all, and missing a tradeable announcement is this system's
# high-severity error. Nothing in that band has ever been vetted (n=0), so
# expect the include rate to fall — that is the band being unproven, not a
# malfunction.
HIGH_IMPACT_VET_ENTRY_SCORE = 60
# Publish floor, applied to the VET's score. Rows that clear the entry score but
# not this land as status='shadow' — vetted, stored, invisible.
HIGH_IMPACT_MIN_VET_SCORE = 75
HIGH_IMPACT_CATEGORIES = ("trading_update", "final_results", "interim_results", "quarterly")
HIGH_IMPACT_MIN_MARKET_CAP = 50_000_000  # £50m — keep to genuinely tradeable names
# Balance-sheet / quality floors — keep over-levered and low-quality names out of
# the showcase entirely (they convert good news to shareholder value poorly). These
# mirror the leverage/quality flags in the LLM ranker so the two stages agree.
# The companion "net debt > market cap" test is in the SQL, not a tunable here,
# and is the only floor needing FX — net_debt is reporting-currency, market_cap
# is GBP (see _fx_to_gbp).
HIGH_IMPACT_MAX_NET_DEBT_TO_EBITDA = 3.0  # skip net debt > 3x profit (same currency both sides, no FX)
HIGH_IMPACT_MIN_NET_MARGIN = 0.02         # fallback margin floor when no usable peer median exists
HIGH_IMPACT_MIN_ROCE = 0.15               # capital-returns escape hatch past the margin floor (profitable names only)
# Second capital-returns hatch, added 2026-08-12 alongside ROCE. ROCE divides by
# total assets - current liabilities, so a cash pile and a non-operating
# investment portfolio both inflate the denominator without contributing EBIT,
# and a genuinely efficient operator can read as capital-inefficient. ROIC
# subtracts cash from that denominator (updater.calc_roic), which is the
# distinction that matters here. Balfour Beatty is the worked example: ROCE 7.2%
# against ROIC 16.0% and ROE 23.0%, on £842m NET CASH plus the Infrastructure
# Investments portfolio — blocked on 2026-08-12 with an llm_score of 75.
#
# Kept at the same 0.15 as ROCE deliberately, and it is NOT the loose setting it
# looks. ROIC's numerator is after-tax (x ~0.79), so for a cash-poor name the
# ROIC test is STRICTER than the ROCE one and never fires alone; it only opens
# the gate where the cash/investment denominator was the thing distorting ROCE.
# Measured against the 700-name universe the day it was added, it admits three
# extra companies in total (APTD.L, TENG.L, BBY.L), and across six weeks of
# stored RNS candidates it changes exactly one outcome. Raising it to 0.20
# admits nobody at all, so a higher floor is a no-op, not a safety margin.
HIGH_IMPACT_MIN_ROIC = 0.15               # cash-adjusted twin of the ROCE hatch (profitable names only)
PEER_MARGIN_MIN_GROUP = 5                 # industry margin medians need at least this many names to count
HIGH_IMPACT_DEDUPE_DAYS = 30             # don't re-flag the same symbol within a month
# Display floor for the page (2026-08-06). Stories published before this date
# are NOT deleted — they stay in high_impact_rns with their follow-ups intact,
# still feed /gates and every calibration query — they are simply no longer
# served to /high-impact-rns. The list restarts from the vet-as-scorer regime
# (migration 029, 2026-08-03) rather than mixing in picks published under the
# old single-score rule, which are not comparable and mostly render "—" where
# the vet score should be. Move the date to change what the page shows; there
# is no other switch.
SHOWCASE_MIN_STORY_DATE = "2026-08-01"


# ── Sentiment (server-side port of RnsTab.js getSentiment) ────────────────────
_NEG_CATS = {"profit_warning", "going_concern", "liquidation", "delisting", "suspension"}
_POS_CATS = {"firm_offer", "recommended_offer", "drug_approval", "contract_win"}
# Thesis-scan word lists — kept in sync across showcase.py, email_rns_digest.py
# and RnsTab.js: edit all three together. "upgrad"/"downgrad"/"dilut"/
# "deteriorat" are stems (the whole words never substring-match "upgrading",
# "dilutive", "deteriorating"). Vocabulary is calibrated against real DeepSeek
# theses (2y CMCX/KLR/TBTG backtest + 438 stored prod theses, 2026-07): the
# "ahead of …"/"record"/"surge" forms are standard UK results phrasing, the
# premium/offer cluster covers M&A targets, and "dilut"/"solvency"/"distress"
# the discounted-placing cluster. Known limit: the scan is negation-blind
# ("lack of distress" still counts) — the stored llm_sentiment layer above it
# is the real signal; this list is the fallback for unranked/legacy rows.
_LLM_POS = ["positive", "upside", "beat", "above expectations", "outperform",
            "upgrad", "bullish", "boost", "opportunity", "record",
            "ahead of expectations", "ahead of consensus", "ahead of guidance",
            "swing to profit", "above consensus", "accretive", "surge",
            "de-risk", "unlock", "exceed", "better than expected",
            "at a premium", "significant premium", "higher offer",
            "re-rate", "re-rating"]
_LLM_NEG = ["negative", "pressure", "miss", "below expectations", "concern",
            "decline", "downgrad", "disappoint", "warning", "bearish", "weak",
            "dilut", "solvency", "distress", "slash", "headwind", "shortfall",
            "deteriorat", "impairment", "write-down", "write down",
            "below consensus", "below guidance", "collapse", "downside",
            "net loss", "suspend", "cash crunch", "deeply discounted"]


def _sentiment(row) -> str:
    """Classify an announcement as 'positive' | 'negative' | 'neutral'.

    Mirrors the frontend getSentiment so the flag rule and the follow-up tally
    agree with what the RNS page shows: category override first, then the
    ranker's own stored sentiment (llm_sentiment, migration 012), then a scan
    of the LLM thesis, then the pos:/neg: keyword_hits counts as a last resort.
    """
    cat = row.get("category")
    if cat in _NEG_CATS:
        return "negative"
    if cat in _POS_CATS:
        return "positive"

    # The ranker read the full announcement and emitted a direction — trust it
    # over any keyword scan of its prose (which is negation-blind). NULL for
    # rows ranked before the field existed; they fall through to the scan.
    llm_sent = (row.get("llm_sentiment") or "").lower()
    if llm_sent in ("positive", "negative", "neutral"):
        return llm_sent

    thesis = (row.get("llm_thesis") or "").lower()
    if thesis:
        pos = sum(1 for w in _LLM_POS if w in thesis)
        neg = sum(1 for w in _LLM_NEG if w in thesis)
        if neg > pos:
            return "negative"
        if pos > neg:
            return "positive"

    hits = row.get("keyword_hits") or []

    def _count(prefix):
        # Stored as count strings like "pos:2" / "neg:1" (see rns.py); a bare
        # "pos" with no count still reads as one hit.
        total = 0
        for h in hits:
            if h.startswith(prefix):
                _, _, n = h.partition(":")
                try:
                    total += int(n) if n else 1
                except ValueError:
                    total += 1
        return total

    neg, pos = _count("neg:"), _count("pos:")
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


# ── DB helpers ────────────────────────────────────────────────────────────────
def _q(sql, params=None) -> list[dict]:
    """SELECT / RETURNING → list of dict rows. Delegates to main.query (imported
    lazily to dodge the circular import)."""
    from main import query
    return query(sql, params)


def _exec(sql, params=None) -> int:
    """Write with no result set → affected row count."""
    from main import get_pool
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.rowcount
    finally:
        pool.putconn(conn)


# LSE closing auction. An announcement released after this has NOT moved that
# day's closing price, so the same-day close is still a clean pre-news baseline.
# Released at or before it, the close already contains the reaction.
_LSE_CLOSE_LOCAL = "16:30"


def _story_close(symbol: str, published_at) -> Optional[float]:
    """Close (pence) from BEFORE the story broke — the baseline for % since news.

    Keyed on the announcement's own release time, not on when this runs.

    The previous rule was `date <= published_at::date`, which is only correct
    while the flag happens before that day's close — true for a same-morning
    cron, false the moment a row is flagged a day late. Then the announcement
    day had already traded, so the query returned the close that CONTAINS the
    story's own move and "% since news" measured the move from its own endpoint.
    Five stored rows were wrong this way; CMCX.L 2026-07-01 rose 458 -> 650 on
    the day and read as flat, and SYNT.L fell hard so its baseline FLATTERED it.
    Direction of the error follows the direction of the move, so it is not
    noise that averages out.

    07:00 London is the standard RNS slot (1,646 of ~2,100 rows in a 30-day
    window), but the spread across the day is real, so the boundary is the
    release time rather than a blanket "always take the previous close" —
    a genuinely post-close announcement did not move that day's close.
    """
    rows = _q(
        """
        WITH s AS (SELECT (%s AT TIME ZONE 'Europe/London') AS local_ts)
        SELECT p.close
        FROM price_history p, s
        WHERE p.symbol = %s
          AND (
              p.date < s.local_ts::date
              OR (p.date = s.local_ts::date AND s.local_ts::time > %s::time)
          )
        ORDER BY p.date DESC
        LIMIT 1
        """,
        (published_at, symbol, _LSE_CLOSE_LOCAL),
    )
    return float(rows[0]["close"]) if rows and rows[0]["close"] is not None else None


# LSE opening auction. An RNS released before it (07:00 is the standard slot,
# 34 of the 36 stories ever showcased) is already public when the market opens,
# so THAT day's open is the first price anyone could have dealt at.
_LSE_OPEN_LOCAL = "08:00"


def _entry_open(symbol: str, published_at) -> Optional[float]:
    """Open (pence) of the first session that could trade on the news.

    The far end of the gap and the near end of "since the open" — the two halves
    the page splits the move into, matching /gates (gates._row_returns), the
    landing story and analysis/rns_score_perf.py.

    For the standard 07:00 release that is the announcement day's OWN open, not
    the day after. The day-after rule this replaced (_next_open) skipped the
    entire session the news was priced into, which is where the reaction lands —
    the same off-by-one that flattened the signal in the score-performance work.

    An announcement released after the open falls through to the next session:
    its own day's open is a pre-news price, and using it would put part of the
    post-news move inside the "gap" the reader is told they missed.

    None until that session's bar exists — a story that broke this morning has
    no open on record yet, so the page shows a dash rather than a guess.
    """
    rows = _q(
        """
        WITH s AS (SELECT (%s AT TIME ZONE 'Europe/London') AS local_ts)
        SELECT p.open
        FROM price_history p, s
        WHERE p.symbol = %s
          AND p.open IS NOT NULL
          AND (
              p.date > s.local_ts::date
              OR (p.date = s.local_ts::date AND s.local_ts::time < %s::time)
          )
        ORDER BY p.date ASC
        LIMIT 1
        """,
        (published_at, symbol, _LSE_OPEN_LOCAL),
    )
    return float(rows[0]["open"]) if rows and rows[0]["open"] is not None else None


def _spark_since_count(symbol: str, published_at) -> int:
    """How many of the last ~63 trading-day closes (the sparkline window) fall on
    or after the story date — the length of the 'since selection' line segment."""
    rows = _q(
        """
        SELECT COUNT(*) AS n FROM (
            SELECT date FROM price_history WHERE symbol = %s ORDER BY date DESC LIMIT 63
        ) x WHERE date >= %s::date
        """,
        (symbol, published_at),
    )
    return int(rows[0]["n"]) if rows else 0


# ── Showcase-specific LLM vet (advisory) ──────────────────────────────────────
def _annual_history(symbol: Optional[str], before=None, years: int = 5) -> list[dict]:
    """Last `years` fiscal years from annual_financials, oldest first.

    `before` (a date) keeps only fiscal years ended before it — used by
    backtests to avoid look-ahead; production passes None (a fresh announcement
    can legitimately see every reported year)."""
    if not symbol:
        return []
    rows = _q(
        """
        SELECT fiscal_year, period_end_date, revenue, operating_income,
               net_income, eps_diluted,
               -- Dilution. The vet's system prompt has always named "heavy
               -- equity dilution" as one of the things it must catch, and until
               -- 2026-08-03 it was given no share count to catch it with.
               shares_diluted,
               -- Cash conversion and balance sheet. A profit line that is not
               -- converting to cash, or growth funded by rising net debt, is
               -- exactly the "positive-FRAMED story the market may punish"
               -- this call exists to find — and none of it was reachable from
               -- revenue/operating income/net income alone.
               fcf, net_debt, total_equity,
               operating_margin, net_income_margin, roce,
               -- NULL for any row written before migration 034 — see that
               -- migration for why gates._low_base_fy_series treats NULL as
               -- "unknown", not "matches", when it cross-checks this against
               -- the announcement's own currency.
               currency
        FROM annual_financials
        WHERE company_symbol = %s
          AND (%s::date IS NULL OR period_end_date < %s::date)
        ORDER BY period_end_date DESC
        LIMIT %s
        """,
        (symbol, before, before, years),
    )
    return list(reversed(rows))


# Reporting currency of the annual_financials series. company_metadata's
# financial_currency is USD for the multinationals that file in dollars (Shell,
# BP, AZN) — prices.py:592 draws exactly this distinction for market cap, and
# news.py already threads it into its own prompt. Hardcoding "£" here mislabelled
# every one of those rows inside a prompt that then instructs the model to
# compare the series against the announcement's own figures "carefully": the
# announcement says $40,000m, the context said £40,000.0m, and nothing told the
# model they were the same number.
#
# Symbol only where it is unambiguous. "$" alone cannot separate USD from
# CAD/AUD, so anything outside this map renders as a bare code ("CAD 40.0m").
_CCY_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}


def _ccy(currency: Optional[str]) -> str:
    """Prefix for a money figure in `currency`. Falls back to "£" when the
    reporting currency is not on file — the universe is UK-listed, so GBP is the
    right assumption, and _annual_lines labels it as an assumption rather than
    letting it pass as fact."""
    code = (currency or "").upper().strip()
    if not code:
        return "£"
    return _CCY_SYMBOL.get(code) or f"{code} "


def _ccy_label(currency: Optional[str]) -> str:
    """How the annual block announces its own units to the model."""
    code = (currency or "").upper().strip()
    if not code:
        return "GBP (£) — reporting currency not on file, assumed"
    sym = _CCY_SYMBOL.get(code)
    return f"{code} ({sym})" if sym else code


def _fmt_money_m(v, ccy: str = "£") -> str:
    if v is None:
        return "n/a"
    return f"{ccy}{float(v) / 1e6:,.1f}m"


def _fmt_pct1(v) -> str:
    """Ratios are stored as fractions (0.081 = 8.1%)."""
    if v is None:
        return "n/a"
    return f"{float(v) * 100:.1f}%"


def _fmt_shares_m(v) -> str:
    if v is None:
        return "n/a"
    return f"{float(v) / 1e6:,.1f}m"


def _fmt_eps(v, currency: Optional[str] = None) -> str:
    """Diluted EPS in the unit the company's own announcement quotes it in.

    Stored as a per-share amount in the reporting currency (0.167 = 16.7p for a
    GBP filer). The x100 pence conversion is a GBP convention: applied to a
    dollar filer it renders $3.50 as "350.0p", a figure that appears nowhere in
    the announcement the model is being asked to check the series against.
    """
    if v is None:
        return "n/a"
    code = (currency or "GBP").upper().strip() or "GBP"
    if code == "GBP":
        return f"{float(v) * 100:.1f}p"
    return f"{_ccy(code)}{float(v):.2f}"


def _fmt_net_debt_m(v, ccy: str = "£") -> str:
    """Net cash reads as net cash, never as negative net debt.

    Mirrors rns_llm._format_net_debt. "net debt £-198.6m" is a double negative
    the model has to unpick to reach "this company has £198.6m of cash", and
    getting it backwards inverts a leverage judgement — which is one of the
    four things the vet's system prompt exists to catch.

    Self-labelling ("net cash £198.6m" / "net debt £50.0m") rather than taking
    a fixed "net debt" label from the caller, so the line never reads
    "net debt £198.6m net cash".
    """
    if v is None:
        return "net debt n/a"
    nd = float(v)
    if nd < 0:
        return f"net cash {_fmt_money_m(-nd, ccy)}"
    return f"net debt {_fmt_money_m(nd, ccy)}"


def _annual_lines(hist: list[dict], currency: Optional[str] = None) -> str:
    """Render the annual series as prompt lines the vet can do arithmetic on.

    Two lines per year rather than one. The single-line version carried only
    revenue/operating income/net income/EPS, which left the model unable to
    answer questions the system prompt explicitly asks it — dilution needs a
    share count, and "profit flattered by one-off/non-cash gains" is far easier
    to spot when FCF sits next to net income. Kept as labelled text rather than
    a table because the surrounding prompt is prose and the model copies
    figures out of it verbatim.
    """
    if not hist:
        return "  (no stored annual financials for this company)"
    ccy = _ccy(currency)
    lines = []
    for h in hist:
        eps_s = _fmt_eps(h.get("eps_diluted"), currency)
        lines.append(
            f"  FY ended {h['period_end_date']}: revenue {_fmt_money_m(h.get('revenue'), ccy)}, "
            f"operating income {_fmt_money_m(h.get('operating_income'), ccy)}, "
            f"net income {_fmt_money_m(h.get('net_income'), ccy)}, diluted EPS {eps_s}"
        )
        lines.append(
            f"      FCF {_fmt_money_m(h.get('fcf'), ccy)}, "
            f"{_fmt_net_debt_m(h.get('net_debt'), ccy)}, "
            f"equity {_fmt_money_m(h.get('total_equity'), ccy)}, "
            f"diluted shares {_fmt_shares_m(h.get('shares_diluted'))}, "
            f"op margin {_fmt_pct1(h.get('operating_margin'))}, "
            f"net margin {_fmt_pct1(h.get('net_income_margin'))}, "
            f"ROCE {_fmt_pct1(h.get('roce'))}"
        )
    return "\n".join(lines)


# How much announcement text the vet sees. The stored rns_announcements.body is
# capped at 24k chars by rns._truncate_body — a cut sized for the RANKER, which
# runs on ~1,000 rows/month and only needs the narrative. The vet runs on ~107
# and has to read comparative tables, so it re-fetches the page instead. Same
# route showcase_fwd already takes, and for the same reason.
#
# Head+tail, not head-only: rns.py's own note records that reiterated-guidance
# language and consensus footnotes turn up ~85% of the way through a long
# results document, so a head-only cut drops exactly what the sceptical read
# needs. fetch_announcement_text truncates head-only, hence the raw fetch here.
_VET_BODY_HEAD = 60_000
_VET_BODY_TAIL = 20_000


def _head_tail(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail:
        return text
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n[… {omitted} chars omitted …]\n\n{text[-tail:]}"


def _vet_full_text(cand: dict) -> str:
    """Freshest, longest announcement text available for the vet.

    Falls back to the stored (24k-capped) body on any fetch failure, and to the
    stub message when there was never a body to fetch. Non-fatal by design: a
    slow or dead URL must degrade the vet's input, never cost a candidate its
    vet call — the score now decides publication, so a raised exception here
    would silently drop a story.
    """
    if cand.get("body_is_stub"):
        return "(body unavailable — announcement links to an external document)"
    stored = cand.get("body") or "(not available)"
    url = cand.get("url")
    if not url:
        return stored
    try:
        from showcase_fwd import fetch_announcement_text

        # max_chars far above any real announcement so the head+tail cut below
        # is the only truncation applied — fetch_announcement_text's own cut is
        # head-only and would defeat the point.
        full = fetch_announcement_text(url, max_chars=1_000_000)
    except Exception as e:
        print(f"[showcase] vet full-text fetch failed for {cand.get('symbol')} "
              f"(non-fatal, using stored body) — {e}")
        return stored
    if not full or len(full) <= len(stored):
        return stored
    return _head_tail(full, _VET_BODY_HEAD, _VET_BODY_TAIL)


def _vet_body_text(cand: dict) -> str:
    if cand.get("body_is_stub"):
        return "(body unavailable — announcement links to an external document)"
    return cand.get("body") or "(not available)"


def _price_context(symbol: Optional[str], before=None) -> str:
    """1m/6m price change for the vet, or an explicit no-data line.

    LOOK-AHEAD GUARD: rns_llm._load_price_change measures from CURRENT_DATE, not
    from the announcement. Live that is exactly right — the vet runs the same
    morning, so `latest` is the prior session's close, the price before this
    announcement's own move. For a backtest (`before` set) it would feed future
    prices into a past judgement, so it is withheld entirely rather than
    silently wrong. Same reason _annual_history takes `before`.
    """
    if before is not None:
        return "  (withheld — point-in-time re-run, live prices would be look-ahead)"
    if not symbol:
        return "  (no price history)"
    try:
        from rns_llm import _load_price_change, _fmt_pct

        p = _load_price_change(symbol)
    except Exception as e:
        print(f"[showcase] price context failed for {symbol} (non-fatal) — {e}")
        return "  (no price history)"
    if not p or (p.get("chg_1m") is None and p.get("chg_6m") is None):
        return "  (no price history)"
    return f"  1 month {_fmt_pct(p.get('chg_1m'))}, 6 months {_fmt_pct(p.get('chg_6m'))}"


def _size_context(cand: dict) -> str:
    """Market cap, plus a currency warning when it and the accounts disagree.

    The vet's system prompt names "heavy equity dilution" as one of the four
    things it exists to catch, and _annual_history was extended to supply
    shares_diluted for it — but without a market cap a placing or a share count
    cannot be sized against anything, so the check was unrunnable.

    CURRENCY TRAP, and the reason this is not just another line in the header:
    market_cap is denominated in the QUOTE currency (sterling for LSE lines —
    prices.py:592 draws the same distinction), while annual_financials is in the
    REPORTING currency, which is USD for the dollar filers. For HSBA the two
    blocks are therefore GBP and USD respectively. Handing the model a market cap
    without saying so would recreate, one block lower, exactly the mislabelling
    fixed in c1d08f1 — and a P/E or dilution ratio formed across the two would be
    wrong by the FX rate with nothing to reveal it.
    """
    cap = cand.get("market_cap")
    if cap is None:
        return "  (market cap not on file)"
    quote = cand.get("currency")
    sym = _ccy(quote)
    cap = float(cap)
    size = (
        f"{sym}{cap / 1e9:,.2f}bn" if abs(cap) >= 1e9 else f"{sym}{cap / 1e6:,.1f}m"
    )
    line = f"  Market cap {size}"

    # Only warn when the two really differ. Comparing the normalised codes, so
    # a GBp quote against GBP accounts stays quiet — same currency, and the
    # stored market cap is in pounds, not pence (verified against GRG's own
    # share count).
    # .upper() folds the "GBp" quote code onto "GBP" — the value itself is in
    # pounds, so the two are the same currency and must not trip the warning.
    q_code = (quote or "GBP").upper().strip() or "GBP"
    r_code = (cand.get("financial_currency") or "").upper().strip()
    if r_code and r_code != q_code:
        line += (
            f"\n  NOTE: this market cap is in {q_code}, but the company reports "
            f"its accounts in {r_code}, so the annual series below is in a "
            f"DIFFERENT currency. Do not form a ratio across the two (P/E, "
            f"market cap vs revenue, placing size vs equity) without converting "
            f"first — and if you have no rate, say the comparison cannot be made "
            f"rather than making it."
        )
    return line


def _guidance_context(cand: dict) -> str:
    """The ranker's structured guidance extraction, rendered for the vet.

    The vet's FIRST named job is catching guidance quietly cut inside an upbeat
    headline, and until now it re-derived that from raw announcement text while
    this — per-statement metric/period/guided value/consensus/vs_prior/
    vs_consensus, already extracted and stored by the ranker — sat unused in the
    same candidate row.

    NOT independent evidence: it is the same model reading the same document one
    pass earlier, so the prompt asks the vet to verify and contradict it rather
    than treat it as ground truth. That is also why it is placed after the
    announcement text, not before it.
    """
    entries = _guidance_entries(cand)
    if not entries:
        # Distinguish the two, exactly as _gate_guidance does: the ranker
        # emitting nothing is not the same as the announcement guiding nothing,
        # and neither is evidence about the company.
        if cand.get("guidance_checks") is None:
            return "  (not extracted for this announcement — read the text yourself)"
        return "  (the earlier read found no forward-looking statement)"
    lines = []
    for i, e in enumerate(entries, 1):
        metric = e.get("metric") or "(unnamed metric)"
        period = e.get("period") or "period unstated"
        guided = e.get("guided_value") or "(no figure printed)"
        lines.append(f"  {i}. {metric} ({period}): guided {guided}")
        detail = f"     vs prior guidance: {e.get('vs_prior') or 'unknown'}"
        detail += f"; vs consensus: {e.get('vs_consensus') or 'no_consensus_stated'}"
        if e.get("consensus_value"):
            detail += f" (consensus printed as {e['consensus_value']})"
        lines.append(detail)
    return "\n".join(lines)


# ── Sequential base, computed from pass 1 ────────────────────────────────────
# docs/rns-sequential-base-plan.md. The vet's own low_base object (below) is
# filled by the vet itself and can go unattempted — FRES.L 9702443 scored 45
# because the vet said the preceding half "cannot be verified" when the FRES
# announcement's own H1'25 revenue (captured correctly) and the FY25 total
# (already in this prompt's annual block) were enough to derive it: 4,561.2 -
# 1,936.2 = 2,625.0, giving +28.9%. gates._gate_low_base computed exactly that
# a few milliseconds after the vet scored the row — the answer was in the
# database before the score was saved.
#
# So this block is computed BEFORE the vet call, from pass 1's
# earnings_quality (rns_llm.py — ranker runs on ~1,000 rows/month vs the vet's
# ~107), and handed to the vet as a fact rather than left for the vet to
# derive under time/token pressure. Revenue only — see the plan §3 note on why
# adjusted-vs-statutory makes profit measures unsafe to map onto
# annual_financials (CTEC prints adjusted operating profit $262m beside
# reported $115m for the same period; subtracting one from the other produced
# a -97.2% garbage answer once already). There is no "adjusted revenue", so
# revenue is the one line safely comparable across the two sources.
_REVENUE_ITEM_RE = re.compile(r"\b(revenue|turnover)\b", re.I)
_REVENUE_EXCLUDE_RE = re.compile(r"\bcost\b", re.I)


def _sequential_base_from_earnings_quality(cand: dict) -> Optional[dict]:
    """Build a low_base-shaped input from pass 1's earnings_quality and run it
    through gates.compute_sequential_base — the same arithmetic the gate uses,
    reused rather than re-derived. Returns the compute_sequential_base success
    dict, or None on anything it cannot establish. Silence, never a guess: a
    missing or unparseable extraction must degrade to today's behaviour.

    Deliberately silent (returns None) when the matching revenue entry itself
    carries a named one-off — verified against HSBA.L 9702338's stored
    earnings_quality (2026-08-04), where the Revenue entry ($37.7bn/$34.1bn,
    period "1H26") is tagged one_off_named "net favourable impact of notable
    items of $0.8bn and one-off property asset disposal gain of $0.2bn". A raw
    sequential read of a revenue line the announcement itself says is
    one-off-flattered is not a clean comparison, and the plan's own worked
    example (§5) requires HSBA stay silent for exactly this row. ELIX's
    Revenue entry, by contrast, carries no one_off_named and is a good case.
    This is a fact read off the extraction, not a guess about story
    relevance.
    """
    from gates import compute_sequential_base, _normalize_period

    entries = cand.get("earnings_quality")
    if not isinstance(entries, list):
        return None

    for e in entries:
        if not isinstance(e, dict):
            continue
        item = str(e.get("item") or "")
        if not _REVENUE_ITEM_RE.search(item) or _REVENUE_EXCLUDE_RE.search(item):
            continue
        if str(e.get("one_off_named") or "").strip():
            continue
        period = _normalize_period(e.get("period"))
        if period not in ("H1", "H2"):
            continue
        if _parse_money(e.get("value")) is None or _parse_money(e.get("prior_value")) is None:
            continue

        lb = {
            "period": period,
            "metric": "revenue",
            "current_value": e.get("value"),
            "prior_year_value": e.get("prior_value"),
        }
        base = compute_sequential_base({**cand, "low_base": lb})
        if base.get("ok"):
            return base
    return None


def _sequential_base_context(cand: dict) -> str:
    """Render the Python-computed sequential comparison for the vet prompt, or
    "" when nothing was establishable — the caller omits the whole block
    rather than print an empty header."""
    base = _sequential_base_from_earnings_quality(cand)
    if not base:
        return ""
    ccy = _ccy(cand.get("financial_currency"))
    period = base["period"]
    half_word = "H1" if period == "H1" else "H2"
    preceding_word = "H2" if period == "H1" else "H1"
    direction = "ABOVE" if base["delta_pct"] >= 0 else "BELOW"
    lines = [
        "Sequential comparison (computed by us from figures pass-1 extracted "
        "from this announcement — not by you)",
        f"  {half_word} revenue {_fmt_money_m(base['current_value'], ccy)} is "
        f"{abs(base['delta_pct']):.1f}% {direction} the preceding half.",
    ]
    if base["basis"] == "derived_from_fy_total":
        lines.append(
            f"  Preceding half ({preceding_word}, prior fiscal year) = "
            f"{_fmt_money_m(base['preceding_value'], ccy)}, derived as the "
            f"latest full fiscal year's total revenue minus the prior-year "
            f"{half_word} figure of {_fmt_money_m(base['prior_year_value'], ccy)} "
            f"printed in this announcement."
        )
    lines.append(
        "  If either input looks wrong against the text, say so and disregard "
        "this."
    )
    return "\n".join(lines)


# ── One-off materiality, computed from pass 1 ────────────────────────────────
# Same shape as the sequential base above, and for the same reason. The
# 2026-08-05 review of the `one_off` shadow gate found it had never once told
# us something the vet had not already found by reading the body: of the 7 rows
# it adjudicated, the 3 that also reached the vet were all named in the vet's
# own rationale, same item, same figure ($69m InnovaMatrix, $2.2bn notable
# items). As a gate it is redundant; the vet dominates it wherever a decision
# is actually made, and it cannot in principle see anything the vet could not,
# because it reads a lossy extraction of the body the vet reads whole.
#
# What the vet is NOT reliably good at is the arithmetic. The 2026-07-30 audit
# recorded in _vet_candidate below found 4 of 5 v4-flash rationales drew the
# sequential comparison backwards with correct inputs in front of them, which is
# what motivated handing over the sequential base rather than asking for it —
# see docs/rns-sequential-base-plan.md. Finding a one-off and sizing it
# are different skills: the vet does the first well from prose, Python does the
# second deterministically. So the gate's ratio is handed over as a fact
# instead of being recorded for a promotion decision it was never going to be
# able to inform.
#
# Reuses gates._gate_one_off rather than re-deriving the ratio, so the number
# the vet reads and the number /gates records can never drift apart.
def _one_off_materiality_context(cand: dict) -> str:
    """Render pass 1's quantified named one-offs for the vet prompt, or "" when
    none could be sized — the caller omits the whole block rather than print an
    empty header.

    Only entries the gate actually ADJUDICATED are shown: an unquantified named
    one-off is left to the vet's own reading of the body (it needs no help
    finding those), and a self-referential ~100% ratio is dropped exactly as
    the gate drops it, because "the line IS the one-off" sizes nothing.

    Figures are quoted as the announcement printed them, never re-labelled with
    the database's financial_currency — 167 of 755 companies report in a
    currency that is not the one the announcement quotes, and one-off values
    are parsed straight out of the announcement text.
    """
    from gates import _ONE_OFF_SELF_REFERENTIAL_PP, _gate_one_off

    r = _gate_one_off(cand)
    if r.reason != "adjudicated" or not r.evidence:
        return ""
    real = [
        c for c in (r.evidence.get("computed") or [])
        if abs(c.get("ratio_pct", 100.0) - 100.0) > _ONE_OFF_SELF_REFERENTIAL_PP
    ]
    if not real:
        return ""

    lines = [
        "Named one-off materiality (computed by us from figures pass-1 "
        "extracted from this announcement — not by you)",
    ]
    for c in real:
        period = f" ({c['period']})" if c.get("period") else ""
        lines.append(
            f"  {c['item']}{period}: the announcement credits "
            f"\"{c['one_off_named']}\" to this line — equal to "
            f"{c['ratio_pct']:.1f}% of it."
        )
    lines.append(
        "  If any of these figures looks wrong against the text, say so and "
        "disregard it."
    )
    return "\n".join(lines)


# Verdict/score agreement, enforced in _clean_vet_score AND stated in the prompt
# below — which is why it is defined up here rather than next to its enforcer.
# Both numbers used to be typed out by hand in two prose passages and one JSON
# schema block, and they drifted: see the band comment in _vet_messages.
_VET_VERDICT_SCORE_CAP = {"exclude": 40, "caution": 74}


def _vet_messages(
    cand: dict,
    annual: Optional[list[dict]] = None,
    body_text: Optional[str] = None,
    price_context: Optional[str] = None,
) -> list[dict]:
    # Score bands, derived from the thresholds they have to agree with rather
    # than typed out. The bug this closes: the system prompt called 60-79
    # "positive but carrying a catch a reader must be told" while the JSON block
    # eight lines later called 75+ "you found nothing a reader would need
    # warning about" — a direct contradiction, and it sat exactly on
    # HIGH_IMPACT_MIN_VET_SCORE, the one boundary that decides publication.
    # It drifted there when the publish floor moved off the entry score on
    # 2026-08-03 and only some of the prose followed. Interpolating means the
    # next threshold move cannot reopen it.
    _pub = HIGH_IMPACT_MIN_VET_SCORE
    _ex_cap = _VET_VERDICT_SCORE_CAP["exclude"]
    _ca_cap = _VET_VERDICT_SCORE_CAP["caution"]
    system = (
        "You are a sceptical UK equity analyst vetting positive-looking RNS "
        "announcements for a 1-3 month long showcase of good investment cases. "
        "Your job is to catch positive-FRAMED stories the market may still punish "
        "— e.g. a secondary/overseas listing that fragments liquidity, guidance "
        "quietly cut inside an upbeat results headline, heavy equity dilution, or "
        "profit flattered by one-off/non-cash gains. "
        "Interrogate the growth arithmetic: when headline growth is quoted "
        "year-on-year against a weak, depressed or loss-making base period, work "
        "out what the figure really says — estimate the implied sequential "
        "run-rate versus the immediately preceding half or quarter, not just the "
        "prior-year comparator (e.g. preceding half = full-year total minus the "
        "prior-year half quoted in the announcement). A half reported as 'up 45% "
        "year-on-year' that is actually below the preceding half is a "
        "deceleration dressed as growth, and claims of 'sustained' activity or "
        "momentum deserve extra suspicion when the comparator was the weak "
        "period. Ground every calculation in figures supplied in this context "
        "or quoted in the announcement itself — NEVER fill gaps from your "
        "memory of the company's accounts. If the announcement's headline "
        "metric and the database series are on different bases (e.g. net "
        "operating income vs total revenue), compare like-for-like or say the "
        "comparison isn't clean rather than forcing it. If the base period "
        "cannot be established from the data provided, say so in the rationale "
        "and use low confidence. Where a 'Sequential comparison' block appears "
        "below, it was computed by us from figures already extracted from this "
        "announcement — use it rather than deriving your own sequential read, "
        "and do not mark the score down for an unverifiable sequential trend "
        "on the line it covers. If it looks wrong against the text, say so and "
        "disregard it — it is not authoritative over the announcement itself. "
        "Where it is absent, the instructions above stand and you derive the "
        "comparison yourself. "
        "The same applies to a 'Named one-off materiality' block: we computed "
        "each share, so use the percentage given rather than working out your "
        "own, and if a figure looks wrong against the text say so and "
        "disregard it. Its ABSENCE is not evidence the result is clean — most "
        "named one-offs cannot be sized arithmetically (the announcement has "
        "to print a figure for both the line and the one-off, which only "
        "happens on a minority of them), so a missing block means only that "
        "we could not do the division for you. Keep reading the text for "
        "one-offs yourself exactly as you would if no block appeared, and "
        "never treat silence here as a reason to score up. "
        "Separately, fill the low_base object by COPYING figures as printed — "
        "never calculate the preceding-period base yourself. Identify the "
        "period of the headline figure you are assessing (H1/H2/Q1-Q4) and "
        "which line it is (revenue/operating_income/net_income/other). Copy "
        "the immediately preceding same-length period's figure ONLY if the "
        "announcement prints it directly (e.g. Q1 next to Q2). Separately, "
        "copy the prior-year same-period figure, or the YoY growth percentage "
        "against it, ONLY if the announcement states one of those — never "
        "convert one into the other yourself. Interims routinely print a "
        "two- or three-year comparative table for the same period; where the "
        "figure for the SAME period TWO years earlier is printed, copy that "
        "into prior_year_2_value. It is the one comparison unaffected by "
        "seasonality, so it is what decides the case for a business whose "
        "trading is skewed to one half of the year. Leave any field null "
        "rather than estimating it. Give your own best-effort direction read "
        "(above/below/in_line) against the correct preceding-period base, "
        "not the prior-year figure — this is checked mechanically afterwards, "
        "so a guess is fine. "
        "You are given the forward guidance an earlier automated read pulled "
        "out of this same announcement, one statement per entry. Use it as a "
        "checklist so no guidance statement goes unconsidered, NOT as a "
        "finding: it came from the same model reading the same document, so it "
        "can be wrong or incomplete, and where it disagrees with the text "
        "above, the text wins and you should say so. Two things to weigh. "
        "First, 'vs prior guidance' and 'vs consensus' are independent: "
        "guidance can be reiterated AND below a consensus printed in the same "
        "document, which means the company's own expectation has not moved "
        "while the market's has moved past it — that combination is the "
        "clearest form of the quiet cut you exist to catch, so look hardest "
        "there. Second, 'no_consensus_stated' is the ordinary case and carries "
        "no information in either direction; never read it as evidence that "
        "guidance fails to meet expectations. "
        "You are given the company's market cap. Use it to size things the "
        "announcement states in absolute terms — a placing, a buyback, a "
        "contract win, a write-down — because the same figure is transformative "
        "for a small cap and immaterial for a large one, and 'heavy equity "
        "dilution' cannot be judged without it. Mind the currency note if one "
        "is present. "
        "You are also given the share price move over the 1 and 6 months "
        "BEFORE this announcement. Treat it as context, not as a verdict in "
        "either direction: a stock that has already run may have priced this "
        "in, and a stock that has fallen may be cheap or may be falling for a "
        "reason the announcement does not address. Say which you think it is "
        "only when the announcement gives you grounds — never infer the "
        "reason for a past move from the move itself. "
        "Judge whether this is a genuinely positive near-term investment case, "
        "and express that judgement as a score from 0 to 100. "
        "The score is your CONVICTION that a holder buying on this "
        "announcement is in a good position over the next 1-3 months, having "
        "made every deduction the checks above call for. It is NOT a measure "
        "of how much the share price is likely to move: a large move on a "
        "story you distrust scores LOW, and a modest, well-founded improvement "
        "in a sound business scores well. Anchor it on these bands, which do "
        f"not overlap: {_pub} and above means you would be comfortable putting "
        "this in front of a reader as a good case, with no catch left "
        f"unresolved; 60-{_pub - 1} means positive but carrying a catch the "
        f"reader must be told; {_ex_cap + 1}-59 means unproven — the checks "
        "above could not be completed on the material that decides the case; "
        f"{_ex_cap} and below means the positive framing does not survive the "
        "checks. Fill verdict and rationale FIRST and let them constrain the "
        "number — an 'exclude' verdict cannot carry a score above "
        f"{_ex_cap}, and a 'caution' cannot exceed {_ca_cap}, whatever the "
        "headline says. "
        "Score down for what you could not check, not up: if the announcement "
        "text is unavailable, the base period cannot be established, or the "
        "figures needed are absent, the case is unproven and belongs below 50. "
        "Uncertainty is never a reason to hedge upward. "
        "Return STRICT JSON only."
    )
    seq_block = _sequential_base_context(cand)
    seq_section = f"\n{seq_block}\n" if seq_block else ""
    one_off_block = _one_off_materiality_context(cand)
    one_off_section = f"\n{one_off_block}\n" if one_off_block else ""

    user = f"""Announcement
  Company:    {cand.get('company_name') or '?'} ({cand.get('symbol') or '?'})
  Sector:     {cand.get('sector') or '?'}
  Category:   {cand.get('category') or '?'}
  Headline:   {cand.get('headline')}
  AI thesis:  {cand.get('llm_thesis') or '(none)'}
  AI risks:   {cand.get('llm_risks') or '(none)'}

Investegate AI summary
{cand.get('summary') or '(not available)'}

Announcement text (verbatim, may be truncated) — this is the primary source;
the summary above is a useful lead but can omit or misread material detail
  {body_text if body_text is not None else _vet_body_text(cand)}

Forward guidance, as extracted from THIS announcement by an earlier automated
read of it. Not an independent source — same document, same model, one pass
earlier — so check it against the text above and say so in your rationale if it
is wrong. "no_consensus_stated" is the common case and is NOT evidence that
guidance misses expectations; most announcements print no consensus footnote.
{_guidance_context(cand)}

Company size (from our own database)
{_size_context(cand)}

Share price before this announcement (our own price history; the latest close
predates today's news, so this is what the market already thought)
{price_context if price_context is not None else "  (no price history)"}

Historical annual financials (from our own database, reported in
{_ccy_label(cand.get('financial_currency'))}. NOTE: "revenue" here is TOTAL
revenue, which can differ from the company's preferred headline metric such as
net operating income — compare bases carefully. Check the announcement's own
currency before comparing any figure against this series; a UK-listed company
may report in dollars or euros)
{_annual_lines(annual or [], cand.get('financial_currency'))}
{seq_section}{one_off_section}
Return a JSON object with exactly these fields, IN THIS ORDER — decide the
verdict and write the rationale before you choose the score, so the number
follows the reasoning rather than the reasoning excusing the number:
  verdict     one of: "include" (clean positive case), "caution" (positive but
              with a real catch to check), "exclude" (likely to disappoint)
  confidence  one of: "high", "medium", "low"
  rationale   one or two sentences naming the specific catch, or why it's clean
  score       integer 0-100 — conviction that this is a genuinely positive
              1-3 month investment case, AFTER every deduction above. Not a
              price-move forecast. Must agree with verdict: exclude <= {_ex_cap},
              caution <= {_ca_cap}. A score of {_pub}+ asserts you found no
              catch a reader would still need warning about; 60-{_pub - 1} is
              the band for a positive case that DOES carry such a catch. An
              unreadable announcement or an unestablished base period belongs
              below 50.
  low_base    an object (null fields where not stated — never estimate):
                period                   "H1"|"H2"|"Q1"|"Q2"|"Q3"|"Q4"|null
                metric                   "revenue"|"operating_income"|
                                         "net_income"|"other"|null
                current_value            the headline figure, verbatim AND
                                         WITH ITS UNITS — "£86.5m", never
                                         "86.5". A bare number cannot be
                                         read back and the field is discarded.
                preceding_period_value   immediately preceding same-length
                                         period's figure, ONLY if printed
                prior_year_value         prior-year same-period figure, ONLY
                                         if printed. Units, as above.
                prior_year_2_value       the SAME period TWO years earlier,
                                         ONLY if printed (interims often show
                                         a three-year comparative table) —
                                         never derived, never estimated
                prior_year_growth_pct    YoY growth %, ONLY if printed instead
                                         of an absolute prior figure
                direction                your own read: "above"|"below"|
                                         "in_line"

Return JSON only — no preamble, no code fence."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# Completion budget for the vet, which runs WITH reasoning (see below). The
# answer itself is small — verdict, confidence, one or two sentences, and the
# low_base object — and 450 tokens covered it for a year. Reasoning shares that
# budget, so the old cap would have been spent before the answer started.
#
# Sized off the ranker's measurements rather than guessed: a typical reasoning
# chain on this feed ran ~2,500 tokens and complex large-cap results reached
# 17,000 (see rns_llm._MAX_COMPLETION_TOKENS). The vet sees a truncated body and
# asks a narrower question than the ranker, so 8,000 with the retry at 16,000
# should clear it — but the vet's whole job is the announcements where the
# arithmetic is hard, which are the long ones. Watch the [showcase_vet] line in
# the cron log: a cap is not a target, it bills what is generated.
_VET_MAX_COMPLETION_TOKENS = int(os.environ.get("SHOWCASE_VET_MAX_TOKENS", "8000"))

# DO NOT reach for temperature to make vet_score reproducible — it does nothing
# here. deepseek-v4-flash ignores temperature in thinking mode (confirmed
# 2026-08-05), and this call always runs thinking=True. A `temperature=0` on
# this path would be a no-op that reads like a determinism guarantee.
#
# The noise is real and it matters: vet_score decides publication against a hard
# 75 floor, and on 2026-08-05 the same NXT.L announcement drew
# 70/68/65/65/68/65/45/70 while HSX.L drew 65/48/65/62/45. Since the same day's
# dedupe fix there is exactly one vet per announcement, so that spread now lands
# entirely on a single draw.
#
# The variance is structural, not a sampling setting: the reasoning chain is
# itself sampled, and one divergent token early cascades through arithmetic the
# model is doing in its head. The levers that can actually move it are
#   (a) give the model less to compute — the Python-side one-off materiality
#       (c61f15f) is the first instalment, docs/rns-gate-block-plan.md Phase 4
#       is the rest;
#   (b) sample deliberately — best-of-N with the median recorded, once, at a
#       known cost, rather than the accidental re-vet loop that ran until
#       2026-08-05 and recorded the FIRST draw anyway;
#   (c) stop making a hard threshold arbitrate a noisy number.
# Measure any of them with analysis/rns_body_context_validation.py --repeat,
# never a single sample.


def _clean_vet_score(raw, verdict: Optional[str]) -> Optional[int]:
    """Coerce the vet's score, then enforce the verdict caps in Python.

    The caps are stated in the prompt, but this number now decides whether a
    story is published, so they are re-applied here rather than trusted. The
    failure this guards against is real and documented for this exact model:
    the ranker had to be told "the number must agree with the words" because
    v4-flash writes a dismissive thesis and attaches a mid-range score to it
    (rns_llm._JSON_SCHEMA_BLOCK). Capping is deliberately one-directional — a
    pessimistic score under an 'include' verdict is left alone, since the
    asymmetry here is that publishing a bad story costs more than holding one
    back.

    Returns None on anything unusable. None is NOT zero: it means the vet did
    not produce a judgement, and the caller must not publish on it.
    """
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        score = int(round(float(raw)))
    except (TypeError, ValueError):
        return None
    score = max(0, min(100, score))
    cap = _VET_VERDICT_SCORE_CAP.get(verdict or "")
    if cap is not None and score > cap:
        print(f"[showcase] vet score {score} exceeds '{verdict}' cap {cap} — capped")
        score = cap
    return score


def _vet_candidate(cand: dict, before=None) -> dict:
    """Run the advisory vet. Raises on API/parse failure — the caller treats that
    as non-fatal and stores a NULL verdict. `before` limits the annual series
    for backtests (see _annual_history).

    Runs WITH reasoning since 2026-07-31. This is the one call in the pipeline
    asked to do arithmetic the model cannot copy out of the text: the prompt
    wants a sequential half/quarter comparison, and _annual_lines supplies FY
    totals only, so the subtraction happens in the model's head on every row.
    It got that backwards on 4 of 5 v4-flash rows audited on 2026-07-30 — every
    input figure traced correctly, only the comparison failed. Reasoning is the
    cheap thing to try before Phase 4 moves the subtraction into Python
    (docs/rns-gate-block-plan.md); the two are complements, not alternatives,
    and Phase 4 remains the real fix because a copied field beats a computed one.

    NOT advisory since migration 029 (2026-08-03). Insertion used to be
    hardcoded 'approved', which made a wrong verdict cosmetic — it mislabelled a
    card on /gates. The score this returns now decides publication: >= 75 goes
    live, anything below lands as status='shadow' and is never seen. So a wrong
    verdict here suppresses a real story, which is this system's high-severity
    error. Treat changes to the prompt or the score bands accordingly.

    Scored exactly once per announcement (see the dedupe clause in
    flag_high_impact_candidates) and the result is not reproducible: the same
    row drew 45-75 across one morning. Temperature cannot fix that — see the
    note beside _VET_MAX_COMPLETION_TOKENS before trying.
    """
    from rns_llm import _call_deepseek, _DEEPSEEK_MODEL

    try:
        annual = _annual_history(cand.get("symbol"), before=before)
    except Exception as e:
        # Missing history must never block the vet — it degrades to the
        # announcement-only judgement with the no-data instruction.
        print(f"[showcase] annual history fetch failed (non-fatal) — {e}")
        annual = []

    # Via _call_deepseek for its truncation retry, which this call site did not
    # have and now needs: with reasoning on, an overrun returns an empty string,
    # json.loads raises, and the caller books it as a NULL verdict that looks
    # exactly like an API outage.
    result = _call_deepseek(
        _vet_messages(
            cand,
            annual,
            body_text=_vet_full_text(cand),
            price_context=_price_context(cand.get("symbol"), before=before),
        ),
        thinking=True,
        budget=_VET_MAX_COMPLETION_TOKENS,
        tag="showcase_vet",
    )
    verdict = (result.get("verdict") or "").lower().strip()
    if verdict not in ("include", "caution", "exclude"):
        verdict = None
    return {
        "verdict": verdict,
        "score": _clean_vet_score(result.get("score"), verdict),
        "confidence": (result.get("confidence") or "").lower().strip()[:10] or None,
        "rationale": (result.get("rationale") or "").strip()[:500] or None,
        # Mode suffix for the same reason the ranker stores one: the 2026-07-30
        # audit could only split the failures by model because llm_model recorded
        # it. Without this, "did reasoning fix the arithmetic?" is unanswerable.
        "model": f"{_DEEPSEEK_MODEL}:thinking",
        "low_base": _parse_low_base(result.get("low_base")),
    }


def _parse_low_base(raw) -> dict:
    """Coerce the vet's low_base object — display/gate input only, never
    trusted further than "the model copied this string or number". All
    arithmetic happens in gates._gate_low_base, not here."""
    if not isinstance(raw, dict):
        raw = {}

    def _str(key):
        v = raw.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    growth = raw.get("prior_year_growth_pct")
    return {
        "period": _str("period"),
        "metric": _str("metric"),
        "current_value": _str("current_value"),
        "preceding_period_value": _str("preceding_period_value"),
        "prior_year_value": _str("prior_year_value"),
        # The seasonality-immune comparator — see gates._SEASONAL_WORSENING_PP.
        # Copied like every other field here; the arithmetic on it happens in
        # gates._gate_low_base, never in the model and never in this function.
        "prior_year_2_value": _str("prior_year_2_value"),
        "prior_year_growth_pct": growth if isinstance(growth, (int, float)) else None,
        "direction": _str("direction"),
    }


# ── Guidance gate ─────────────────────────────────────────────────────────────
# Guidance that the company has NOT raised, against a consensus the
# announcement itself prints as higher, is the LUCE 2026-07-28 failure: an
# unchanged ">£40m" that beat consensus in May but sat under the £40.7m
# consensus printed in the same document ten weeks later. LUCE fell 11.8% that
# session after being flagged at 75/positive.
#
# This is a gate on the FACT rather than the score by design. Scoring LUCE 7
# times at temperature 0.2 gave llm_score 75 in 6 runs and 85 in 1 — never once
# below the flag threshold — while ULVR (a genuine +8.7% winner) ranged 45-75
# across its own 7 runs. A ~30-point spread is wider than the 75/80/85 band the
# page gates on, so llm_score alone is not a sound thing to gate on. The
# structured field is far steadier, so the decision is made here in Python,
# deterministically and testably.
#
# Which combination disqualifies, measured rather than assumed. Over those same
# 7 LUCE runs vs_prior was "reiterated" 7/7, but vs_consensus split 4 "below" /
# 3 "in_line" — ">£40m" is a floor and the £40.7m consensus is only 1.75% above
# it, so both labels are defensible and the model cannot be relied on to pick
# one. Gating on "below" alone would therefore fire on barely half the runs.
# Including "in_line" made it fire 7/7 and was defended on its own terms: a
# guide the company has NOT raised, which the announcement's own printed
# consensus shows it does not exceed, is not a positive catalyst. That rule was
# DISARMED on 2026-08-04 and moved to the shadow `guidance_wide` gate — see the
# KLR.L note below. The armed rule is now "below" alone, which means it fires on
# roughly half the LUCE runs rather than 7/7; that is the accepted cost of not
# enforcing an uncalibrated rule, and the shadow gate records what it would
# have done in the meantime.
#
# Still deliberately narrow. "raised" never disqualifies, so ULVR — which
# restates a pre-existing 4-6% range while explicitly upgrading its outlook —
# stays flaggable. "no_consensus_stated" never disqualifies, so the common case
# (no consensus footnote at all) is untouched; this gate only ever fires on
# announcements that printed a consensus figure and failed to clear it.
# "unknown" never disqualifies either: it is the fail-safe value
# _clean_guidance_checks assigns to labels it didn't recognise, so treating it
# as disqualifying would silently drop rows on a parsing miss.
_GUIDANCE_DISQUALIFYING_VS_PRIOR = ("reiterated", "lowered")
_GUIDANCE_DISQUALIFYING_VS_CONSENSUS = ("below",)

# ── The two rules that are NOT armed ──────────────────────────────────────────
# Both were found by the 2026-08-04 audit of that morning's nine llm_score>=60
# rows, and both are recorded by the shadow `guidance_wide` gate rather than
# added to the armed rule above, because §4 of the plan doc is explicit that
# each armed gate compounds the block's aggregate false-block rate and that
# nothing gets armed on n=1.
#
#  1. reiterated/lowered + in_line. Armed until 2026-08-04 on the reasoning
#     quoted above, and it is 8 of the 9 guidance blocks ever recorded — i.e.
#     almost the entire fire rate of this gate rests on a rule no return
#     horizon has ever judged. KLR.L 9702412 is why it came out: it printed
#     "in line with recently UPGRADED market expectations" alongside an H1
#     beat, a raised dividend and a record order book. `vs_consensus: in_line`
#     cannot distinguish a guide reiterated against a consensus just raised to
#     meet it from one reiterated against a stale consensus, and only the
#     latter is the non-catalyst this rule was built on.
#
#  2. below, with any other vs_prior. The vs_prior restriction is what let
#     CLI.L 9702416 through — FY EPS guided 4.6-5.5p against a printed 6.8p
#     consensus, a ~32% miss, labelled `new` because it was the first guide of
#     the year. Guidance that misses a printed consensus is a miss whatever it
#     did relative to prior guidance, but arming that is a widening, and this
#     module widens on evidence.
_GUIDANCE_UNARMED_IN_LINE_VS_PRIOR = ("reiterated", "lowered")
# Rule 2's vs_prior set is enumerated rather than written as "not reiterated or
# lowered", so that "unknown" — the fail-safe _clean_guidance_checks assigns to
# labels it did not recognise — stays out of it. This gate is shadow, so an
# "unknown" firing here could not drop a row today; but it would quietly seed
# the calibration sample with parsing misses, and the promotion criterion reads
# that sample.
_GUIDANCE_UNARMED_BELOW_VS_PRIOR = ("raised", "new")


def _guidance_entries(cand: dict) -> list:
    checks = cand.get("guidance_checks")
    if not isinstance(checks, list):
        return []
    return [e for e in checks if isinstance(e, dict)]


def _guidance_states_consensus(entry: dict) -> bool:
    """Did this entry print a consensus figure to compare against at all?"""
    return entry.get("vs_consensus") not in (None, "no_consensus_stated")


def _disqualifying_guidance(cand: dict) -> Optional[dict]:
    """Return the first guidance entry that should block flagging, else None."""
    for entry in _guidance_entries(cand):
        if (
            entry.get("vs_consensus") in _GUIDANCE_DISQUALIFYING_VS_CONSENSUS
            and entry.get("vs_prior") in _GUIDANCE_DISQUALIFYING_VS_PRIOR
        ):
            return entry
    return None


def _unarmed_disqualifying_guidance(cand: dict) -> Optional[tuple[str, dict]]:
    """First entry an UNARMED guidance rule would disqualify, as (rule, entry).

    Blocks nothing on its own — it feeds the shadow `guidance_wide` gate, and
    it also stops the armed gate reporting `pass` on a row one of these rules
    flags, which is how CLI.L's 32% consensus miss came back as "adjudicated,
    nothing wrong".
    """
    for entry in _guidance_entries(cand):
        vs_c, vs_p = entry.get("vs_consensus"), entry.get("vs_prior")
        if vs_c == "in_line" and vs_p in _GUIDANCE_UNARMED_IN_LINE_VS_PRIOR:
            return "reiterated_in_line", entry
        if (
            vs_c in _GUIDANCE_DISQUALIFYING_VS_CONSENSUS
            and vs_p in _GUIDANCE_UNARMED_BELOW_VS_PRIOR
        ):
            return "below_consensus_other_vs_prior", entry
    return None


# ── Printed-number parsers ────────────────────────────────────────────────────
# earnings_quality stores figures exactly as the announcement printed them, so
# the gate needs to read "£1.4bn", "c.£225m" and "62bps" back into numbers.
# Both parsers return None on anything they don't recognise — never a guess.
# A None propagates into "this entry can't be adjudicated", which fails open,
# and over-blocking is the high-severity error here.
_NUM = r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?"
# Longest suffix first: "million" must not be consumed as "m" + "illion".
_MAG = {
    "trillion": 1e12, "tr": 1e12,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "million": 1e6, "mn": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3,
}
_MAG_ALT = "|".join(sorted(_MAG, key=len, reverse=True))

# Rates only. A percentage EMBEDDED IN PROSE is deliberately NOT converted —
# "increased 38%" is a growth rate, not a loss rate, and reading it as 3,800bps
# would fire the bank gate on an income line's own comparator.
#
# But requiring the bps unit did not "cost nothing", as this comment used to
# claim. Of the 28 bank cost_or_charge lines in the table on 2026-08-01, exactly
# three are rates and only ONE of those printed bps (NWG's loan impairment rate,
# 19 -> 19bps). The other two — LLOY's asset quality ratio and VANQ's cost of
# risk — are printed as percentages by the banks themselves, so the gate simply
# never saw them. Every other line is an absolute £m charge, which is precisely
# the figure this gate exists NOT to fire on. The unit requirement wasn't
# filtering noise, it was filtering out the signal.
#
# So: a percentage is read as a rate only when it is the WHOLE string. That
# keeps "increased 38%" out (it is prose, so it fails the anchor) while letting
# "0.25%" and "(7.0)%" in. Parentheses do not flip the sign — they are the
# accounting convention for a charge, applied to both sides of the pair by the
# announcement, and treating "(7.0)% vs (6.6)%" as -700 vs -660 would invert a
# 40bps DETERIORATION into an improvement. An explicit minus IS honoured, since
# a negative loss rate is a genuine release.
_BPS_RE = re.compile(rf"({_NUM})\s*(?:bps|bp|basis\s+points?)\b", re.I)
_RATE_PCT_RE = re.compile(rf"^\(?\s*({_NUM})\s*\)?\s*%$")
_MONEY_CCY_RE = re.compile(rf"[£$€]\s*({_NUM})\s*({_MAG_ALT})?\b", re.I)
_MONEY_BARE_RE = re.compile(rf"({_NUM})\s*({_MAG_ALT})\b", re.I)


def _parse_bps(s) -> Optional[float]:
    """First basis-point figure in a printed string, else None.

    First rather than last: the model quotes the current figure ahead of its
    comparator ("62bps (H125: 52bps)"), so if it puts the whole clause in
    `value` the leading number is still the one meant.

    A bare percentage — the whole string and nothing else — is converted, since
    that is how UK banks actually print the cost of risk and the asset quality
    ratio. A percentage inside prose is not; see the note above _BPS_RE.
    """
    if not isinstance(s, str):
        return None
    m = _BPS_RE.search(s)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    m = _RATE_PCT_RE.match(s.strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "")) * 100
    except ValueError:
        return None


def _parse_money(s) -> Optional[float]:
    """First money figure in a printed string, in units, else None.

    Handles the forms actually observed in bodies — "£1.4bn", "c.£225m",
    ">£13.7bn", "£0.2bn" — plus a bare magnitude ("1.4bn"). A currency-marked
    figure wins over a bare one, so "up 38% to £1.4bn" reads as 1.4bn rather
    than as the growth rate. Returns None on "increased 38%" and on anything
    else with neither a currency symbol nor a magnitude suffix.
    """
    if not isinstance(s, str):
        return None
    m = _MONEY_CCY_RE.search(s) or _MONEY_BARE_RE.search(s)
    if not m:
        return None
    # A trailing % means the number is a rate, whatever preceded it.
    if s[m.end():].lstrip().startswith("%"):
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value * _MAG.get((m.group(2) or "").lower(), 1.0)


# ── Earnings-quality gate ─────────────────────────────────────────────────────
# The BARC 2026-07-28 failure mode, which the guidance gate above cannot reach
# by construction: guidance genuinely WAS raised, so no guidance label
# disqualifies, while the reported numbers underneath were partly non-repeating
# (a c.£225m disposal gain inside "USCB income increased 38%") against a loan
# loss rate that had gone 52 -> 62bps. The stock fell 5.5% that day; scored 7
# times the announcement came back [55, 60, 65, 75, 80, 80, 80], positive 7/7,
# four runs clearing the flag threshold. It is not an edge case either: on
# 2026-07-29, 68 of 75 guidance_checks entries batch-wide were
# "no_consensus_stated", which is the only state in which the guidance gate can
# do nothing at all.
#
# Gate on the loan loss RATE, not the absolute impairment charge. Any bank
# growing its loan book grows impairments, so £1.1bn -> £1.4bn is evidence of
# nothing on its own; the LLR is already normalised for book size, which is why
# banks report it. That distinction is the whole reason the rule is
# bank-branched, and it belongs here in Python where it is written once and
# unit-tested, not in a prompt where it is re-derived every morning against a
# 25-point score spread.
#
# PROVISIONAL threshold — now fitted on n=4, which is better than the n=1 it
# started at and still not a calibration. Every bank rate pair we can read:
#
#   BARC H1 2026 loan loss rate      52 -> 62bps   +10   fell 5.5%   want block
#   BARC Q2 2026 loan loss rate      44 -> 51bps    +7   (same day)  want block
#   NWG  H1 2026 loan impairment     19 -> 19bps     0   +1.4%       want pass
#   LLOY H1 2026 asset quality ratio 0.19 -> 0.25%  +6   +5.6%       want pass
#   VANQ H1 2026 cost of risk        6.6 -> 7.0%   +40   -17.0%      want block
#
# 7 is the only value that gets all five right, and it lands exactly on an
# observation with no margin either side — so treat it as a stopgap, not a
# finding. It cannot go higher without losing BARC's Q2 window, and the
# enumeration is not stable run to run (2 to 7 entries across 7 BARC runs), so
# relying on H1 being the one enumerated is not safe.
#
# The LLOY row is the interesting one and argues this metric may be wrong. Its
# AQR rose 32% in relative terms — a bigger relative move than BARC's — and the
# stock still rose 5.6%, because 0.19% is an exceptionally benign base and the
# rest of the result was strong (RoTE 14.1 -> 17.1%). A pure delta-in-bps rule
# cannot tell "+6bps off a trivial base" from "+6bps off a stressed one". If a
# fifth observation breaks the fit, add a floor on the LEVEL rather than nudging
# this number again.
_BANK_LLR_RISE_BPS = 7


def _worsening_loss_rate(cand: dict) -> Optional[dict]:
    """Return the earnings_quality entry that should block flagging, else None.

    Bank-only. Every ambiguous path returns None: not a bank, no array, a
    `kind` the ranker couldn't classify ("unclear"), a missing period, or a
    figure neither side of which parses as basis points. Dropping a tradeable
    announcement is the high-severity error in this system, so the gate only
    ever fires on a fully-read pair.
    """
    from quality import classify_risk_model

    # unknown_is_trust=False for the same reason the RNS ranker passes it:
    # company_metadata is a LEFT JOIN, so absent sector/industry means the
    # ticker is outside our universe, not that it is a closed-end fund.
    if classify_risk_model(cand, unknown_is_trust=False) != "bank":
        return None
    entries = cand.get("earnings_quality")
    if not isinstance(entries, list):
        return None
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("kind") != "cost_or_charge":
            continue
        # Without a period there is no way to know a half-year figure isn't
        # being compared against a quarter — the body prints both, a few
        # hundred chars apart. str() because this reads stored JSON, which is
        # only as well-shaped as the cleaner that wrote it, and this runs in
        # the morning cron.
        if not str(e.get("period") or "").strip():
            continue
        cur, prior = _parse_bps(e.get("value")), _parse_bps(e.get("prior_value"))
        if cur is None or prior is None:
            continue
        if cur - prior >= _BANK_LLR_RISE_BPS:
            return e
    return None


def _named_one_offs(cand: dict) -> list[dict]:
    """Income lines the announcement itself credits to a named non-repeating
    item. Reported, never gated on.

    Judging materiality would need the one-off as a share of the growth, and
    the base is not reliably printed in comparable form — "c.£225m" against
    "increased 38%" is not a computation. A named, quoted fact is worth
    surfacing to a reader even unquantified; it is not sound enough to block.

    Deliberately kept alongside gates.py's `one_off` shadow gate rather than
    folded into it (docs/rns-one-off-gate-plan.md §7.6): this prints
    immediately to the cron log for the rows that reached flagging, which is
    cheaper and faster to read than /gates; the gate is the calibratable
    record over every ranked row, income AND cost_or_charge, that this
    income-only print was never meant to be.
    """
    entries = cand.get("earnings_quality")
    if not isinstance(entries, list):
        return []
    return [
        e
        for e in entries
        if isinstance(e, dict)
        and e.get("kind") == "income"
        and str(e.get("one_off_named") or "").strip()
    ]


# ── FX for the leverage floor ─────────────────────────────────────────────────
# TWO tiers, because the in-memory one alone is a narrower guarantee than it
# looks: the RNS cron is `docker exec ... python run_rns.py`, a fresh process
# every 15 minutes, so a module-level dict never survives between runs.
#
#   1. in-memory — kills the repeat calls WITHIN a run. _build_messages asks per
#      ranked candidate, so the 36-candidate 06:04 run would otherwise pay 36x.
#   2. on-disk — carries the rates ACROSS runs. Without it every cron run paid a
#      cold ~3.4s Yahoo fetch (measured on the VPS 2026-08-06), most of them on
#      runs with no candidates to filter at all.
#
# Same snapshot dir as market.py, which is the Dokploy /data volume in prod, so
# the cron exec and the uvicorn workers share one file. Best-effort throughout:
# a snapshot failure costs a refetch, never a wrong rate.
#
# Steady state is ~9 Yahoo requests per refresh (1 crumb handshake + 2 chart
# calls per pair — fast_info makes two) at 2-4 refreshes/day. The failure path
# is the one that could actually get us rate-limited, hence the backoff below.
_FX_SNAPSHOT_DIR = os.environ.get(
    "MARKET_SNAPSHOT_DIR",
    os.path.join(tempfile.gettempdir(), "finscope_market_cache"),
)
_FX_SNAPSHOT_PATH = os.path.join(_FX_SNAPSHOT_DIR, "fx_to_gbp.json")

_FX_CACHE: dict = {"rates": None, "at": None}
_FX_TTL_SECONDS = 6 * 3600

# Currencies with no Yahoo cross pair. Purely an optimisation: GELGBP=X 404s in
# ~0.56s on every single run and logs a line each time, and the 3 GEL reporters
# already lose the check either way (a missing rate is unevaluable, see below).
# Deleting this set costs a wasted call, never correctness — so if Yahoo ever
# lists the pair, drop the code and it starts working.
_FX_NO_YAHOO_PAIR = {"GEL"}

# Negative cache. Without it a Yahoo outage means EVERY cron run retries — ~16
# runs/day x 9 requests, i.e. we'd hit Yahoo hardest exactly when it is already
# refusing us. After a total failure, wait this long before calling again.
#
# Must be well ABOVE the 15-minute cron interval to be worth anything: at 30
# minutes it only skipped every other run (measured: 8 attempts per 16 runs, a
# 2x cut). At 2h a full-day outage costs a handful of attempts instead of 16.
# Retrying eagerly buys nothing here, because the stale rates below keep the
# check running throughout — so the only thing fast recovery gains is slightly
# fresher numbers on a comparison that tolerates day-old rates fine.
_FX_FAIL_BACKOFF_SECONDS = 2 * 3600

# During that wait, keep serving the last known rates even though they are past
# the 6h TTL. FX moves ~1%/day and this only feeds a net-debt-vs-market-cap
# test whose contested band is 1.0-1.27, so a day-old rate is far better than
# no rate. Bounded, because "stale" has to stop meaning "usable" eventually.
_FX_STALE_MAX_SECONDS = 7 * 24 * 3600


def _fx_read_blob() -> Optional[dict]:
    """Raw snapshot file, or None. Kept separate from the freshness rules so a
    failure marker can live alongside rates that are stale but still usable."""
    try:
        if not os.path.exists(_FX_SNAPSHOT_PATH):
            return None
        with open(_FX_SNAPSHOT_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(f"[showcase] fx snapshot load failed — {e}")
        return None


def _fx_blob_rates(blob: Optional[dict]) -> tuple[Optional[dict], float]:
    """(rates, age_seconds) from a raw blob. Rates without sterling are treated
    as corrupt, not stale — trusting them would drop the check for every GBP
    reporter, which is the one group that never needed a rate at all."""
    if not blob:
        return None, 0.0
    try:
        rates = {str(k): float(v) for k, v in (blob.get("rates") or {}).items()}
        if rates.get("GBP") != 1.0:
            return None, 0.0
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(blob["at"])
        ).total_seconds()
        return rates, age
    except Exception:
        return None, 0.0


def _fx_load_snapshot() -> Optional[dict]:
    """Rates from the shared snapshot if still inside the TTL, else None."""
    rates, age = _fx_blob_rates(_fx_read_blob())
    return rates if rates and age < _FX_TTL_SECONDS else None


def _fx_in_backoff(blob: Optional[dict]) -> bool:
    """True while a recent total failure should stop us calling Yahoo again."""
    try:
        failed_at = (blob or {}).get("failed_at")
        if not failed_at:
            return False
        since = (
            datetime.now(timezone.utc) - datetime.fromisoformat(failed_at)
        ).total_seconds()
        return since < _FX_FAIL_BACKOFF_SECONDS
    except Exception:
        return False


def _fx_write_blob(blob: dict) -> None:
    try:
        os.makedirs(_FX_SNAPSHOT_DIR, exist_ok=True)
        tmp = _FX_SNAPSHOT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(blob, fh)
        os.replace(tmp, _FX_SNAPSHOT_PATH)  # atomic on POSIX
    except Exception as e:
        print(f"[showcase] fx snapshot save failed — {e}")


def _fx_save_snapshot(rates: dict) -> None:
    """Persist good rates and clear any failure marker."""
    _fx_write_blob({"at": datetime.now(timezone.utc).isoformat(), "rates": rates})


def _fx_record_failure(blob: Optional[dict]) -> None:
    """Stamp the backoff, PRESERVING whatever rates are already on file so the
    outage window can keep serving them."""
    out = dict(blob or {})
    out["failed_at"] = datetime.now(timezone.utc).isoformat()
    _fx_write_blob(out)


def _fx_to_gbp() -> dict:
    """Rates converting each reporting currency in the universe into GBP.

    Exists for ONE comparison — the `net debt > market cap` leverage floor —
    because those two columns are in different currencies and nothing else in
    this file may form a cross-currency ratio (see _size_context: the vet is
    explicitly told to refuse the comparison rather than guess a rate).

    ttm_financials.net_debt is in the company's REPORTING currency; market_cap
    is in GBP. Comparing them raw judged every dollar filer too harshly by the
    FX rate — Harbour Energy's $4.42bn net debt read as 1.21x its £3.66bn cap
    when the true ratio is ~0.96 (found 2026-08-06). 138 of 755 companies
    report in a non-GBP currency, so this is not an edge case.

    Callers MUST treat a MISSING rate as "this check cannot be evaluated"
    rather than as a pass or a fail — that matches the surrounding floors,
    which leave names with missing data in. Yahoo's 'GBP=X' convention is
    USD->GBP, and the cross pairs are '<CCY>GBP=X'.

    GBP is therefore seeded first and returned even when everything else
    fails: sterling reporters (617 of 755) need no rate, so a Yahoo outage
    must not cost them a check that was never cross-currency. Only the names
    genuinely needing a conversion lose it.

    GBP and GBp both map to 1.0: the 'GBp' quote code is a unit label only and
    the stored market cap is already in whole pounds, not pence.

    Reads memory, then the shared snapshot, then Yahoo — see the tier notes
    above the cache constants for why a process-local dict is not enough.

    On failure it backs off for 30 minutes and keeps serving the last known
    rates (bounded at 7 days) rather than retrying every run, so an outage
    degrades quietly instead of turning into a retry storm against a host that
    is already refusing us.
    """
    now = datetime.now(timezone.utc)
    cached, at = _FX_CACHE["rates"], _FX_CACHE["at"]
    if cached is not None and at and (now - at).total_seconds() < _FX_TTL_SECONDS:
        return cached

    # Tier 2: a snapshot from another process (usually an earlier cron run).
    blob = _fx_read_blob()
    stored, age = _fx_blob_rates(blob)
    if stored and age < _FX_TTL_SECONDS:
        # Fresh. Seeds this process's memory so the rest of the run is free.
        _FX_CACHE["rates"], _FX_CACHE["at"] = stored, now
        return stored

    def _degraded() -> dict:
        """What to serve without a successful fetch. Deliberately NOT written
        to the memory cache: that slot means "fresh for 6h", and holding a
        stale or sterling-only result there would suppress the retry once the
        backoff expires."""
        if stored and age < _FX_STALE_MAX_SECONDS:
            print(f"[showcase] fx using stale rates ({age / 3600:.1f}h old)")
            return stored
        return {"GBP": 1.0}

    # Tier 3 gate: a recent total failure means don't call Yahoo yet.
    if _fx_in_backoff(blob):
        return _degraded()

    rates = {"GBP": 1.0}
    try:
        codes = [
            (r.get("code") or "").upper().strip()
            for r in _q(
                "SELECT DISTINCT upper(trim(financial_currency)) AS code"
                " FROM company_metadata WHERE financial_currency IS NOT NULL"
            )
        ]
        wanted = sorted(
            {c for c in codes if c and c != "GBP" and c not in _FX_NO_YAHOO_PAIR}
        )
        if wanted:
            import yfinance as yf  # deferred — only this fetch path needs it

            for code in wanted:
                ticker = "GBP=X" if code == "USD" else f"{code}GBP=X"
                try:
                    fi = yf.Ticker(ticker).fast_info
                    last = fi.get("lastPrice") or fi.get("previousClose")
                    if last and float(last) > 0:
                        rates[code] = float(last)
                except Exception as e:
                    # One bad pair must not cost the others their rate.
                    print(f"[showcase] fx rate {ticker} unavailable — {e}")
    except Exception as e:
        # Non-fatal by design: sterling names keep the check, foreign ones
        # fall back to stale rates or lose it for this run.
        print(f"[showcase] fx lookup failed — {e}")
        _fx_record_failure(blob)
        return _degraded()

    if len(rates) > 1:
        # A real rate resolved. Cache, and clear any failure marker.
        _FX_CACHE["rates"], _FX_CACHE["at"] = rates, now
        _fx_save_snapshot(rates)
        return rates

    # Reached Yahoo but resolved nothing — every pair failed. Same treatment as
    # an outright exception: back off, and keep serving what we already had.
    # Never persist the sterling-only dict as if it were good rates.
    print("[showcase] fx resolved no rates — backing off")
    _fx_record_failure(blob)
    return _degraded()


# ── Auto-flag ─────────────────────────────────────────────────────────────────
def flag_high_impact_candidates(hours: int = 48) -> dict:
    """Flag rules-passing candidates from the last `hours` straight onto the
    approved (public) showcase. Advisory-vets each and snapshots the story.
    Idempotent via the rns_id unique constraint, and each announcement is
    vetted exactly once (a failed vet call being the one retryable case) — the
    cron re-runs this every 15 minutes over a 48h window, so anything else
    re-pays for the same LLM verdict dozens of times. Returns a counts dict for
    cron logs."""
    # Parallel arrays rather than a dict: psycopg2 adapts Python lists straight
    # to the two Postgres arrays the unnest() below zips back into rows.
    _fx = _fx_to_gbp()
    _fx_codes = list(_fx.keys())
    _fx_rates = [_fx[c] for c in _fx_codes]

    cands = _q(
        """
        SELECT r.id, r.symbol, r.company_name, r.headline, r.url, r.published_at,
               r.tier, r.category, r.score, r.keyword_hits, r.summary,
               r.body, r.body_is_stub,
               r.llm_score, r.llm_confidence, r.llm_thesis, r.llm_risks, r.llm_action,
               r.llm_sentiment, r.guidance_checks, r.earnings_quality,
               -- The ranker's own forward-profit extraction (migration 032) and
               -- the model that produced it; showcase_fwd.fwd_from_ranker turns
               -- the pair into the multiple without spending a call.
               r.fwd_profit, r.llm_model,
               m.sector, m.industry, m.country, m.ftse_index,
               -- Two DIFFERENT currencies, both needed by the vet prompt and
               -- easy to confuse (see _size_context): financial_currency is the
               -- accounts' reporting currency (USD for Shell/BP/AZN) and drives
               -- the annual series; currency is the QUOTE currency and is what
               -- market_cap below is denominated in.
               m.financial_currency, m.currency,
               t.market_cap, t.net_debt
        FROM rns_announcements r
        JOIN ttm_financials t ON t.company_symbol = r.symbol
        LEFT JOIN company_metadata m ON m.symbol = r.symbol
        -- True industry-peer margin median: trusts, banks and resellers each get
        -- judged against their own economics rather than a whole-sector blend
        -- (the Financial Services sector median is trust-inflated to ~0.70).
        -- Yields NULL — and so falls back to the absolute floor — when the
        -- industry has too few names for a meaningful median.
        LEFT JOIN LATERAL (
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY t2.net_income_margin)
                       AS margin_median
            FROM ttm_financials t2
            JOIN company_metadata m2 ON m2.symbol = t2.company_symbol
            WHERE m2.industry = m.industry
              AND t2.net_income_margin IS NOT NULL
            HAVING COUNT(*) >= %s
        ) pm ON TRUE
        -- Rate turning this company's REPORTING currency into GBP, so net debt
        -- can be compared against a GBP market cap below. NULL when the rate is
        -- unavailable, which deliberately makes that one check unevaluable
        -- rather than guessing — see _fx_to_gbp.
        LEFT JOIN LATERAL (
            SELECT f.rate
            FROM unnest(%s::text[], %s::numeric[]) AS f(code, rate)
            WHERE f.code = upper(trim(COALESCE(m.financial_currency, 'GBP')))
        ) fx ON TRUE
        WHERE r.symbol IS NOT NULL
          AND r.llm_processed_at IS NOT NULL
          AND r.llm_score >= %s
          AND r.llm_action IN ('watch', 'research')
          AND r.tier IN ('A', 'B')
          AND r.category = ANY(%s)
          AND r.published_at >= NOW() - (%s || ' hours')::interval
          AND t.market_cap >= %s
          -- Leverage floor: drop over-indebted names. Excludes net debt > 3x
          -- EBITDA, indebted names with no profit to service it, and net debt
          -- that exceeds the market cap. Missing net_debt data is left in.
          --
          -- The first two tests are same-currency (net debt and EBITDA are both
          -- reporting-currency) and so need no conversion. The third is NOT:
          -- market_cap is GBP while net_debt is the reporting currency, so it
          -- converts first. Without that it read every dollar filer as ~1.27x
          -- more indebted than it is. A NULL rate leaves the third test NULL,
          -- the OR-chain yields NULL when the other two are false, and the
          -- COALESCE keeps the name — i.e. an unavailable rate skips this one
          -- check instead of silently excluding or admitting the company. The
          -- other two leverage tests still apply, so it is never unguarded.
          AND NOT COALESCE(
              (t.ebitda > 0 AND t.net_debt > %s * t.ebitda)
              OR (t.ebitda <= 0 AND t.net_debt > 0)
              OR (t.net_debt * fx.rate > t.market_cap),
              FALSE
          )
          -- Quality floor, peer-relative: require profitability at or above the
          -- industry-median net margin, and never loss-making — so thin-margin
          -- industries aren't blanket-banned but below-par names within them are.
          -- Falls back to an absolute floor when no usable peer median exists;
          -- missing margin data is left in. Escape hatch: a profitable name with
          -- strong capital returns passes even below the margin median — a
          -- low-margin/high-ROCE model (reseller, distributor) is structure,
          -- not fragility. Loss-makers and over-levered names never pass via
          -- the hatch (margin > 0 here, leverage floor above).
          --
          -- The hatch reads ROCE *or* ROIC (2026-08-12). ROCE alone punishes a
          -- cash-rich or investment-portfolio balance sheet for holding assets
          -- that earn no EBIT; ROIC nets the cash off. See HIGH_IMPACT_MIN_ROIC
          -- for why the shared 0.15 threshold is tight rather than loose.
          -- NULL handling is unchanged: one NULL return leaves the other to
          -- decide (NULL OR TRUE = TRUE), and both NULL yields NULL, so the
          -- row still needs the margin branch to survive.
          AND (
              t.net_income_margin IS NULL
              OR t.net_income_margin >= GREATEST(0, COALESCE(pm.margin_median, %s))
              OR (t.net_income_margin > 0 AND (t.roce >= %s OR t.roic >= %s))
          )
          -- Dedupe on PUBLISHED history only. A shadow row (vetted, scored
          -- below the publish floor) must not suppress the same symbol's next
          -- announcement: since 2026-08-03 the vet sees the 60-74 band, so
          -- without this exclusion a company scoring 62 on Monday would lock
          -- itself out of a 90 on Wednesday for a month. Dropping a tradeable
          -- announcement is this system's high-severity error.
          AND NOT EXISTS (
              SELECT 1 FROM high_impact_rns h
              WHERE h.symbol = r.symbol
                AND h.status <> 'shadow'
                AND h.flagged_at >= NOW() - (%s || ' days')::interval
          )
          -- ONE VET PER ANNOUNCEMENT. The clause above intentionally lets a
          -- shadow row back into the pool so it can't lock out its symbol —
          -- but nothing there stops the SAME rns_id being re-selected, so
          -- until 2026-08-05 every already-vetted candidate was re-vetted on
          -- every run for the whole `hours` window: ~8 reasoning-heavy calls
          -- per 15-minute run, all of them discarded by the ON CONFLICT below.
          -- Worse than the cost, it made publication a lottery — the vet is
          -- not reproducible on identical input (HSX.L scored 65/48/65/62/45
          -- across one morning), and on 2026-08-05 07:30 NXT.L rolled a 75 on
          -- its sixth re-vet, paid for the fwd extraction, then vanished into
          -- ON CONFLICT DO NOTHING against its own 06:09 shadow row.
          -- Scored once, the row is done: its verdict is stored and the INSERT
          -- could not update it anyway. A NULL vet_score is the exception —
          -- that means the CALL FAILED, not that the story is weak, so it
          -- stays eligible and the conflict clause below lets the retry land.
          AND NOT EXISTS (
              SELECT 1 FROM high_impact_rns h2
              WHERE h2.rns_id = r.id
                AND h2.vet_score IS NOT NULL
          )
        ORDER BY r.llm_score DESC
        """,
        (
            PEER_MARGIN_MIN_GROUP,
            _fx_codes,
            _fx_rates,
            HIGH_IMPACT_VET_ENTRY_SCORE,
            list(HIGH_IMPACT_CATEGORIES),
            hours,
            HIGH_IMPACT_MIN_MARKET_CAP,
            HIGH_IMPACT_MAX_NET_DEBT_TO_EBITDA,
            HIGH_IMPACT_MIN_NET_MARGIN,
            HIGH_IMPACT_MIN_ROCE,
            HIGH_IMPACT_MIN_ROIC,
            HIGH_IMPACT_DEDUPE_DAYS,
        ),
    )

    from gates import GATES, blocking_reason, record_low_base_evaluation

    flagged = 0
    counts = {g.name: 0 for g in GATES}
    vetted = 0
    shadowed = 0
    for c in cands:
        # Gate order is the registry's evaluation order (sentiment, guidance,
        # earnings_quality) — same short-circuit as before the registry
        # existed, so a disqualified row still costs no LLM vet call.
        blocked = blocking_reason(c)
        if blocked:
            gate, result = blocked
            counts[gate.name] = counts.get(gate.name, 0) + 1
            print(
                f"[showcase] {c['symbol']} not flagged — gate={gate.name} "
                f"reason={result.reason} evidence={result.evidence}"
            )
            continue

        # Not a gate — see _named_one_offs. Logged so a flagged row's headline
        # growth can be read against what the company said drove it.
        for one_off in _named_one_offs(c):
            print(
                f"[showcase] {c['symbol']} one-off named in "
                f"{one_off.get('period')} {one_off.get('item')} "
                f"({one_off.get('value')}): {one_off.get('one_off_named')}"
            )

        story_close = _story_close(c["symbol"], c["published_at"])
        try:
            vet = _vet_candidate(c)
            vetted += 1
        except Exception as e:
            print(f"[showcase] vet failed for {c['symbol']} (non-fatal) — {e}")
            vet = None

        # Gate-block Phase 4 (docs/rns-gate-block-plan.md) — shadow-evaluate
        # low_base on this candidate now, while its vet output is in hand.
        # This gate's evaluation pool is the vet's pool, not the wide Tier A/B
        # sweep record_gate_evaluations runs in the morning cron, because it
        # needs fields only the vet call produces. Shadow mode: the GATE'S
        # verdict never blocks the flag below. The raw dict itself IS also
        # saved onto the INSERT below (migration 028) — the gate's own
        # evidence only survives on rows it manages to adjudicate, so without
        # this the model's extraction would be unrecoverable on every n/a exit.
        low_base = (vet or {}).get("low_base")
        try:
            record_low_base_evaluation(c["id"], {**c, "low_base": low_base})
        except Exception as e:
            print(f"[showcase] low_base gate recording failed (non-fatal) — {e}")

        # ── Publish decision ────────────────────────────────────────────────
        # The vet's score, not the ranker's, decides what reaches the public
        # page (migration 029). A row that cleared the entry floor but not this
        # one is still stored — status='shadow' — because the 60-74 band is the
        # only evidence base for calibrating this threshold and it cannot be
        # reconstructed later: rns_announcements rows are pruned, so a
        # retrospective re-vet is impossible.
        #
        # A NULL vet_score means the vet call FAILED, not that the story is
        # weak. It must not publish on a number that was never produced, so it
        # lands as shadow and is visible in the cron log as a vet failure
        # above. This is the one behaviour change that can silently lose a good
        # story — previously a failed vet still flagged with a NULL verdict.
        vet_score = (vet or {}).get("score")
        publish = vet_score is not None and vet_score >= HIGH_IMPACT_MIN_VET_SCORE
        status = "approved" if publish else "shadow"
        if not publish:
            shadowed += 1
            print(
                f"[showcase] {c['symbol']} shadowed — vet_score="
                f"{vet_score if vet_score is not None else 'NULL (vet failed)'} "
                f"< {HIGH_IMPACT_MIN_VET_SCORE} (llm_score={c['llm_score']}, "
                f"verdict={(vet or {}).get('verdict')})"
            )

        # Forward multiple: the RANKER extracted the stated FY profit figure in
        # its own scoring call (migration 032), Python computes EV/multiple off
        # it here. Internally non-fatal — a blank column must never block a
        # flag.
        #
        # This used to run only `if publish:`, because it was a second DeepSeek
        # call plus its own Investegate fetch and paying that on the ~80% of
        # candidates that never publish was pure waste. That gate is what left
        # every row of /high-impact-rns/archive — which is nothing BUT shadow
        # rows — with a blank multiple. Reading the ranker's extraction costs
        # nothing per row, so the gate is gone and shadow rows get the column
        # too.
        from showcase_fwd import fwd_from_ranker
        fwd = fwd_from_ranker(c)
        if fwd is None:
            # No ranker extraction: this row was scored before 032 shipped, or
            # its ranking call failed. processed=False leaves fwd_processed_at
            # NULL, which keeps the row eligible for the /extract-fwd backfill
            # — the one remaining caller of the old two-call extractor.
            from showcase_fwd import _empty as _empty_fwd
            fwd = _empty_fwd(processed=False)

        n = _exec(
            """
            INSERT INTO high_impact_rns
                (rns_id, symbol, company_name, headline, url, published_at, tier,
                 category, rules_score, keyword_hits, summary, llm_score,
                 llm_confidence, llm_thesis, llm_risks, story_close,
                 vet_verdict, vet_confidence, vet_rationale, vet_model, vet_processed_at,
                 vet_score, low_base,
                 fwd_metric, fwd_value, fwd_currency, fwd_period, fwd_basis,
                 fwd_is_bound, fwd_quote, fwd_ev, fwd_multiple, fwd_model,
                 fwd_processed_at,
                 status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s)
            -- Only ONE conflict can now reach here: a row whose earlier vet
            -- call FAILED (vet_score NULL, stored as shadow) and which the
            -- candidate SQL therefore kept eligible for a retry. Let that
            -- retry land — test_flag_vet_failure_shadows_instead_of_publishing
            -- has always promised "a re-vet can promote it", and under DO
            -- NOTHING that was never true: a DeepSeek outage during the
            -- morning batch withheld the story permanently. The WHERE makes
            -- this unreachable for a row that already has a score, so a stored
            -- verdict is still immutable.
            ON CONFLICT (rns_id) DO UPDATE SET
                vet_verdict = EXCLUDED.vet_verdict,
                vet_confidence = EXCLUDED.vet_confidence,
                vet_rationale = EXCLUDED.vet_rationale,
                vet_model = EXCLUDED.vet_model,
                vet_processed_at = EXCLUDED.vet_processed_at,
                vet_score = EXCLUDED.vet_score,
                low_base = EXCLUDED.low_base,
                fwd_metric = EXCLUDED.fwd_metric,
                fwd_value = EXCLUDED.fwd_value,
                fwd_currency = EXCLUDED.fwd_currency,
                fwd_period = EXCLUDED.fwd_period,
                fwd_basis = EXCLUDED.fwd_basis,
                fwd_is_bound = EXCLUDED.fwd_is_bound,
                fwd_quote = EXCLUDED.fwd_quote,
                fwd_ev = EXCLUDED.fwd_ev,
                fwd_multiple = EXCLUDED.fwd_multiple,
                fwd_model = EXCLUDED.fwd_model,
                fwd_processed_at = EXCLUDED.fwd_processed_at,
                status = EXCLUDED.status
            WHERE high_impact_rns.vet_score IS NULL
            """,
            (
                c["id"], c["symbol"], c["company_name"], c["headline"], c["url"],
                c["published_at"], c["tier"], c["category"], c["score"],
                c["keyword_hits"], c["summary"], c["llm_score"], c["llm_confidence"],
                c["llm_thesis"], c["llm_risks"], story_close,
                (vet or {}).get("verdict"), (vet or {}).get("confidence"),
                (vet or {}).get("rationale"), (vet or {}).get("model"),
                datetime.now(timezone.utc) if vet else None,
                vet_score,
                Json(low_base) if low_base is not None else None,
                fwd["fwd_metric"], fwd["fwd_value"], fwd["fwd_currency"],
                fwd["fwd_period"], fwd["fwd_basis"], fwd["fwd_is_bound"],
                fwd["fwd_quote"], fwd["fwd_ev"], fwd["fwd_multiple"],
                fwd["fwd_model"], fwd["fwd_processed_at"],
                status,
            ),
        )
        # `flagged` counts PUBLISHED rows only — it is what the cron log and the
        # /status card report, and a shadow row is not a flag.
        if publish:
            flagged += n

    return {
        "candidates": len(cands),
        "flagged": flagged,
        # Legacy key names, mapped from the gate registry so callers (and
        # test_showcase.py) don't need to know gate names changed underneath.
        "skipped_sentiment": counts.get("sentiment", 0),
        "skipped_guidance": counts.get("guidance", 0),
        "skipped_earnings_quality": counts.get("earnings_quality", 0),
        "vetted": vetted,
        # Vetted but below the publish floor. Watch this against `flagged`: the
        # threshold is uncalibrated (the vet had never emitted a score before
        # migration 029), so the split is the first evidence of whether 75 is
        # in the right place on the NEW scale.
        "shadowed": shadowed,
    }


# ── Follow-up recorder ────────────────────────────────────────────────────────
def record_followups() -> dict:
    """Snapshot subsequent tier A/B announcements for every actively tracked
    company, so post-selection news survives even the (now Tier-C-only)
    14-day source prune."""
    active = _q(
        "SELECT id, rns_id, symbol, published_at FROM high_impact_rns "
        "WHERE status IN ('pending', 'approved')"
    )
    inserted = 0
    for e in active:
        newer = _q(
            """
            SELECT id, headline, url, published_at, tier, category, keyword_hits,
                   llm_score, llm_thesis, llm_sentiment
            FROM rns_announcements
            WHERE symbol = %s AND published_at > %s AND id <> %s AND tier IN ('A', 'B')
            """,
            (e["symbol"], e["published_at"], e["rns_id"]),
        )
        for a in newer:
            inserted += _exec(
                """
                INSERT INTO high_impact_rns_followups
                    (showcase_id, rns_id, headline, url, published_at, tier,
                     category, llm_score, sentiment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (showcase_id, rns_id) DO NOTHING
                """,
                (
                    e["id"], a["id"], a["headline"], a["url"], a["published_at"],
                    a["tier"], a["category"], a["llm_score"], _sentiment(a),
                ),
            )
    return {"active": len(active), "inserted": inserted}


# ── Enrichment ────────────────────────────────────────────────────────────────
# MQVR source — copied from the /api/screener SELECT (main.py) so quality/value
# scoring sees the exact same columns (incl. the stored *_median companions).
# m.name and s.risk_model are load-bearing, not decoration: effective_model()
# keys the trust branch of _value_score and the trust blanking in
# _scrub_screener_metrics off them. Without the name this SELECT classified 108
# funds (Scottish Mortgage, City of London, F&C, …) as ordinary asset managers,
# so the company page and this showcase scored them on operating-company rules
# while the screener scored the same rows as trusts.
_MQVR_SQL = """
    SELECT m.symbol, m.name, m.sector, m.industry, m.ftse_index,
           -- Reporting currency of everything out of annual_financials, which
           -- the archive's net-debt series and reported lines are both in. NOT
           -- the quote currency market_cap uses (see _size_context).
           m.financial_currency,
           t.market_cap, t.revenue, t.net_debt, t.ebitda,
           CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END as price_to_earnings,
           t.price_to_book, t.price_to_sales, t.roe, t.roic,
           t.gross_margin, t.operating_margin, t.net_income_margin,
           t.eps_cagr_10, t.eps_diluted, t.fcf_margin, t.net_income,
           -- Denominator for _eps_diluted_effective when eps_diluted is absent.
           COALESCE(t.shares_diluted, t.shares_basic, t.shares_outstanding) AS shares_for_eps,
           t.dividends_per_share, t.dividend_yield, t.period_end_price, t.fcf,
           t.gross_margin_median, t.operating_margin_median,
           t.net_margin_median, t.roe_median, t.roic_median,
           a.total_analysts, a.eps_growth_next_yr, a.eps_est_current_yr,
           s.momentum_score, s.risk_score, s.risk_model
    FROM company_metadata m
    LEFT JOIN ttm_financials t ON t.company_symbol = m.symbol
    LEFT JOIN (
        SELECT DISTINCT ON (symbol)
            symbol, total_analysts, eps_growth_next_yr, eps_est_current_yr
        FROM analyst_snapshots
        ORDER BY symbol, snapshot_date DESC
    ) a ON a.symbol = m.symbol
    LEFT JOIN screener_scores s ON s.symbol = m.symbol
    WHERE m.symbol = ANY(%s)
"""


def _ttm_ev_ebitda(r) -> Optional[float]:
    """Own trailing EV/EBITDA from ttm_financials, or None. Context for the
    forward multiple only — same sanity band as showcase_fwd so a degenerate
    stored EBITDA (the 40-50x artifacts the fair-value module trims) shows
    nothing rather than nonsense."""
    from showcase_fwd import _MIN_MULTIPLE, _MAX_MULTIPLE

    try:
        mkt = float(r.get("market_cap"))
        ebitda = float(r.get("ebitda"))
    except (TypeError, ValueError):
        return None
    if mkt <= 0 or ebitda <= 0:
        return None
    nd = r.get("net_debt")
    ev = mkt + (float(nd) if nd is not None else 0.0)
    if ev <= 0:
        return None
    m = ev / ebitda
    return round(m, 2) if _MIN_MULTIPLE <= m <= _MAX_MULTIPLE else None


def _reported_lines(entries: list[dict]) -> dict[int, list]:
    """The announcement's own quantified lines, per showcase entry.

    Straight passthrough of rns_announcements.earnings_quality — already
    extracted by the ranker for the earnings-quality gate, and until now shown
    nowhere. Each line carries the period, the item as printed, its value as
    printed and the prior-period comparator, which is what makes an H1'26 vs
    H1'25 read possible without any new extraction or LLM cost.

    Values stay VERBATIM strings, deliberately. They span money, percentages,
    per-share pence, ratios and prose ("down >90%", "net favourable $2.2bn"),
    and a parser over that would fail on a large minority — showing what the
    company printed is both cheaper and more honest. Any consumer that needs a
    number should use _parse_money and handle None.

    Safe to read live rather than snapshot onto high_impact_rns: rns._prune_old
    hard-deletes only Tier C rows and NULLs only `body`, so this column
    survives indefinitely on the Tier A/B rows the showcase is built from.
    """
    ids = [e["id"] for e in entries]
    rows = _q(
        """
        SELECT h.id AS showcase_id, r.earnings_quality
        FROM high_impact_rns h
        JOIN rns_announcements r ON r.id = h.rns_id
        WHERE h.id = ANY(%s) AND r.earnings_quality IS NOT NULL
        """,
        (ids,),
    )
    out: dict[int, list] = {}
    for r in rows:
        eq = r["earnings_quality"]
        if isinstance(eq, str):
            try:
                eq = json.loads(eq)
            except ValueError:
                continue
        if isinstance(eq, list) and eq:
            out[r["showcase_id"]] = eq
    return out


def _reported_net_debt(entries: list[dict]) -> dict[int, dict]:
    """The company's OWN net debt figure for each entry, as printed.

    Exists because _net_debt_series below is NOT the company's number and for
    a cash-rich filer is nowhere near it: updater.py computes net_debt as
    borrowings minus cash and never deducts short-term investments, which have
    no live source at all. ANTO.L's HY26 statement prints $3,966.1m at 30 June
    2026 against 31 Dec 2025's $2,749.5m, where our FY2025 row says $4,194.8m
    for that same date.

    Verbatim strings, and a separate query from _reported_lines because it is a
    different column with a different shape — one extra round trip on an
    admin-only page. Absent (rather than a partial dict) whenever the ranker
    found nothing or the row predates migration 033, so the UI shows our
    figure alone rather than an empty comparison.
    """
    ids = [e["id"] for e in entries]
    rows = _q(
        """
        SELECT h.id AS showcase_id, r.net_debt_reported
        FROM high_impact_rns h
        JOIN rns_announcements r ON r.id = h.rns_id
        WHERE h.id = ANY(%s) AND r.net_debt_reported IS NOT NULL
        """,
        (ids,),
    )
    out: dict[int, dict] = {}
    for r in rows:
        nd = r["net_debt_reported"]
        if isinstance(nd, str):
            try:
                nd = json.loads(nd)
            except ValueError:
                continue
        # {"found": false} is a real, stored answer — the ranker read the text
        # and it printed no net-debt figure — but there is nothing to render,
        # so it drops out here rather than reaching the payload.
        if isinstance(nd, dict) and nd.get("found") and nd.get("value"):
            out[r["showcase_id"]] = nd
    return out


def _net_debt_series(symbols: list[str], years: int = 5) -> dict[str, list]:
    """OUR net debt by fiscal year, oldest first, per symbol.

    NOT the company's reported figure, despite what this used to say — see
    _reported_net_debt above for that. updater.py:314 computes
    net_debt = st_debt + lt_debt - cash_and_equiv, which deducts cash but not
    short-term investments, and there is no live source for the latter at all
    (nothing writes annual_financials.st_investments). A cash-rich filer
    therefore reads far more levered here than in its own accounts: ANTO.L
    FY2025 is $4,194.8m / 0.80x against the $2,749.5m / 0.53x its own HY26
    statement prints for 31 December 2025. The shape of the series is sound;
    the level is not comparable with an announcement's own figure, and the UI
    labels it as ours for exactly that reason.

    From annual_financials, which carried net_debt on every one of the 19
    showcase symbols checked on 2026-08-14 — the one balance-sheet series with
    no coverage problem. Paired with the announcement's own lines it answers
    "is the growth funded by debt", which _annual_history already feeds the vet
    privately and the page never showed.

    In the REPORTING currency (financial_currency), like everything else out of
    annual_financials, and NOT comparable with market_cap. See _size_context
    for the same trap.
    """
    if not symbols:
        return {}
    rows = _q(
        """
        SELECT company_symbol, fiscal_year, period_end_date, net_debt, ebitda
        FROM (
            SELECT company_symbol, fiscal_year, period_end_date, net_debt, ebitda,
                   ROW_NUMBER() OVER (PARTITION BY company_symbol
                                      ORDER BY period_end_date DESC) AS rn
            FROM annual_financials
            WHERE company_symbol = ANY(%s)
        ) t
        WHERE rn <= %s
        ORDER BY company_symbol, period_end_date
        """,
        (symbols, years),
    )
    out: dict[str, list] = {}
    for r in rows:
        nd = r["net_debt"]
        eb = r["ebitda"]
        nd_f = float(nd) if nd is not None else None
        eb_f = float(eb) if eb is not None else None
        out.setdefault(r["company_symbol"], []).append({
            "fiscal_year": r["fiscal_year"],
            "net_debt": nd_f,
            # Leverage where it means anything: a negative or zero EBITDA makes
            # the ratio meaningless rather than large, so it stays None (the
            # same call rns_llm._build_messages makes for its own leverage line).
            "net_debt_to_ebitda": (
                round(nd_f / eb_f, 2)
                if nd_f is not None and eb_f is not None and eb_f > 0 else None
            ),
        })
    return out


def _sequential_summary(entries: list[dict], reported: dict[int, list]) -> dict[int, dict]:
    """The sequential comparison the vet rationale quotes, per showcase entry.

    Exists because the two revenue comparisons on the archive page read as a
    contradiction when only one of them is labelled. The reported-lines table
    shows the company's OWN comparator — ANTO's H1 2026 revenue of $4,479.0m
    against H1 2025's $3,799.4m, up 18% — while the vet rationale for the same
    row says it is "about 7% below H2 2025's $4,820.9m". Both are right: the
    second compares against the half that just finished, which nobody printed
    and which we derive as FY2025 total minus the prior-year H1. Neither
    number was wrong; the page just never said which was which.

    Reuses _sequential_base_from_earnings_quality, i.e. the SAME
    gates.compute_sequential_base arithmetic the vet was handed as a fact, so
    the page cannot drift from the prompt. `preceding_period` is added here
    (the compute function has no reason to care) purely so the UI does not
    have to know that the half before H1 is H2.

    Silent — absent from the map — on anything unestablishable, which is the
    majority: it needs a revenue line, no named one-off on it, a parseable
    value and prior, and an annual history to derive against.
    """
    out: dict[int, dict] = {}
    for e in entries:
        eq = reported.get(e["id"])
        if not eq:
            continue
        # One _annual_history query per entry with a usable revenue line.
        # Fine on the admin archive (detail=True never runs on the cached
        # public list); revisit if this ever moves onto a hot path.
        base = _sequential_base_from_earnings_quality(
            {"symbol": e["symbol"], "earnings_quality": eq}
        )
        if not base:
            continue
        out[e["id"]] = {
            "period": base["period"],
            "preceding_period": "H2" if base["period"] == "H1" else "H1",
            "metric": base["metric"],
            "current_value": base["current_value"],
            "preceding_value": base["preceding_value"],
            "delta_pct": base["delta_pct"],
            "basis": base["basis"],
            "prior_year_value": base["prior_year_value"],
        }
    return out


def _enrich(entries: list[dict], detail: bool = False) -> list[dict]:
    """Turn raw high_impact_rns rows into full showcase rows: watchlist parity +
    MQVR scores + days/%-since-news + follow-up tally + the story block.

    `detail=True` adds the announcement's own reported lines and the net-debt
    series. Off by default because it costs two extra queries per call and only
    the admin archive renders them — the public list is the hot, cached path.
    """
    if not entries:
        return []
    from main import (
        _watchlist_rows, _scrub_screener_metrics, _attach_pegy,
        _quality_score, _value_score,
    )

    symbols = list({e["symbol"] for e in entries})
    watchlist = {r["symbol"]: r for r in _watchlist_rows(symbols)}

    mrows = _q(_MQVR_SQL, (symbols,))
    _scrub_screener_metrics(mrows)
    _attach_pegy(mrows)
    mqvr = {
        r["symbol"]: {
            "momentum_score": r.get("momentum_score"),
            "quality_score": _quality_score(r),
            "value_score": _value_score(r),
            "ttm_ev_ebitda": _ttm_ev_ebitda(r),
            "financial_currency": r.get("financial_currency"),
        }
        for r in mrows
    }

    reported = _reported_lines(entries) if detail else {}
    debt = _net_debt_series(symbols) if detail else {}
    reported_debt = _reported_net_debt(entries) if detail else {}
    sequential = _sequential_summary(entries, reported) if detail else {}

    ids = [e["id"] for e in entries]
    furows = _q(
        "SELECT showcase_id, headline, url, published_at, sentiment, llm_score, "
        "       tier, category "
        "FROM high_impact_rns_followups WHERE showcase_id = ANY(%s) "
        "ORDER BY published_at DESC",
        (ids,),
    )
    fu_map: dict[int, list] = {}
    for f in furows:
        fu_map.setdefault(f["showcase_id"], []).append(f)

    # Prior news: tier A/B history for these symbols, filtered per-entry below to
    # published_at < the story's own date. One batched query for all symbols
    # (retained indefinitely now that _prune_old spares A/B rows) rather than
    # N+1 per entry.
    prows = _q(
        "SELECT symbol, published_at, headline, url, category, tier, "
        "       llm_sentiment, llm_thesis, keyword_hits "
        "FROM rns_announcements WHERE symbol = ANY(%s) AND tier IN ('A', 'B') "
        "ORDER BY published_at DESC",
        (symbols,),
    )
    prior_by_symbol: dict[str, list] = {}
    for p in prows:
        prior_by_symbol.setdefault(p["symbol"], []).append(p)

    now = datetime.now(timezone.utc)
    out = []
    for e in entries:
        base = dict(watchlist.get(e["symbol"]) or {
            "symbol": e["symbol"], "name": e.get("company_name"),
        })
        m = mqvr.get(e["symbol"], {})
        fus = fu_map.get(e["id"], [])
        priors = [
            p for p in prior_by_symbol.get(e["symbol"], [])
            if p["published_at"] < e["published_at"]
        ][:10]

        # % since news: story-date close (snapshotted at flag time) vs latest price.
        baseline = float(e["story_close"]) if e.get("story_close") is not None \
            else _story_close(e["symbol"], e["published_at"])
        cur = base.get("current_price")
        pct = None
        if baseline and cur is not None and baseline > 0:
            pct = round((cur / baseline - 1) * 100, 2)

        # The same split /gates shows, because the single "% since news" figure
        # hid which half of it was ever available:
        #   gap_pct  — pre-news close -> the first open you could deal at. The
        #              move the market made while nobody could trade it.
        #   pct_since_entry_open — that open -> now. The part a reader could
        #              actually have captured.
        # They compound back to pct_since_news, so nothing is lost by splitting.
        # Neither can be snapshotted at flag time: for a 07:00 story the entry
        # open is hours away, so both are looked up fresh.
        entry_open = _entry_open(e["symbol"], e["published_at"])
        gap_pct = None
        if baseline and entry_open and baseline > 0:
            gap_pct = round((entry_open / baseline - 1) * 100, 2)
        pct_entry_open = None
        if entry_open and cur is not None and entry_open > 0:
            pct_entry_open = round((cur / entry_open - 1) * 100, 2)

        out.append({
            **base,
            "showcase_id": e["id"],
            "momentum_score": m.get("momentum_score"),
            "quality_score": m.get("quality_score"),
            "value_score": m.get("value_score"),
            # Inclusive calendar-day count: publication day is day 1, so an RNS
            # published yesterday reads as "2 days" (its second day) today,
            # rather than counting whole 24h periods elapsed.
            "days_since_news": (now.date() - e["published_at"].date()).days + 1,
            "pct_since_news": pct,
            "story_close": baseline,
            "gap_pct": gap_pct,
            "pct_since_entry_open": pct_entry_open,
            "entry_open": entry_open,
            "spark_since": _spark_since_count(e["symbol"], e["published_at"]),
            # Forward multiple (extraction-only LLM + Python arithmetic; see
            # showcase_fwd.py). fwd_multiple is NULL when nothing usable was
            # stated — the UI shows a dash, never a guess.
            "fwd_multiple": float(e["fwd_multiple"]) if e.get("fwd_multiple") is not None else None,
            "fwd_metric": e.get("fwd_metric"),
            "fwd_basis": e.get("fwd_basis"),
            "fwd_is_bound": e.get("fwd_is_bound"),
            "fwd_period": e.get("fwd_period"),
            "fwd_quote": e.get("fwd_quote"),
            # Trailing comparison, only where it's like-for-like: a forward
            # EV/EBITDA exists and the TTM one is computable. Never a fallback
            # for a blank column — it contextualises the re-rating.
            "ttm_ev_ebitda": (
                m.get("ttm_ev_ebitda")
                if e.get("fwd_multiple") is not None and e.get("fwd_metric") == "ebitda"
                else None
            ),
            # Admin archive only (detail=True). Both are in the REPORTING
            # currency, which is why financial_currency travels with them —
            # CTEC reports USD and CGEO GEL, and rendering either behind a £
            # would be the same mislabel _size_context exists to prevent.
            "reported_lines": reported.get(e["id"]) or None,
            "net_debt_series": debt.get(e["symbol"]) or None,
            # The company's own net-debt figure, which our series above is not.
            "reported_net_debt": reported_debt.get(e["id"]) or None,
            # The comparator the vet rationale uses, so the page can say which
            # of the two revenue reads is which. See _sequential_summary.
            "sequential_base": sequential.get(e["id"]) or None,
            "financial_currency": m.get("financial_currency") if detail else None,
            "followup_pos": sum(1 for f in fus if f["sentiment"] == "positive"),
            "followup_neg": sum(1 for f in fus if f["sentiment"] == "negative"),
            "followup_neutral": sum(1 for f in fus if f["sentiment"] == "neutral"),
            "followups": [
                {
                    "headline": f["headline"],
                    "url": f["url"],
                    "published_at": f["published_at"],
                    "sentiment": f["sentiment"],
                    "llm_score": f["llm_score"],
                    "tier": f["tier"],
                    "category": f["category"],
                }
                for f in fus
            ],
            # Prior news: A/B announcements for this issuer before the story date.
            # Empty for most entries today (history only started accumulating
            # once _prune_old stopped deleting A/B rows) and fills in over time.
            "prior_pos": sum(1 for p in priors if _sentiment(p) == "positive"),
            "prior_neg": sum(1 for p in priors if _sentiment(p) == "negative"),
            "prior_neutral": sum(1 for p in priors if _sentiment(p) == "neutral"),
            "prior_news": [
                {
                    "headline": p["headline"],
                    "url": p["url"],
                    "published_at": p["published_at"],
                    "category": p["category"],
                    "sentiment": _sentiment(p),
                }
                for p in priors
            ],
            "story": {
                "id": e["id"],
                "rns_id": e["rns_id"],
                "headline": e["headline"],
                "url": e["url"],
                "published_at": e["published_at"],
                "category": e["category"],
                "tier": e["tier"],
                "llm_score": e["llm_score"],
                "llm_confidence": e["llm_confidence"],
                "llm_thesis": e["llm_thesis"],
                "llm_risks": e["llm_risks"],
                "summary": e["summary"],
                "status": e["status"],
                "vet_verdict": e["vet_verdict"],
                "vet_confidence": e["vet_confidence"],
                "vet_rationale": e["vet_rationale"],
                # The score that actually put this story on the page (migration
                # 029). NULL on every row flagged before 2026-08-03 — the UI
                # must render that as "—", never as a zero.
                "vet_score": e.get("vet_score"),
                "flagged_at": e["flagged_at"],
                "decided_at": e["decided_at"],
            },
        })
    return out


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.get("")
def list_showcase(response: Response):
    """Public — the approved showcase, newest story first."""
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=60"
    entries = _q(
        "SELECT * FROM high_impact_rns WHERE status = 'approved' "
        # Display floor only — the rows stay in the table (see the constant).
        "AND (published_at AT TIME ZONE 'Europe/London')::date >= %s::date "
        "ORDER BY published_at DESC",
        (SHOWCASE_MIN_STORY_DATE,),
    )
    return _enrich(entries)


@router.get("/pending", dependencies=[Depends(require_admin_token)])
def list_pending():
    """Admin — candidates awaiting approval, newest flag first."""
    entries = _q(
        "SELECT * FROM high_impact_rns WHERE status = 'pending' ORDER BY flagged_at DESC"
    )
    return _enrich(entries)


@router.get("/shadow", dependencies=[Depends(require_admin_token)])
def list_shadow():
    """Admin — rows the vet scored but withheld (vet_score < HIGH_IMPACT_MIN_VET_SCORE).

    Admin-only on purpose. These are the vet's own rejections, so putting them on
    the public page would undo the thing the vet exists to do; the point here is
    that its decisions are otherwise invisible — a shadow row appears in no UI at
    all, only in the cron log. Ordered by vet_score DESC so the near-misses (the
    band that actually decides whether 75 is the right floor) sort to the top.

    A NULL vet_score means the vet call FAILED, not that the story scored zero
    (see flag_high_impact_candidates). Those sort last and the UI labels them
    separately — do not present them as low-conviction.
    """
    entries = _q(
        "SELECT * FROM high_impact_rns WHERE status = 'shadow' "
        # Same display floor as the public list — these rows are interleaved
        # into the same table, so a cutoff that applied to only one of the two
        # would leave withheld stories sitting above published ones that the
        # page no longer shows.
        "AND (published_at AT TIME ZONE 'Europe/London')::date >= %s::date "
        "ORDER BY vet_score DESC NULLS LAST, flagged_at DESC",
        (SHOWCASE_MIN_STORY_DATE,),
    )
    # detail=True: the archive is where the withheld rows are read closely, so
    # it gets the announcement's own reported lines and the net-debt series.
    # Admin-only and uncached, so the two extra queries cost the public page
    # nothing.
    return _enrich(entries, detail=True)


class StatusBody(BaseModel):
    status: str


@router.post("/{entry_id}/status", dependencies=[Depends(require_admin_token)])
def set_status(entry_id: int, body: StatusBody):
    """Admin — approve / reject / archive a showcase entry."""
    new = (body.status or "").lower().strip()
    if new not in ("approved", "rejected", "archived"):
        raise HTTPException(422, "status must be one of approved|rejected|archived")
    rows = _q(
        "UPDATE high_impact_rns SET status = %s, decided_at = NOW() "
        "WHERE id = %s RETURNING id",
        (new, entry_id),
    )
    if not rows:
        raise HTTPException(404, "showcase entry not found")
    return {"id": entry_id, "status": new}


@router.post("/flag", dependencies=[Depends(require_admin_token)])
def flag_now(hours: int = 48):
    """Admin — manually run the auto-flag pass (dev/testing convenience)."""
    return flag_high_impact_candidates(hours=hours)


@router.post("/extract-fwd", dependencies=[Depends(require_admin_token)])
def extract_fwd(entry_id: Optional[int] = None, force: bool = False):
    """Admin — (re)run the forward-multiple extraction for showcase entries.

    Backfill for rows flagged before the feature existed, and a redo hook after
    prompt/gate changes. Targets one entry (`entry_id`) or every non-rejected
    entry; without `force`, rows that already have a fwd_processed_at stamp are
    left alone. Announcement text comes from the snapshotted Investegate URL,
    which outlives the rns_announcements prune."""
    from showcase_fwd import extract_fwd_fields

    entries = _q(
        """
        SELECT h.id, h.symbol, h.company_name, h.headline, h.url, h.summary,
               h.fwd_processed_at,
               m.sector, m.industry, t.market_cap, t.net_debt
        FROM high_impact_rns h
        LEFT JOIN company_metadata m ON m.symbol = h.symbol
        LEFT JOIN LATERAL (
            SELECT market_cap, net_debt FROM ttm_financials
            WHERE company_symbol = h.symbol
            ORDER BY period_end_date DESC NULLS LAST LIMIT 1
        ) t ON TRUE
        WHERE h.status <> 'rejected'
          AND (%s::bigint IS NULL OR h.id = %s)
        ORDER BY h.published_at DESC
        """,
        (entry_id, entry_id),
    )

    results = []
    for e in entries:
        if e["fwd_processed_at"] is not None and not force:
            results.append({"id": e["id"], "symbol": e["symbol"], "skipped": "already processed"})
            continue
        fwd = extract_fwd_fields(e)
        _exec(
            """
            UPDATE high_impact_rns SET
                fwd_metric = %s, fwd_value = %s, fwd_currency = %s,
                fwd_period = %s, fwd_basis = %s, fwd_is_bound = %s,
                fwd_quote = %s, fwd_ev = %s, fwd_multiple = %s,
                fwd_model = %s, fwd_processed_at = %s
            WHERE id = %s
            """,
            (
                fwd["fwd_metric"], fwd["fwd_value"], fwd["fwd_currency"],
                fwd["fwd_period"], fwd["fwd_basis"], fwd["fwd_is_bound"],
                fwd["fwd_quote"], fwd["fwd_ev"], fwd["fwd_multiple"],
                fwd["fwd_model"], fwd["fwd_processed_at"], e["id"],
            ),
        )
        results.append({
            "id": e["id"], "symbol": e["symbol"],
            "fwd_multiple": fwd["fwd_multiple"], "fwd_metric": fwd["fwd_metric"],
            "fwd_basis": fwd["fwd_basis"], "fwd_currency": fwd["fwd_currency"],
            "fwd_quote": (fwd["fwd_quote"] or "")[:160] or None,
        })
    return {"processed": len(results), "results": results}
