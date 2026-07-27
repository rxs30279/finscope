"""Story of the week — the RNS proof block on the marketing landing page.

Picks one real announcement from the trailing week that the LLM ranker scored
before the 08:00 open, together with the price reaction it called, and snapshots
it into `landing_story` (migration 023). The landing page reads the newest row.

Why weekly rather than daily: the point of the block is the *outcome*, and this
morning's 07:00 announcement has no price reaction yet. A week-old story always
has settled prices. Why not a fixed weekday: measured over all 268 scored morning
announcements (29 Jun - 27 Jul 2026), Mon/Fri are genuinely thin (6.8 / 7.8
scored per session vs ~18 midweek) but Wed-vs-Thu is noise at 4 sessions each —
so the pick ranges over the whole week instead of pinning a day.

PRICE CONVENTION (load-bearing): RNS drops ~07:00, before the 08:00 LSE open, so
the news is priced into THAT day's session. The gap is previous close ->
announcement-day open. Do NOT reuse showcase._next_open() here: it deliberately
takes the day AFTER the story, and that off-by-one flattened the entire signal in
the score-performance work (backend/analysis/rns_score_perf.py has the right
convention). Prices are pence throughout, matching price_history.

The pick is a curated best case by construction — we take the biggest move that
agreed with the score's direction. Page copy must therefore describe what the
score *flagged*, never imply a realised return.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Response

import psycopg2.extras

from db import connection, query
from showcase import HIGH_IMPACT_MIN_MARKET_CAP, _sentiment

router = APIRouter(prefix="/api/landing", tags=["landing"])

# ── Tunables ──────────────────────────────────────────────────────────────────
# 76+ is the band the digest analysis found meaningful (~3.4x big-move lift) and
# the one rns_score_perf splits on.
LANDING_MIN_LLM_SCORE = 76
LANDING_WINDOW_DAYS = 7
# "Scored before the open" has to be literally true, so only announcements that
# published ahead of the 08:00 London open qualify.
LANDING_MAX_PUBLISH_TIME = "08:00"
# A limp week is better skipped than shown: the block only earns its space if the
# move is big enough to read as a move.
LANDING_MIN_GAP_PCT = 3.0
# Announcement-day traded value floor, in POUNDS (see _qualifies).
LANDING_MIN_TURNOVER = 250_000
# Sessions either side of the announcement day in the snapshotted candle window.
LANDING_OHLC_PAD = 3
# Funnel: the "scored 80 or above" tier, and how many wire lines to snapshot for
# the scrolling ticker (the page loops them, so it needs far fewer than a full
# morning's ~120).
LANDING_WIRE_TOP_SCORE = 80
LANDING_WIRE_SAMPLE = 24
# M&A is excluded on purpose. A recommended bid gapping a stock 40% is not
# evidence the ranker read anything well — everyone already knows a bid pops a
# stock — and because a bid outguns every organic move, leaving them in would
# have this block showing takeovers most weeks instead of the trading-statement
# calls it exists to demonstrate. Category names come from rns.py's classifier.
LANDING_EXCLUDED_CATEGORIES = frozenset({
    "acquisition", "firm_offer", "possible_offer", "recommended_offer", "ma_update",
})


# ── Selection ─────────────────────────────────────────────────────────────────
#
# The SQL applies only the cheap, indexed eligibility filters (score, tier,
# window, published-before-the-open) and computes the numbers. The judgement
# floors — size, liquidity, gap magnitude, direction agreement — are applied in
# _qualifies() below, where they sit together and are unit-testable without a
# database. The candidate set here is a week of tier A/B 76+ rows, so filtering
# a handful of extra rows in Python costs nothing.
_CANDIDATE_SQL = """
    SELECT r.id, r.symbol, r.company_name, r.headline, r.url, r.published_at,
           r.category, r.keyword_hits, r.llm_score, r.llm_thesis, r.llm_sentiment,
           m.sector, m.ftse_index,
           t.market_cap,
           ev.date   AS event_date,
           ev.open   AS event_open,
           ev.close  AS event_close,
           ev.volume AS event_volume,
           pre.close AS prev_close,
           (ev.open / pre.close - 1) * 100 AS gap_pct
    FROM rns_announcements r
    JOIN ttm_financials t ON t.company_symbol = r.symbol
    LEFT JOIN company_metadata m ON m.symbol = r.symbol
    -- The announcement-day bar. ">= the announcement date, earliest" rather than
    -- "= the announcement date" so a rare weekend/holiday RNS resolves to the
    -- next session it could actually trade in; for a normal weekday morning
    -- announcement the two are the same bar.
    JOIN LATERAL (
        SELECT p.date, p.open, p.close, p.volume
        FROM price_history p
        WHERE p.symbol = r.symbol
          AND p.date >= (r.published_at AT TIME ZONE 'Europe/London')::date
          AND p.open IS NOT NULL
        ORDER BY p.date ASC
        LIMIT 1
    ) ev ON TRUE
    -- The close the market last saw before the news — the gap baseline.
    JOIN LATERAL (
        SELECT p.close
        FROM price_history p
        WHERE p.symbol = r.symbol
          AND p.date < ev.date
          AND p.close IS NOT NULL
        ORDER BY p.date DESC
        LIMIT 1
    ) pre ON TRUE
    WHERE r.symbol IS NOT NULL
      AND r.llm_processed_at IS NOT NULL
      AND r.llm_score >= %s
      AND r.tier IN ('A', 'B')
      AND r.published_at >= NOW() - (%s || ' days')::interval
      AND (r.published_at AT TIME ZONE 'Europe/London')::time < %s::time
      AND pre.close > 0
      -- Never headline the same story twice.
      AND NOT EXISTS (SELECT 1 FROM landing_story ls WHERE ls.rns_id = r.id)
    ORDER BY ABS(ev.open / pre.close - 1) DESC, r.llm_score DESC
