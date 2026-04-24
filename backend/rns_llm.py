"""DeepSeek-backed LLM ranker for RNS announcements.

Takes rows that passed the rules-based coarse filter (tier A/B) and produces a
structured score + thesis + action + risks. Context assembled per-row:
  - headline, category, tier, keyword_hits, rules score
  - investegate AI summary (scraped via rns._fetch_summary)
  - company_metadata: sector, industry, country, ftse_index
  - ttm_fundamentals: market_cap
  - recent RNS history for the same ticker (last 60 days)

Uses DeepSeek's OpenAI-compatible API. Requires DEEPSEEK_API_KEY in env.
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from dotenv import load_dotenv

from rns import _query, _get_pool

load_dotenv()

router = APIRouter(prefix="/api/rns", tags=["rns-llm"])

_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

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
    """Load the announcement plus enrichment (company, market cap, history)."""
    rows = _query("""
        SELECT a.id, a.published_at, a.wire, a.ticker, a.symbol, a.company_name,
               a.headline, a.headline_slug, a.url, a.tier, a.category,
               a.keyword_hits, a.score, a.summary,
               m.sector, m.industry, m.country, m.ftse_index,
               t.market_cap
        FROM rns_announcements a
        LEFT JOIN company_metadata m ON m.symbol = a.symbol
        LEFT JOIN LATERAL (
            SELECT market_cap FROM ttm_financials
            WHERE company_symbol = a.symbol
            ORDER BY period_end_date DESC NULLS LAST
            LIMIT 1
        ) t ON TRUE
        WHERE a.id = %s
    """, (row_id,))
    return rows[0] if rows else None


def _load_history(symbol: Optional[str], limit: int = 10) -> list[dict]:
    """Last `limit` RNS items for this issuer, excluding routine noise."""
    if not symbol:
        return []
    return _query("""
        SELECT published_at, tier, category, headline
        FROM rns_announcements
        WHERE symbol = %s
          AND tier IN ('A', 'B')
          AND published_at >= NOW() - INTERVAL '60 days'
        ORDER BY published_at DESC
        LIMIT %s
    """, (symbol, limit))


def _format_market_cap(mc: Optional[float]) -> str:
    if mc is None:
        return "unknown"
    if mc >= 1e9:
        return f"£{mc/1e9:.1f}bn"
    if mc >= 1e6:
        return f"£{mc/1e6:.0f}m"
    return f"£{mc:.0f}"


def _build_messages(cand: dict, history: list[dict]) -> list[dict]:
    """Construct the DeepSeek chat messages. Forces JSON output via prompt."""
    system = (
        "You rank UK stock announcements (RNS feed) on how likely they are to "
        "move the share price materially. Be sceptical — most announcements are "
        "noise. An item is only 'high-impact' if it changes the investment case "
        "(earnings, M&A, strategy, solvency). Routine updates are low-impact. "
        "Always weigh company size: a £50m contract is transformational for a "
        "£100m microcap, trivial for a FTSE100. Return STRICT JSON only."
    )

    hist_lines = (
        "\n".join(
            f"  - {h['published_at'].strftime('%Y-%m-%d')}  [{h['tier']}] "
            f"{h['category'] or '?'}: {h['headline']}"
            for h in history
        ) or "  (no prior tier A/B items in last 60 days)"
    )

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

Investegate AI summary
{cand.get('summary') or '(not available)'}

Recent issuer RNS history (tier A/B only, last 60 days)
{hist_lines}

Produce a JSON object with these fields exactly:
  score        integer 0-100; price-impact likelihood × magnitude
  confidence   one of: "high", "medium", "low"
  thesis       one sentence: why this matters (or why it doesn't)
  action       one of: "watch", "research", "ignore"
  risks        one sentence: what would invalidate the thesis

Return JSON only — no preamble, no code fence."""

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


# ── LLM call + persistence ────────────────────────────────────────────────────

def _call_deepseek(messages: list[dict]) -> dict:
    client = _get_client()
    resp = client.chat.completions.create(
        model=_DEEPSEEK_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=400,
    )
    content = resp.choices[0].message.content
    return json.loads(content)


def _save_ranking(ann_id: int, result: dict, model: str) -> None:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE rns_announcements
            SET llm_score        = %s,
                llm_confidence   = %s,
                llm_thesis       = %s,
                llm_action       = %s,
                llm_risks        = %s,
                llm_model        = %s,
                llm_processed_at = NOW()
            WHERE id = %s
        """, (
            _clip_int(result.get("score"), 0, 100),
            (result.get("confidence") or "").lower()[:10] or None,
            (result.get("thesis") or "")[:500] or None,
            (result.get("action") or "").lower()[:10] or None,
            (result.get("risks") or "")[:500] or None,
            model,
            ann_id,
        ))
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
    messages = _build_messages(cand, history)
    result = _call_deepseek(messages)
    _save_ranking(row_id, result, _DEEPSEEK_MODEL)
    return {"id": row_id, **result}


def _rank_pending(limit: int = 50, tiers: tuple = ("A", "B"),
                  hours: int = 72) -> dict:
    """Rank recent tier A/B rows that haven't been processed yet."""
    rows = _query("""
        SELECT id
        FROM rns_announcements
        WHERE tier = ANY(%s)
          AND llm_processed_at IS NULL
          AND published_at >= NOW() - (%s || ' hours')::interval
        ORDER BY published_at DESC
        LIMIT %s
    """, (list(tiers), str(hours), limit))

    ranked = errors = 0
    for r in rows:
        try:
            _rank_one(r["id"])
            ranked += 1
        except Exception as e:
            print(f"[rns_llm] rank failed for {r['id']}: {e}")
            errors += 1
    result = {"candidates": len(rows), "ranked": ranked, "errors": errors}
    print(f"[rns_llm] ranking done — {result}")
    return result


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.post("/rank")
def rank(background_tasks: BackgroundTasks,
         limit: int = Query(50, ge=1, le=500),
         hours: int = Query(72, ge=1, le=168)):
    """Kick off LLM ranking for pending tier A/B rows."""
    background_tasks.add_task(_rank_pending, limit, ("A", "B"), hours)
    return {"status": "ranking started", "limit": limit, "hours": hours}


@router.post("/rank/{row_id}")
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
):
    """LLM-ranked feed for the morning screen."""
    return _query("""
        SELECT id, published_at, ticker, symbol, company_name, headline, url,
               tier, category, score,
               llm_score, llm_confidence, llm_thesis, llm_action, llm_risks,
               llm_model, llm_processed_at
        FROM rns_announcements
        WHERE llm_processed_at IS NOT NULL
          AND llm_score >= %s
          AND published_at >= NOW() - (%s || ' hours')::interval
        ORDER BY llm_score DESC, published_at DESC
        LIMIT %s
    """, (min_llm_score, str(hours), limit))
