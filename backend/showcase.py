"""High Impact RNS — curated showcase of high-impact, positive RNS stories.

Pipeline (all driven from run_rns.py after the LLM ranking stage):
  1. flag_high_impact_candidates() — rules pick candidates (high llm_score,
     positive sentiment, performance-report category, market-cap floor), an
     advisory LLM vet flags market-punished positives, and each lands as
     status='pending' for a human to approve.
  2. record_followups() — copies subsequent tier A/B announcements for each
     tracked company into high_impact_rns_followups, so bad news that surfaces
     AFTER selection (Luceco-style CEO exit) is captured before the source prunes.
  3. expire_tracked_entries() — auto-archives approved entries 31 days after the
     story date (admin Extend pushes that out).

Endpoints serve the approved (public) and pending (admin) lists enriched with the
same per-stock metrics as the watchlist plus MQVR scores, days-since / %-since the
story, and the follow-up tally. Story data is snapshotted at flag time because
rns_announcements is pruned after 14 days (run_rns.py) while monitoring runs ~30d.

Main-module helpers (_watchlist_rows, the score functions) are imported lazily
inside functions to avoid a circular import at load time — main.py registers this
router before those helpers are defined.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from admin_auth import require_admin_token

router = APIRouter(prefix="/api/showcase", tags=["showcase"])

# ── Tunables ──────────────────────────────────────────────────────────────────
# The auto-flag is deliberately strict: this is a small, curated showcase, so a
# missed candidate is cheap (nothing appears) while a weak one wastes a review.
HIGH_IMPACT_MIN_LLM_SCORE = 75
HIGH_IMPACT_CATEGORIES = ("trading_update", "final_results", "interim_results", "quarterly")
HIGH_IMPACT_MIN_MARKET_CAP = 50_000_000  # £50m — keep to genuinely tradeable names
HIGH_IMPACT_DEDUPE_DAYS = 30             # don't re-flag the same symbol within a month
TRACK_DAYS = 31                          # monitoring window from the story date
EXTEND_DAYS = 30                         # admin Extend button adds this per click


# ── Sentiment (server-side port of RnsTab.js getSentiment) ────────────────────
_NEG_CATS = {"profit_warning", "going_concern", "liquidation", "delisting", "suspension"}
_POS_CATS = {"firm_offer", "recommended_offer", "drug_approval", "contract_win"}
_LLM_POS = ["positive", "upside", "beat", "above expectations", "outperform",
            "upgrade", "bullish", "boost", "opportunity"]
_LLM_NEG = ["negative", "pressure", "miss", "below expectations", "concern",
            "decline", "downgrade", "disappoint", "warning", "bearish", "weak"]


def _sentiment(row) -> str:
    """Classify an announcement as 'positive' | 'negative' | 'neutral'.

    Mirrors the frontend getSentiment so the flag rule and the follow-up tally
    agree with what the RNS page shows: category override first, then a scan of
    the LLM thesis, then the pos:/neg: keyword_hits counts as a last resort.
    """
    cat = row.get("category")
    if cat in _NEG_CATS:
        return "negative"
    if cat in _POS_CATS:
        return "positive"

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


def _story_close(symbol: str, published_at) -> Optional[float]:
    """Close (pence) on or before the story date — the baseline for % since news."""
    rows = _q(
        """
        SELECT close FROM price_history
        WHERE symbol = %s AND date <= %s::date
        ORDER BY date DESC LIMIT 1
        """,
        (symbol, published_at),
    )
    return float(rows[0]["close"]) if rows and rows[0]["close"] is not None else None


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
def _vet_messages(cand: dict) -> list[dict]:
    system = (
        "You are a sceptical UK equity analyst vetting positive-looking RNS "
        "announcements for a 1-3 month long showcase of good investment cases. "
        "Your job is to catch positive-FRAMED stories the market may still punish "
        "— e.g. a secondary/overseas listing that fragments liquidity, guidance "
        "quietly cut inside an upbeat results headline, heavy equity dilution, or "
        "profit flattered by one-off/non-cash gains. Judge whether this is a "
        "genuinely positive near-term investment case. Return STRICT JSON only."
    )
    user = f"""Announcement
  Company:    {cand.get('company_name') or '?'} ({cand.get('symbol') or '?'})
  Sector:     {cand.get('sector') or '?'}
  Category:   {cand.get('category') or '?'}
  Headline:   {cand.get('headline')}
  AI thesis:  {cand.get('llm_thesis') or '(none)'}
  AI risks:   {cand.get('llm_risks') or '(none)'}

Investegate AI summary
{cand.get('summary') or '(not available)'}

