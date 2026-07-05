"""DeepSeek-backed LLM ranker for RNS announcements.

Takes rows that passed the rules-based coarse filter (tier A/B) and produces a
structured score + thesis + action + risks. Context assembled per-row:
  - headline, category, tier, keyword_hits, rules score
  - investegate AI summary (scraped via rns._fetch_summary)
  - company_metadata: sector, industry, country, ftse_index
  - ttm_financials: market_cap, P/E, dividend yield, ROIC, ROE, margins,
    growth rates, debt/equity, quality_score, risk_score
  - analyst_snapshots: consensus, buy %, upside %, # analysts, fwd EPS growth
  - price_history: 1-month and 6-month price change
  - recent RNS history for the same ticker (last 60 days)

Uses DeepSeek's OpenAI-compatible API. Requires DEEPSEEK_API_KEY in env.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from dotenv import load_dotenv

from admin_auth import require_admin_token
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
    """Load the announcement plus enrichment (company, fundamentals, analysts).

    If market_cap is missing from ttm_financials (e.g. the company isn't in the
    financials DB yet), falls back to a Yahoo Finance lookup via the shared
    market-cap cache in rns.py.
    """
    rows = _query(
        """
        SELECT a.id, a.published_at, a.wire, a.ticker, a.symbol, a.company_name,
               a.headline, a.headline_slug, a.url, a.tier, a.category,
               a.keyword_hits, a.score, a.summary,
               m.sector, m.industry, m.country, m.ftse_index,
               t.market_cap,
               CASE WHEN t.price_to_earnings > 999 OR t.price_to_earnings <= 0
                    THEN NULL ELSE t.price_to_earnings END AS price_to_earnings,
               CASE WHEN t.period_end_price > 0 AND t.dividends_per_share > 0
                    THEN t.dividends_per_share / t.period_end_price
                    ELSE NULL END AS dividend_yield,
               t.price_to_book, t.price_to_sales,
               t.roic, t.roe, t.operating_margin, t.fcf_margin,
               t.revenue_growth, t.eps_cagr_10,
               t.debt_to_equity, t.current_ratio,
               t.net_debt, t.ebitda,
               t.gross_margin, t.net_income_margin,
               t.gross_margin_median, t.operating_margin_median,
               t.net_margin_median, t.roe_median, t.roic_median,
               t.revenue, t.fcf, t.period_end_price,
               s.consensus, s.buy_pct, s.upside_pct, s.total_analysts,
               s.eps_growth_next_yr
        FROM rns_announcements a
        LEFT JOIN company_metadata m ON m.symbol = a.symbol
        LEFT JOIN LATERAL (
            SELECT market_cap, price_to_earnings, dividends_per_share, period_end_price,
                   price_to_book, price_to_sales,
                   roic, roe, operating_margin, fcf_margin,
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
    """Last `limit` RNS items for this issuer, excluding routine noise."""
    if not symbol:
        return []
    return _query(
        """
        SELECT published_at, tier, category, headline
        FROM rns_announcements
        WHERE symbol = %s
          AND tier IN ('A', 'B')
          AND published_at >= NOW() - INTERVAL '60 days'
        ORDER BY published_at DESC
        LIMIT %s
    """,
        (symbol, limit),
    )


def _format_market_cap(mc: Optional[float]) -> str:
    if mc is None:
        return "unknown"
    if mc >= 1e9:
        return f"£{mc/1e9:.1f}bn"
    if mc >= 1e6:
        return f"£{mc/1e6:.0f}m"
    return f"£{mc:.0f}"


def _format_net_debt(nd: Optional[float]) -> str:
    """Sign-aware money format; negative net debt is surfaced as net cash."""
    if nd is None:
        return "n/a"
    if nd < 0:
        return f"{_format_market_cap(-nd)} net cash"
    return _format_market_cap(nd)


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:+.1f}%"


def _fmt_num(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{decimals}f}"


# ── Quality & risk helpers (ported from main.py) ──────────────────────────────


def _quality_score(r: dict) -> Optional[int]:
    """Quality score 0-10: rewards high AND consistent returns/margins."""
    score = 0
    roic = r.get("roic")
    roic_med = r.get("roic_median")
    roe = r.get("roe")
    roe_med = r.get("roe_median")
    gm = r.get("gross_margin")
    gm_med = r.get("gross_margin_median")
    om = r.get("operating_margin")
    om_med = r.get("operating_margin_median")
    fcfm = r.get("fcf_margin")
    nm = r.get("net_income_margin")
    nm_med = r.get("net_margin_median")

    if roic is not None:
        if roic > 0.10:
            score += 1
        if roic_med is not None and roic >= roic_med:
            score += 1
    if roe is not None:
        if roe > 0.15:
            score += 1
        if roe_med is not None and roe >= roe_med:
            score += 1
    if gm is not None:
        if gm > 0.30:
            score += 1
        if gm_med is not None and gm >= gm_med:
            score += 1
    if om is not None:
        if om > 0.10:
            score += 1
        if om_med is not None and om >= om_med:
            score += 1
    if fcfm is not None:
        if fcfm > 0.05:
            score += 1
        if nm is not None and nm_med is not None and nm >= nm_med:
            score += 1

    return score


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