"""


def _ohlc_window(symbol: str, event_date, pad: int = LANDING_OHLC_PAD) -> tuple[list, int]:
    """The +/-`pad` sessions around the announcement day, oldest first, as
    [label, open, high, low, close] rows plus the index of the event bar.

    Labels are day-of-month, which is all the axis needs at this width."""
    before = query(
        """
        SELECT date, open, high, low, close FROM price_history
        WHERE symbol = %s AND date <= %s AND open IS NOT NULL
        ORDER BY date DESC LIMIT %s
        """,
        (symbol, event_date, pad + 1),
    )
    after = query(
        """
        SELECT date, open, high, low, close FROM price_history
        WHERE symbol = %s AND date > %s AND open IS NOT NULL
        ORDER BY date ASC LIMIT %s
        """,
        (symbol, event_date, pad),
    )
    bars = list(reversed(before)) + after
    event_idx = max(len(before) - 1, 0)
    ohlc = [
        [
            b["date"].strftime("%d"),
            float(b["open"]),
            float(b["high"]) if b["high"] is not None else float(b["open"]),
            float(b["low"]) if b["low"] is not None else float(b["open"]),
            float(b["close"]) if b["close"] is not None else float(b["open"]),
        ]
        for b in bars
    ]
    return ohlc, event_idx


def _wire_stats(published_at) -> dict:
    """The funnel for the morning this story landed in, plus a slice of the wire.

    This is the sequence the landing block opens with: everything that hit the
    wire before the open, how much survived the rules filter (tier A/B), and how
    little the ranker scored 80+. Real 22 Jul 2026: 122 -> 31 -> 4.

    The sample is deliberately UNFILTERED and in publish order — the routine
    "Transaction in Own Shares" / "Holding(s) in Company" noise is exactly the
    point, so filtering it out would undercut the funnel that follows.
    """
    counts = query(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE tier IN ('A', 'B')) AS survived,
               COUNT(*) FILTER (WHERE llm_score >= %s)    AS top
        FROM rns_announcements
        WHERE (published_at AT TIME ZONE 'Europe/London')::date
                  = (%s AT TIME ZONE 'Europe/London')::date
          AND (published_at AT TIME ZONE 'Europe/London')::time < %s::time
        """,
        (LANDING_WIRE_TOP_SCORE, published_at, LANDING_MAX_PUBLISH_TIME),
    )
    sample = query(
        """
        SELECT to_char(published_at AT TIME ZONE 'Europe/London', 'HH24:MI') AS t,
               ticker, headline
        FROM rns_announcements
        WHERE (published_at AT TIME ZONE 'Europe/London')::date
                  = (%s AT TIME ZONE 'Europe/London')::date
          AND (published_at AT TIME ZONE 'Europe/London')::time < %s::time
        ORDER BY published_at ASC, id ASC
        LIMIT %s
        """,
        (published_at, LANDING_MAX_PUBLISH_TIME, LANDING_WIRE_SAMPLE),
    )
    c = counts[0] if counts else {}
    return {
        "total": int(c.get("total") or 0),
        "survived": int(c.get("survived") or 0),
        "top": int(c.get("top") or 0),
        "sample": [[s["t"], s["ticker"] or "", s["headline"]] for s in sample],
    }


def _agrees(direction: str, gap_pct: float) -> bool:
    """Did the price move the way the score said it would?"""
    if direction == "positive":
        return gap_pct > 0
    if direction == "negative":
        return gap_pct < 0
    return False  # neutral calls have no direction to be right about


def _turnover(row) -> Optional[float]:
    """Announcement-day traded value in POUNDS (price_history is pence)."""
    vol, close = row.get("event_volume"), row.get("event_close")
    if vol is None or close is None:
        return None
    return float(vol) * float(close) / 100.0


def _qualifies(row, gap_pct: float, direction: str) -> bool:
    """The judgement floors, all in one place.

    Size and liquidity keep the block on names where the move means something —
    Mulberry scored 85 on 22 Jul 2026 and "moved" 2.2% on 13,769 shares, which is
    one trade, not the market repricing anything. Direction agreement is what
    makes the block a claim about the score rather than a coincidence.
    """
    if row.get("category") in LANDING_EXCLUDED_CATEGORIES:
        return False
    cap = row.get("market_cap")
    if cap is None or float(cap) < HIGH_IMPACT_MIN_MARKET_CAP:
        return False
    turnover = _turnover(row)
    if turnover is None or turnover < LANDING_MIN_TURNOVER:
        return False
    if abs(gap_pct) < LANDING_MIN_GAP_PCT:
        return False
    return _agrees(direction, gap_pct)