Return a JSON object with exactly these fields:
  verdict     one of: "include" (clean positive case), "caution" (positive but
              with a real catch to check), "exclude" (likely to disappoint)
  confidence  one of: "high", "medium", "low"
  rationale   one or two sentences naming the specific catch, or why it's clean

Return JSON only — no preamble, no code fence."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _vet_candidate(cand: dict) -> dict:
    """Run the advisory vet. Raises on API/parse failure — the caller treats that
    as non-fatal and stores a NULL verdict."""
    from rns_llm import _get_client, _DEEPSEEK_MODEL

    client = _get_client()
    resp = client.chat.completions.create(
        model=_DEEPSEEK_MODEL,
        messages=_vet_messages(cand),
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=300,
    )
    result = json.loads(resp.choices[0].message.content)
    verdict = (result.get("verdict") or "").lower().strip()
    if verdict not in ("include", "caution", "exclude"):
        verdict = None
    return {
        "verdict": verdict,
        "confidence": (result.get("confidence") or "").lower().strip()[:10] or None,
        "rationale": (result.get("rationale") or "").strip()[:500] or None,
        "model": _DEEPSEEK_MODEL,
    }


# ── Auto-flag ─────────────────────────────────────────────────────────────────
def flag_high_impact_candidates(hours: int = 48) -> dict:
    """Flag rules-passing candidates from the last `hours` as pending showcase
    entries. Advisory-vets each and snapshots the story. Idempotent via the
    rns_id unique constraint. Returns a counts dict for cron logs."""
    cands = _q(
        """
        SELECT r.id, r.symbol, r.company_name, r.headline, r.url, r.published_at,
               r.tier, r.category, r.score, r.keyword_hits, r.summary,
               r.llm_score, r.llm_confidence, r.llm_thesis, r.llm_risks, r.llm_action,
               m.sector, m.industry, m.country, m.ftse_index, t.market_cap
        FROM rns_announcements r
        JOIN ttm_financials t ON t.company_symbol = r.symbol
        LEFT JOIN company_metadata m ON m.symbol = r.symbol
        WHERE r.symbol IS NOT NULL
          AND r.llm_processed_at IS NOT NULL
          AND r.llm_score >= %s
          AND r.llm_action IN ('watch', 'research')
          AND r.tier IN ('A', 'B')
          AND r.category = ANY(%s)
          AND r.published_at >= NOW() - (%s || ' hours')::interval
          AND t.market_cap >= %s
          AND NOT EXISTS (
              SELECT 1 FROM high_impact_rns h
              WHERE h.symbol = r.symbol
                AND h.flagged_at >= NOW() - (%s || ' days')::interval
          )
        ORDER BY r.llm_score DESC
        """,
        (
            HIGH_IMPACT_MIN_LLM_SCORE,
            list(HIGH_IMPACT_CATEGORIES),
            hours,
            HIGH_IMPACT_MIN_MARKET_CAP,
            HIGH_IMPACT_DEDUPE_DAYS,
        ),
    )

    flagged = 0
    skipped_sentiment = 0
    vetted = 0
    for c in cands:
        if _sentiment(c) != "positive":
            skipped_sentiment += 1
            continue

        story_close = _story_close(c["symbol"], c["published_at"])
        try:
            vet = _vet_candidate(c)
            vetted += 1
        except Exception as e:
            print(f"[showcase] vet failed for {c['symbol']} (non-fatal) — {e}")
            vet = None

        track_until = c["published_at"] + timedelta(days=TRACK_DAYS)
        n = _exec(
            """
            INSERT INTO high_impact_rns
                (rns_id, symbol, company_name, headline, url, published_at, tier,
                 category, rules_score, keyword_hits, summary, llm_score,
                 llm_confidence, llm_thesis, llm_risks, story_close,
                 vet_verdict, vet_confidence, vet_rationale, vet_model, vet_processed_at,
                 track_until, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, 'pending')
            ON CONFLICT (rns_id) DO NOTHING
            """,
            (
                c["id"], c["symbol"], c["company_name"], c["headline"], c["url"],
                c["published_at"], c["tier"], c["category"], c["score"],
                c["keyword_hits"], c["summary"], c["llm_score"], c["llm_confidence"],
                c["llm_thesis"], c["llm_risks"], story_close,
                (vet or {}).get("verdict"), (vet or {}).get("confidence"),
                (vet or {}).get("rationale"), (vet or {}).get("model"),
                datetime.now(timezone.utc) if vet else None,
                track_until,
            ),
        )
        flagged += n

    return {
        "candidates": len(cands),
        "flagged": flagged,
        "skipped_sentiment": skipped_sentiment,
        "vetted": vetted,
    }