def _build_messages(cand: dict, history: list[dict], price: dict) -> list[dict]:
    """Construct the DeepSeek chat messages. Forces JSON output via prompt."""
    system = (
        "You rank UK stock announcements (RNS feed) on how likely they are to "
        "move the share price materially. Be sceptical — most announcements are "
        "noise. An item is only 'high-impact' if it changes the investment case "
        "(earnings, M&A, strategy, solvency). Routine updates are low-impact. "
        "Always weigh company size: a £50m contract is transformational for a "
        "£100m microcap, trivial for a FTSE100. Use positioning context too — "
        "news that contradicts analyst consensus has more surprise; news that "
        "confirms a stock that's already rallied or fallen sharply is largely "
        "priced in. "
        "Scrutinise the balance sheet: we avoid highly-indebted companies. Always "
        "weigh net debt against both market cap and profits. Net debt above 3x "
        "EBITDA is a serious red flag, and net debt that exceeds the market cap "
        "means equity holders sit behind a heavy debt load — in both cases treat "
        "the company with caution, call it out in the risks, and hold the score "
        "down unless the announcement directly and materially de-levers the "
        "balance sheet. "
        "Weigh business quality too. A low quality score (<=3/10), a net margin "
        "below the sector median (judge margins sector-relative — a thin margin "
        "is normal in some sectors; below the sector's own norm is the red flag, "
        "loss-making doubly so), or a deteriorating margin / EPS trend means the "
        "underlying business is weak and converts good news into shareholder "
        "value poorly. For a positive catalyst on such a low-quality name, temper "
        "the score and flag the fragile fundamentals in the risks rather than "
        "taking the upgrade at face value. Return STRICT JSON only."
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
    net_debt = cand.get("net_debt")
    ebitda = cand.get("ebitda")
    mcap = cand.get("market_cap")
    nd_to_mktcap = (net_debt / mcap) if (net_debt is not None and mcap and mcap > 0) else None
    nd_to_ebitda = (net_debt / ebitda) if (net_debt is not None and ebitda and ebitda > 0) else None
    leverage_flag = ""
    if nd_to_ebitda is not None and nd_to_ebitda > 3:
        leverage_flag = "  !! HIGH LEVERAGE (net debt > 3x profit)"
    elif nd_to_mktcap is not None and nd_to_mktcap > 1:
        leverage_flag = "  !! net debt exceeds market cap"

    # ── Quality: weak or below-sector-margin businesses convert good news ────
    # poorly. Margins are judged sector-relative — thin-margin sectors aren't
    # penalised wholesale, but a name below its own sector's median (or
    # loss-making) is fragile and a positive catalyst deserves a tempered score.
    nim = cand.get("net_income_margin")
    nim_median = cand.get("net_margin_median")
    margin_floor = max(0.0, nim_median) if nim_median is not None else 0.02
    quality_flag = ""
    if qs is not None and qs <= 3:
        quality_flag = "  !! LOW QUALITY (weak fundamentals)"
    elif nim is not None and nim < margin_floor:
        quality_flag = (
            "  !! WEAK MARGINS (loss-making)" if nim < 0
            else "  !! WEAK MARGINS (below sector median)"
        )

    quality_str = f"{qs}/10" if qs is not None else "n/a"
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
        f"  Net debt:     {_format_net_debt(net_debt)}"
        f"   Net debt/EBITDA: {_fmt_num(nd_to_ebitda, 1)}x"
        f"   Net debt/mkt cap: {_fmt_num(nd_to_mktcap, 1)}x{leverage_flag}\n"
        f"  P/B:          {_fmt_num(pb, 2)}x   P/S: {_fmt_num(ps, 2)}x\n"
        f"  Net margin:   {_fmt_pct(nim)} (sector median {_fmt_pct(nim_median)})"
        f"   Gross margin: {_fmt_pct(cand.get('gross_margin'))}\n"
        f"  Quality:      {quality_str}   Risk: {risk_str}{risk_label}{quality_flag}"
    )

    if fwd_eps is not None:
        health_lines += (
            f"\n  Fwd EPS gr:   {_fmt_pct(fwd_eps)}  ({n_analysts or 0} analysts)"
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

Market context
  Valuation:    {valuation_line}
  Analysts:     {analyst_line}
  Price change: {price_line}

Financial health
{health_lines}

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
        {"role": "user", "content": user},
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
        cur.execute(
            """
            UPDATE rns_announcements
            SET llm_score        = %s,
                llm_confidence   = %s,
                llm_thesis       = %s,
                llm_action       = %s,
                llm_risks        = %s,
                llm_model        = %s,
                llm_processed_at = NOW()
            WHERE id = %s
        """,
            (
                _clip_int(result.get("score"), 0, 100),
                (result.get("confidence") or "").lower()[:10] or None,
                (result.get("thesis") or "")[:500] or None,
                (result.get("action") or "").lower()[:10] or None,
                (result.get("risks") or "")[:500] or None,
                model,
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
    messages = _build_messages(cand, history, price)
    result = _call_deepseek(messages)
    _save_ranking(row_id, result, _DEEPSEEK_MODEL)
    return {"id": row_id, **result}


def _rank_pending(limit: int = 50, tiers: tuple = ("A", "B"), hours: int = 72) -> dict:
    """Rank recent tier A/B rows that haven't been processed yet."""
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


@router.post("/rank", dependencies=[Depends(require_admin_token)])
def rank(
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=500),
    hours: int = Query(72, ge=1, le=168),
):
    """Kick off LLM ranking for pending tier A/B rows."""
    background_tasks.add_task(_rank_pending, limit, ("A", "B"), hours)
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
               llm_model, llm_processed_at
        FROM rns_announcements
        WHERE llm_processed_at IS NOT NULL
          AND llm_score >= %s
          AND published_at >= NOW() - (%s || ' hours')::interval
        ORDER BY llm_score DESC, published_at DESC
        LIMIT %s
    """,
        (min_llm_score, str(hours), limit),
    )