def select_candidate() -> Optional[dict]:
    """Best qualifying story from the trailing week, or None for a thin week.

    Ranked by |gap| (the SQL already orders that way, biggest first, tie-broken
    on llm_score), so the first row that clears _qualifies() is the pick.
    """
    cands = query(
        _CANDIDATE_SQL,
        (
            LANDING_MIN_LLM_SCORE,
            LANDING_WINDOW_DAYS,
            LANDING_MAX_PUBLISH_TIME,
        ),
    )
    for c in cands:
        gap = float(c["gap_pct"])
        direction = _sentiment(c)
        if not _qualifies(c, gap, direction):
            continue
        c["direction"] = direction
        c["gap_pct"] = round(gap, 2)
        return c
    return None


def pick_story() -> dict:
    """Pick this week's story and snapshot it. Returns a counts dict for the
    cron log.

    A thin week is a no-op, NOT a blank page: the previous row stays in place
    and the caller records status='skipped'.
    """
    cand = select_candidate()
    if cand is None:
        return {"status": "skipped", "reason": "no qualifying story in the trailing week"}

    ohlc, event_idx = _ohlc_window(cand["symbol"], cand["event_date"])
    wire = _wire_stats(cand["published_at"])

    with connection() as conn:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO landing_story
                (rns_id, symbol, company_name, headline, url, published_at,
                 llm_score, llm_sentiment, llm_thesis, sector, ftse_index,
                 prev_close, event_open, event_close, gap_pct, ohlc, event_idx,
                 wire_total, wire_survived, wire_top, wire_sample)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s)
            ON CONFLICT (rns_id) DO NOTHING
            """,
            (
                cand["id"], cand["symbol"], cand["company_name"], cand["headline"],
                cand["url"], cand["published_at"], cand["llm_score"],
                cand["direction"], cand["llm_thesis"], cand["sector"],
                cand["ftse_index"], cand["prev_close"], cand["event_open"],
                cand["event_close"], cand["gap_pct"],
                psycopg2.extras.Json(ohlc), event_idx,
                wire["total"], wire["survived"], wire["top"],
                psycopg2.extras.Json(wire["sample"]),
            ),
        )
        written = cur.rowcount

    return {
        "status": "ok" if written else "skipped",
        "symbol": cand["symbol"],
        "rns_id": cand["id"],
        "llm_score": cand["llm_score"],
        "direction": cand["direction"],
        "gap_pct": cand["gap_pct"],
        "bars": len(ohlc),
        "wire": f"{wire['total']} -> {wire['survived']} -> {wire['top']}",
    }


def record_run(status: str, detail: dict) -> None:
    """Stamp pipeline_runs so healthcheck.py can tell the weekly job ran
    (migration 008 convention, same shape as shorts.record_run)."""
    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
            VALUES ('landing_story', NOW(), %s, %s)
            ON CONFLICT (pipeline) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                status      = EXCLUDED.status,
                detail      = EXCLUDED.detail
            """,
            (status, psycopg2.extras.Json(detail)),
        )
        conn.commit()


# ── API ───────────────────────────────────────────────────────────────────────
def current_story() -> Optional[dict]:
    """The newest snapshotted story, JSON-ready, or None if none has been picked."""
    rows = query("SELECT * FROM landing_story ORDER BY picked_at DESC LIMIT 1")
    if not rows:
        return None
    r = rows[0]

    def _f(v):
        return float(v) if v is not None else None

    return {
        "symbol": r["symbol"],
        "company_name": r["company_name"],
        "headline": r["headline"],
        "url": r["url"],
        "published_at": r["published_at"],
        "llm_score": r["llm_score"],
        "sentiment": r["llm_sentiment"],
        "thesis": r["llm_thesis"],
        "sector": r["sector"],
        "ftse_index": r["ftse_index"],
        "prev_close": _f(r["prev_close"]),
        "event_open": _f(r["event_open"]),
        "event_close": _f(r["event_close"]),
        "gap_pct": _f(r["gap_pct"]),
        "ohlc": r["ohlc"],
        "event_idx": r["event_idx"],
        # Null for rows snapshotted before the funnel existed — the page drops
        # the opening scenes and goes straight to the card when it's missing.
        "wire": {
            "total": r["wire_total"],
            "survived": r["wire_survived"],
            "top": r["wire_top"],
            "sample": r["wire_sample"] or [],
        } if r["wire_total"] else None,
        "picked_at": r["picked_at"],
    }


@router.get("/story")
def get_landing_story(response: Response):
    """Public — the current story of the week, or null before the first pick.

    Cached hard: the row only changes once a week, so a stale-while-revalidate
    day is free, and the landing page is the most-hit route on the site.
    """
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
    return current_story()