# ── Follow-up recorder ────────────────────────────────────────────────────────
def record_followups() -> dict:
    """Snapshot subsequent tier A/B announcements for every actively tracked
    company, so post-selection news survives the 14-day source prune."""
    active = _q(
        "SELECT id, rns_id, symbol, published_at FROM high_impact_rns "
        "WHERE status IN ('pending', 'approved')"
    )
    inserted = 0
    for e in active:
        newer = _q(
            """
            SELECT id, headline, url, published_at, tier, category, keyword_hits,
                   llm_score, llm_thesis
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


# ── Auto-archive ──────────────────────────────────────────────────────────────
def expire_tracked_entries() -> dict:
    """Archive approved entries whose 31-day tracking window has elapsed."""
    n = _exec(
        "UPDATE high_impact_rns SET status = 'archived', decided_at = NOW() "
        "WHERE status = 'approved' AND track_until IS NOT NULL AND track_until < NOW()"
    )
    return {"archived": n}


# ── Enrichment ────────────────────────────────────────────────────────────────
# MQVR source — copied from the /api/screener SELECT (main.py) so quality/value
# scoring sees the exact same columns (incl. the stored *_median companions).
_MQVR_SQL = """
    SELECT m.symbol, m.sector, m.industry,
           t.market_cap, t.revenue,
           CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END as price_to_earnings,
           t.price_to_book, t.price_to_sales, t.roe, t.roic,
           t.gross_margin, t.operating_margin, t.net_income_margin,
           t.eps_cagr_10, t.eps_diluted, t.fcf_margin,
           t.dividends_per_share, t.dividend_yield, t.period_end_price, t.fcf,
           t.gross_margin_median, t.operating_margin_median,
           t.net_margin_median, t.roe_median, t.roic_median,
           a.total_analysts, a.eps_growth_next_yr, a.eps_est_current_yr,
           s.momentum_score
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


def _enrich(entries: list[dict]) -> list[dict]:
    """Turn raw high_impact_rns rows into full showcase rows: watchlist parity +
    MQVR scores + days/%-since-news + follow-up tally + the story block."""
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
        }
        for r in mrows
    }

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

    now = datetime.now(timezone.utc)
    out = []
    for e in entries:
        base = dict(watchlist.get(e["symbol"]) or {
            "symbol": e["symbol"], "name": e.get("company_name"),
        })
        m = mqvr.get(e["symbol"], {})
        fus = fu_map.get(e["id"], [])

        # % since news: story-date close (snapshotted at flag time) vs latest price.
        baseline = float(e["story_close"]) if e.get("story_close") is not None \
            else _story_close(e["symbol"], e["published_at"])
        cur = base.get("current_price")
        pct = None
        if baseline and cur is not None and baseline > 0:
            pct = round((cur / baseline - 1) * 100, 2)

        out.append({
            **base,
            "showcase_id": e["id"],
            "momentum_score": m.get("momentum_score"),
            "quality_score": m.get("quality_score"),
            "value_score": m.get("value_score"),
            "days_since_news": (now - e["published_at"]).days,
            "pct_since_news": pct,
            "spark_since": _spark_since_count(e["symbol"], e["published_at"]),
            "track_until": e.get("track_until"),
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
        "SELECT * FROM high_impact_rns WHERE status = 'approved' ORDER BY published_at DESC"
    )
    return _enrich(entries)


@router.get("/pending", dependencies=[Depends(require_admin_token)])
def list_pending():
    """Admin — candidates awaiting approval, newest flag first."""
    entries = _q(
        "SELECT * FROM high_impact_rns WHERE status = 'pending' ORDER BY flagged_at DESC"
    )
    return _enrich(entries)


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


@router.post("/{entry_id}/extend", dependencies=[Depends(require_admin_token)])
def extend_tracking(entry_id: int):
    """Admin — push an approved entry's tracking window out by EXTEND_DAYS."""
    rows = _q(
        "UPDATE high_impact_rns "
        "SET track_until = GREATEST(COALESCE(track_until, NOW()), NOW()) "
        "                  + (%s || ' days')::interval "
        "WHERE id = %s AND status = 'approved' RETURNING track_until",
        (EXTEND_DAYS, entry_id),
    )
    if not rows:
        raise HTTPException(404, "approved showcase entry not found")
    return {"id": entry_id, "track_until": rows[0]["track_until"]}


@router.post("/flag", dependencies=[Depends(require_admin_token)])
def flag_now(hours: int = 48):
    """Admin — manually run the auto-flag pass (dev/testing convenience)."""
    return flag_high_impact_candidates(hours=hours)
