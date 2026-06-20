import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import psycopg2.pool
from typing import Optional
from dotenv import load_dotenv
import os
from market import router as market_router
from prices import router as prices_router, _attach_momentum, _trailing_streak
from analysts import router as analysts_router
from rns import router as rns_router
from rns_llm import router as rns_llm_router
from news import router as news_router
from subscribers import router as subscribers_router
from feedback import router as feedback_router
from email_rns_digest import main as run_digest
from sectors import to_icb, to_gics

load_dotenv()

app = FastAPI(title="Finance API")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(market_router)
app.include_router(prices_router)
app.include_router(analysts_router)
app.include_router(rns_router)
app.include_router(rns_llm_router)
app.include_router(news_router)
app.include_router(subscribers_router)
app.include_router(feedback_router)

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **DB_CONFIG)
    return _pool


def query(sql, params=None):
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except psycopg2.OperationalError:
        # Connection was dropped (e.g. SSL timeout) — discard it and retry once
        pool.putconn(conn, close=True)
        conn = pool.getconn()
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        pool.putconn(conn)


SITEMAP_BASE = os.environ.get("SITE_URL", "https://app.alphamoveai.co.uk").rstrip("/")

# Static frontend routes mirrored from the Next app (kept in sync manually — there
# are only a handful). Per-company URLs are appended from the DB at request time.
_SITEMAP_STATIC = [
    ("/", "daily", "1.0"),
    ("/screener", "daily", "0.9"),
    ("/markets", "daily", "0.8"),
    ("/trending", "daily", "0.8"),
    ("/analysts", "daily", "0.7"),
    ("/rns", "daily", "0.7"),
    ("/heatmap", "daily", "0.6"),
    ("/benchmarks", "weekly", "0.5"),
    ("/subscribe", "monthly", "0.5"),
    ("/donate", "yearly", "0.3"),
    ("/feedback", "yearly", "0.3"),
]


@app.get("/sitemap.xml")
def sitemap_xml():
    # Served by the backend (not Next) so the full ~500-stock universe comes straight
    # from the DB — no build-time loopback fetch that can silently fall back to an
    # empty company list. Routed via the /sitemap.xml entry in vercel.json.
    from urllib.parse import quote
    from xml.sax.saxutils import escape

    rows = query(
        "SELECT symbol FROM company_metadata WHERE is_active ORDER BY symbol"
    )
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, freq, prio in _SITEMAP_STATIC:
        loc = escape(f"{SITEMAP_BASE}{path}")
        parts.append(
            f"<url><loc>{loc}</loc><changefreq>{freq}</changefreq>"
            f"<priority>{prio}</priority></url>"
        )
    for r in rows:
        loc = escape(f"{SITEMAP_BASE}/company?symbol={quote(r['symbol'])}")
        parts.append(
            f"<url><loc>{loc}</loc><changefreq>daily</changefreq>"
            f"<priority>0.6</priority></url>"
        )
    parts.append("</urlset>")
    return Response(
        content="\n".join(parts),
        media_type="application/xml",
        headers={"Cache-Control": "public, s-maxage=86400, stale-while-revalidate=86400"},
    )


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), response: Response = None):
    # The universe only changes on the quarterly index refresh — hold a day at the
    # edge so repeat type-ahead queries don't re-invoke the function.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=86400"
    return query(
        """
        SELECT symbol, name, sector, industry, exchange, country
        FROM company_metadata
        WHERE symbol ILIKE %s OR name ILIKE %s
        ORDER BY symbol LIMIT 20
    """,
        (f"{q}%", f"%{q}%"),
    )


@app.get("/api/company")
def company(symbol: str = Query(...), response: Response = None):
    # Company metadata changes only on the quarterly index refresh — safe to hold
    # at the edge for a day so repeat profile views don't re-invoke the function.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=86400"
    rows = query("SELECT * FROM company_metadata WHERE symbol = %s", (symbol,))
    if not rows:
        raise HTTPException(404, "Not found")
    return rows[0]


@app.get("/api/snapshot")
def snapshot(symbol: str = Query(...), response: Response = None):
    # Does a price_history scan + risk computation per call; the underlying data
    # only changes daily, so hold it a full day at the edge to remove both the DB
    # read and the CPU on every repeat view within the day.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=86400"
    rows = query(
        """
        SELECT t.*, m.sector
        FROM ttm_financials t
        LEFT JOIN company_metadata m ON m.symbol = t.company_symbol
        WHERE t.company_symbol = %s
        """,
        (symbol,),
    )
    if not rows:
        raise HTTPException(404, "No data")
    row = rows[0]
    # _attach_risk_score expects a 'symbol' key (screener convention)
    row["symbol"] = symbol
    _attach_risk_score([row])
    row.pop("symbol", None)
    return row


@app.get("/api/annual")
def annual(symbol: str = Query(...), response: Response = None):
    # Annual financials change at most a few times a year — hold 6h at the edge.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=21600, stale-while-revalidate=86400"
    return query(
        """
        SELECT * FROM annual_financials
        WHERE company_symbol = %s
        ORDER BY period_end_date ASC
    """,
        (symbol,),
    )


@app.get("/api/quarterly")
def quarterly(symbol: str = Query(...), response: Response = None):
    # Quarterly financials change ~4x/year — hold 6h at the edge.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=21600, stale-while-revalidate=86400"
    return query(
        """
        SELECT * FROM quarterly_financials
        WHERE company_symbol = %s
        ORDER BY period_end_date ASC
        LIMIT 20
    """,
        (symbol,),
    )


def _piotroski_score(row):
    """Compute Piotroski F-Score (0-9) from an annual_financials row pair."""
    score = 0
    roa_cur = row.get("roa_cur")
    roa_prev = row.get("roa_prev")
    cfo = row.get("cf_cfo")
    ta_cur = row.get("ta_cur") or 0
    de_cur = row.get("de_cur")
    de_prev = row.get("de_prev")
    cr_cur = row.get("cr_cur")
    cr_prev = row.get("cr_prev")
    sh_cur = row.get("sh_cur")
    sh_prev = row.get("sh_prev")
    gm_cur = row.get("gm_cur")
    gm_prev = row.get("gm_prev")
    rev_cur = row.get("rev_cur")
    rev_prev = row.get("rev_prev")
    ta_prev = row.get("ta_prev") or 0

    # Profitability
    if roa_cur is not None and roa_cur > 0:
        score += 1  # F1
    if cfo is not None and cfo > 0:
        score += 1  # F2
    if roa_cur is not None and roa_prev is not None and roa_cur > roa_prev:
        score += 1  # F3
    if (
        cfo is not None
        and ta_cur > 0
        and roa_cur is not None
        and (cfo / ta_cur) > roa_cur
    ):
        score += 1  # F4 accruals
    # Leverage / liquidity
    if de_cur is not None and de_prev is not None and de_cur < de_prev:
        score += 1  # F5
    if cr_cur is not None and cr_prev is not None and cr_cur > cr_prev:
        score += 1  # F6
    if sh_cur is not None and sh_prev is not None and sh_cur <= sh_prev:
        score += 1  # F7 no dilution
    # Efficiency
    if gm_cur is not None and gm_prev is not None and gm_cur > gm_prev:
        score += 1  # F8
    if (
        rev_cur is not None
        and ta_cur > 0  # F9 asset turnover
        and rev_prev is not None
        and ta_prev > 0
        and rev_cur / ta_cur > rev_prev / ta_prev
    ):
        score += 1

    return score


def _quality_score(r):
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


import math as _math


def _altman_z(row, total_assets):
    """Compute Altman Z-Score from a ttm_financials row + total_assets.

    X1 (working capital) is treated as 0 (conservative — unavailable from stored data).
    X2 uses book equity as a proxy for retained earnings.
    X3 uses operating income (operating_margin * revenue) as EBIT proxy.
    Returns None if insufficient data to compute any meaningful score.
    """
    if not total_assets or total_assets <= 0:
        return None

    mc = row.get("market_cap")
    revenue = row.get("revenue")
    op_margin = row.get("operating_margin")
    p2b = row.get("price_to_book")

    z = 0.0
    computed_terms = 0

    # X2 = book_equity / total_assets  (proxy for retained earnings / total_assets)
    book_equity = None
    if mc and p2b and p2b > 0:
        book_equity = mc / p2b
        z += 1.4 * (book_equity / total_assets)
        computed_terms += 1

    # X3 = EBIT / total_assets  (operating income as EBIT proxy)
    if op_margin is not None and revenue:
        ebit = op_margin * revenue
        z += 3.3 * (ebit / total_assets)
        computed_terms += 1

    # X4 = market_cap / total_liabilities
    if book_equity is not None:
        total_liabilities = total_assets - book_equity
        if total_liabilities > 0:
            z += 0.6 * (mc / total_liabilities)
            computed_terms += 1

    # X5 = revenue / total_assets
    if revenue:
        z += 1.0 * (revenue / total_assets)
        computed_terms += 1

    if computed_terms == 0:
        return None

    return round(z, 3)


def _z_to_risk(z):
    """Map Altman Z to 1-10 risk component. Lower Z = higher risk.

    Z >= 3.0 → 1 (safe), Z <= 1.0 → 10 (distress), linear between.
    """
    if z is None:
        return None
    if z >= 3.0:
        return 1
    if z <= 1.0:
        return 10
    # Linear: z=3.0→1, z=1.0→10. Slope = (10-1)/(1.0-3.0) = -4.5
    return round(1 + (3.0 - z) * 4.5)


def _annualised_vol(closes):
    """Compute annualised volatility from a list of closes (oldest first).

    Returns annualised std of log returns, or None if fewer than 2 prices.
    """
    if len(closes) < 2:
        return None
    log_returns = [_math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(log_returns)
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / (n - 1) if n > 1 else 0.0
    return _math.sqrt(variance) * _math.sqrt(252)


def _vol_to_score(vol):
    """Map annualised volatility to 1-10 risk score using absolute thresholds.

    Thresholds calibrated for FTSE-listed stocks (typical range 10-40% ann. vol).
    Returns None if vol is None.
    """
    if vol is None:
        return None
    thresholds = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
    for i, t in enumerate(thresholds):
        if vol < t:
            return i + 1
    return 10


def _blend_risk(altman_component, vol_component):
    """Combine Altman (60%) and volatility (40%) components into 1-10 score.

    Falls back to whichever component is available. Returns None if both are None.
    """
    if altman_component is not None and vol_component is not None:
        return max(1, min(10, round(0.6 * altman_component + 0.4 * vol_component)))
    if altman_component is not None:
        return max(1, min(10, altman_component))
    if vol_component is not None:
        return max(1, min(10, vol_component))
    return None


def _is_financial(row):
    """True for banks/insurers/financials, where the Altman Z-Score is invalid.

    Altman explicitly excluded financial firms: their balance sheets are mostly
    leverage by design (deposits, policy liabilities), so every Altman term
    collapses toward zero and the score wrongly flags them as distressed.
    """
    sector = (row.get("sector") or "").lower()
    return "financ" in sector or "bank" in sector or "insurance" in sector


def _roe_to_risk(roe):
    """Map return on equity to a 1-10 risk component for financials.

    Higher ROE = lower risk. ROE >= 15% → 2 (strong), ROE <= 0 → 10 (weak),
    linear between. Floored at 2 since ROE alone is a coarse proxy.
    """
    if roe is None:
        return None
    if roe >= 0.15:
        return 2
    if roe <= 0.0:
        return 10
    # Linear: roe=0.15→2, roe=0.0→10.
    return round(2 + (0.15 - roe) * (8 / 0.15))


def _financial_risk(roe_component, vol_component):
    """Risk for financials: 60% volatility + 40% ROE/quality, no Altman.

    Falls back to whichever component is available (volatility-only when ROE is
    missing); returns None if neither is available.
    """
    if roe_component is not None and vol_component is not None:
        return max(1, min(10, round(0.6 * vol_component + 0.4 * roe_component)))
    if vol_component is not None:
        return max(1, min(10, vol_component))
    if roe_component is not None:
        return max(1, min(10, roe_component))
    return None


# PEGY growth is capped so a one-off recovery bounce (e.g. +150% off a depressed
# base) can't inflate the denominator and make junk look ultra-cheap.
_PEGY_GROWTH_CAP = 0.30


def _forward_pe(r, _f):
    """Forward P/E rebased onto analyst EPS estimates, currency-safe.

    Trailing statutory P/E can be badly distorted by one-off items — e.g. a
    disposal gain or deferred-tax credit inflates reported EPS and makes the
    trailing P/E (and PEGY) look cheap (Rolls-Royce), while a depressed statutory
    year does the reverse (Legal & General). When an analyst estimate for the
    current fiscal year exists we rebase onto forward earnings:

        forward_PE = trailing_PE * (eps_diluted / eps_est_current_yr)

    This equals price / eps_est_current_yr, but multiplying the ratio keeps it
    unit/currency-safe: eps_diluted and the estimate are both in the company's
    reporting currency (so their ratio is dimensionless) while trailing_PE already
    handles the pence-price vs reporting-currency-EPS conversion. That matters for
    USD reporters like AZN/SHEL whose price is quoted in GBp.

    Falls back to the trailing P/E when no usable estimate exists. Returns None
    when there is no positive P/E to work from.
    """
    trailing_pe = _f(r.get("price_to_earnings"))
    if trailing_pe is None or trailing_pe <= 0:
        return None
    eps_dil = _f(r.get("eps_diluted"))
    est_cur = _f(r.get("eps_est_current_yr"))
    if eps_dil is not None and eps_dil > 0 and est_cur is not None and est_cur > 0:
        return trailing_pe * eps_dil / est_cur
    return trailing_pe


def _attach_pegy(results):
    """Add pegy ratio to each screener result row.

    PEGY = forward P/E / (growth% + dividend yield%). Lower = cheaper relative to
    growth+income. The numerator is a forward (analyst-estimate-based) P/E rather
    than the trailing statutory P/E so one-off earnings items can't make a stock
    look cheap when it isn't — see _forward_pe.

    Growth is a blend of forward analyst EPS growth (when >=3 analysts cover the
    stock) and the 10Y trailing EPS CAGR, so every stock is scored on the same
    definition rather than some on a noisy 1Y forward and others on a 10Y trailing
    number. Each leg is capped at _PEGY_GROWTH_CAP before blending.

    PEG/PEGY is only meaningful for growing earnings, so rows whose blended growth
    is not positive are left as None (a fat yield can't mask an EPS decline).

    Yield derived from dividends_per_share / period_end_price (same vintage as P/E).
    Returns None when inputs are missing or the denominator is too small to be meaningful.
    """

    def _f(x):
        return float(x) if x is not None else None

    def _cap(g):
        return min(g, _PEGY_GROWTH_CAP) if g is not None else None

    for r in results:
        r["pegy"] = None
        pe = _forward_pe(r, _f)
        if pe is None or pe <= 0:
            continue

        total = r.get("total_analysts") or 0
        fwd  = _cap(_f(r.get("eps_growth_next_yr"))) if total >= 3 else None
        cagr = _cap(_f(r.get("eps_cagr_10")))
        # Blend both legs when available; otherwise use whichever exists.
        if fwd is not None and cagr is not None:
            growth = 0.5 * fwd + 0.5 * cagr
        elif fwd is not None:
            growth = fwd
        elif cagr is not None:
            growth = cagr
        else:
            continue

        # Skip shrinking / flat earnings — PEGY is meaningless there.
        if growth <= 0:
            continue

        # Dividend yield (as a fraction). Prefer the clean, currency-free
        # dividend_yield (from yfinance info['dividendYield']); fall back to the
        # legacy dividends_per_share / period_end_price only when it's absent.
        # The fallback is unreliable for non-GBP reporters (per-share figure is in
        # the reporting currency while price is GBp) — see migration 002.
        yld = _f(r.get("dividend_yield"))
        if yld is None:
            dps = _f(r.get("dividends_per_share")) or 0.0
            price = _f(r.get("period_end_price")) or 0.0
            yld = (dps / price) if price > 0 else 0.0

        denom_pct = (growth + yld) * 100
        if denom_pct < 2:
            continue
        r["pegy"] = round(pe / denom_pct, 2)
    return results


def _attach_piotroski(results):
    """Add piotroski_score to each screener result row."""
    if not results:
        return results
    symbols = [r["symbol"] for r in results]
    rows = query(
        """
        WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY company_symbol ORDER BY period_end_date DESC) AS rn
            FROM annual_financials
            WHERE company_symbol = ANY(%s)
        )
        SELECT
            cur.company_symbol,
            cur.roa          AS roa_cur,   prv.roa          AS roa_prev,
            cur.cf_cfo,
            cur.total_assets AS ta_cur,    prv.total_assets  AS ta_prev,
            cur.debt_to_equity AS de_cur,  prv.debt_to_equity AS de_prev,
            cur.current_ratio  AS cr_cur,  prv.current_ratio  AS cr_prev,
            cur.shares_diluted AS sh_cur,  prv.shares_diluted AS sh_prev,
            cur.gross_margin   AS gm_cur,  prv.gross_margin   AS gm_prev,
            cur.revenue        AS rev_cur, prv.revenue        AS rev_prev
        FROM ranked cur
        LEFT JOIN ranked prv
               ON prv.company_symbol = cur.company_symbol AND prv.rn = 2
        WHERE cur.rn = 1
    """,
        (symbols,),
    )

    scores = {r["company_symbol"]: _piotroski_score(r) for r in rows}
    for r in results:
        r["piotroski_score"] = scores.get(r["symbol"])
    return results


def _attach_risk_score(results):
    """Add risk_score (1-10), altman_z, and volatility_annualised to each result row.

    Fetches total_assets from annual_financials and price history in two bulk queries.
    risk_score = blend of Altman Z component (60%) and volatility component (40%).
    """
    if not results:
        return results

    symbols = [r["symbol"] for r in results]

    # 1. Fetch most recent total_assets per symbol from annual_financials
    ta_rows = query(
        """
        WITH ranked AS (
            SELECT company_symbol, total_assets,
                   ROW_NUMBER() OVER (PARTITION BY company_symbol ORDER BY period_end_date DESC) AS rn
            FROM annual_financials
            WHERE company_symbol = ANY(%s)
        )
        SELECT company_symbol, total_assets FROM ranked WHERE rn = 1
    """,
        (symbols,),
    )
    total_assets_map = {r["company_symbol"]: r["total_assets"] for r in ta_rows}

    # 2. Fetch up to 252 most recent closes per symbol, oldest-first for log-return ordering
    #    rn=1 is the latest date; ORDER BY rn DESC puts oldest (largest rn) first.
    price_rows = query(
        """
        WITH numbered AS (
            SELECT symbol, close,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM price_history
            WHERE symbol = ANY(%s)
        )
        SELECT symbol, close
        FROM numbered
        WHERE rn <= 252
        ORDER BY symbol, rn DESC
    """,
        (symbols,),
    )

    # Group closes by symbol (list is already oldest-first within each symbol)
    closes_map = {}
    for r in price_rows:
        closes_map.setdefault(r["symbol"], []).append(float(r["close"]))

    # 3. Compute and attach scores
    for r in results:
        sym = r["symbol"]
        ta = total_assets_map.get(sym)

        closes = closes_map.get(sym, [])
        vol = _annualised_vol(closes) if len(closes) >= 63 else None
        vol_component = _vol_to_score(vol)

        if _is_financial(r):
            # Altman is invalid for financials — use volatility + ROE quality.
            roe = r.get("roe")
            if roe is None:
                roe = r.get("roe_median")
            r["risk_score"] = _financial_risk(_roe_to_risk(roe), vol_component)
            r["altman_z"] = None
        else:
            z = _altman_z(r, ta)
            altman_component = _z_to_risk(z)
            r["risk_score"] = _blend_risk(altman_component, vol_component)
            r["altman_z"] = z

        r["volatility_annualised"] = round(vol * 100, 1) if vol is not None else None

    return results


def compute_and_store_scores():
    """Recompute the heavy per-symbol scores for the whole universe and upsert
    them into screener_scores.

    Run once daily (after the price refresh). It carries the four expensive
    queries that /api/screener used to fire on every cache miss — momentum,
    Piotroski and risk (annual_financials + price_history scans) — off the
    request path. The endpoint then serves these via a single LEFT JOIN.

    Momentum is percentile-ranked across this full universe, so a stock's score
    no longer shifts with the active filter (it used to rank within the filtered
    result set). Returns a summary dict.
    """
    universe = query(
        """
        SELECT m.symbol, m.sector,
               t.market_cap, t.revenue, t.operating_margin, t.price_to_book,
               t.roe, t.roe_median
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        ORDER BY t.market_cap DESC NULLS LAST
        """
    )
    if not universe:
        return {"symbols": 0, "stored": 0}

    # Each scorer runs one bulk query over the full universe — once, here.
    _attach_momentum(universe)
    _attach_piotroski(universe)
    _attach_risk_score(universe)

    rows = [
        (
            r["symbol"],
            r.get("momentum_score"),
            r.get("piotroski_score"),
            r.get("risk_score"),
            r.get("altman_z"),
            r.get("volatility_annualised"),
        )
        for r in universe
    ]

    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO screener_scores"
            " (symbol, momentum_score, piotroski_score, risk_score, altman_z,"
            "  volatility_annualised, computed_at)"
            " VALUES %s"
            " ON CONFLICT (symbol) DO UPDATE SET"
            "   momentum_score        = EXCLUDED.momentum_score,"
            "   piotroski_score       = EXCLUDED.piotroski_score,"
            "   risk_score            = EXCLUDED.risk_score,"
            "   altman_z              = EXCLUDED.altman_z,"
            "   volatility_annualised = EXCLUDED.volatility_annualised,"
            "   computed_at           = now()",
            rows,
            template="(%s, %s, %s, %s, %s, %s, now())",
            page_size=1000,
        )
        conn.commit()
        return {"symbols": len(universe), "stored": len(rows)}
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


_screener_cache: dict = {}
_SCREENER_TTL = 21600  # 6h — underlying data only refreshes once/day (matches edge s-maxage)


@app.get("/api/screener")
def screener(
    response: Response,
    sector: Optional[str] = None,
    exclude_sectors: Optional[str] = None,
    country: Optional[str] = None,
    ftse_index: Optional[str] = None,
    min_market_cap: Optional[float] = None,
    max_pe: Optional[float] = None,
    min_roe: Optional[float] = None,
    min_revenue_growth: Optional[float] = None,
    consensus: Optional[str] = None,
    min_upside_pct: Optional[float] = None,
    limit: int = 100,
):
    # Vercel edge CDN cache — the underlying data only changes once/day (17:00
    # UTC Render cron), and the frontend now calls a single canonical URL
    # (no filters; it filters client-side), so this is one cache key for all
    # users. Fresh for 6h, then serve stale up to 24h while refetching in the
    # background, so a user never waits on the ~13s cold-start MISS.
    response.headers["Cache-Control"] = "public, s-maxage=21600, stale-while-revalidate=86400"
    import time
    cache_key = (
        sector, exclude_sectors, country, ftse_index, min_market_cap, max_pe,
        min_roe, min_revenue_growth, consensus, min_upside_pct, limit,
    )
    now = time.time()
    cached = _screener_cache.get(cache_key)
    if cached and now - cached[1] < _SCREENER_TTL:
        return cached[0]

    wheres = ["1=1"]
    params = []
    # Filters arrive as ICB names (what the UI shows); the DB stores raw GICS, so
    # map back before matching. See backend/sectors.py.
    if sector:
        wheres.append("m.sector = ANY(%s)")
        params.append(to_gics(sector))
    if exclude_sectors:
        excluded = [s.strip() for s in exclude_sectors.split(",") if s.strip()]
        if excluded:
            gics_excluded = [g for s in excluded for g in to_gics(s)]
            wheres.append("m.sector <> ALL(%s)")
            params.append(gics_excluded)
    if country:
        wheres.append("m.country = %s")
        params.append(country)
    if ftse_index:
        if ftse_index == "FTSE 350":
            wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250')")
        elif ftse_index == "FTSE All-Share":
            wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250', 'FTSE SmallCap')")
        else:
            wheres.append("m.ftse_index = %s")
            params.append(ftse_index)
    if min_market_cap:
        wheres.append("t.market_cap >= %s")
        params.append(min_market_cap)
    if max_pe:
        wheres.append("t.price_to_earnings <= %s AND t.price_to_earnings > 0")
        params.append(max_pe)
    if min_roe:
        wheres.append("t.roe >= %s")
        params.append(min_roe)
    if min_revenue_growth:
        wheres.append("t.revenue_growth >= %s")
        params.append(min_revenue_growth)
    if consensus:
        wheres.append("a.consensus = %s")
        params.append(consensus)
    if min_upside_pct:
        wheres.append("a.upside_pct >= %s")
        params.append(min_upside_pct)
    params.append(limit)
    sql = f"""
        SELECT m.symbol, m.name, m.sector, m.country, m.exchange, m.ftse_index, m.financial_currency,
               t.market_cap, t.revenue, t.net_income,
               CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END as price_to_earnings,
               t.price_to_book, t.price_to_sales, t.roe, t.roa, t.roic, t.roce,
               t.gross_margin, t.operating_margin, t.net_income_margin,
               t.revenue_growth, t.eps_diluted_growth, t.fcf_growth,
               t.debt_to_equity, t.current_ratio, t.fcf, t.ebitda,
               t.revenue_cagr_10, t.eps_cagr_10, t.eps_diluted, t.period_end_date,
               t.fcf_margin, t.dividends_per_share, t.dividend_yield, t.period_end_price,
               t.gross_margin_median, t.operating_margin_median,
               t.net_margin_median, t.roe_median, t.roic_median,
               a.consensus, a.buy_pct, a.upside_pct, a.total_analysts, a.revision_score,
               a.eps_growth_next_yr, a.eps_est_current_yr,
               s.momentum_score, s.piotroski_score, s.risk_score,
               s.altman_z, s.volatility_annualised,
               COALESCE(p.latest_close, t.period_end_price) AS current_price
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol)
                symbol, consensus, buy_pct, upside_pct, total_analysts, revision_score,
                eps_growth_next_yr, eps_est_current_yr
            FROM analyst_snapshots
            ORDER BY symbol, snapshot_date DESC
        ) a ON a.symbol = m.symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol) symbol, close AS latest_close
            FROM price_history
            ORDER BY symbol, date DESC
        ) p ON p.symbol = m.symbol
        LEFT JOIN screener_scores s ON s.symbol = m.symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY t.market_cap DESC NULLS LAST
        LIMIT %s
    """
    results = query(sql, params)
    # momentum / piotroski / risk / altman_z / volatility now come precomputed via
    # the screener_scores JOIN (see compute_and_store_scores). quality_score and
    # pegy stay inline — they read only columns already in this query, no extra DB hit.
    for r in results:
        r["quality_score"] = _quality_score(r)
    _attach_pegy(results)
    # Surface ICB labels so the table matches the sidebar/heatmap. Done last so
    # scoring above still sees the raw GICS sector it was built against.
    for r in results:
        r["sector"] = to_icb(r["sector"])
    _screener_cache[cache_key] = (results, now)
    return results


_quote_cache: dict = {}
_QUOTE_TTL = 60  # seconds


@app.get("/api/quotes")
def quotes(symbols: str, response: Response):
    """Return live last-price for each symbol via yfinance fast_info. 60s cache per symbol."""
    import time
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    requested = [s.strip() for s in symbols.split(",") if s.strip()]
    if not requested:
        return {}

    # Live prices are already designed to be up to 60s stale (_QUOTE_TTL); mirror
    # that at the edge so many tabs polling the same symbol(s) collapse to one
    # function call per symbol-set per minute instead of one per poll per user.
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=60"

    now = time.time()
    out = {}
    misses = []
    for sym in requested:
        cached = _quote_cache.get(sym)
        if cached and now - cached[1] < _QUOTE_TTL:
            out[sym] = cached[0]
        else:
            misses.append(sym)

    def _fetch(sym):
        # Try intraday (1-min bars) first — gives a near-live price during
        # market hours. Falls back to daily if market is closed or intraday
        # is unavailable.
        for period, interval in (("2d", "1m"), ("5d", "1d")):
            try:
                h = yf.Ticker(sym).history(
                    period=period, interval=interval, auto_adjust=False
                )
                if h.empty:
                    continue
                close = h["Close"].dropna()
                if len(close) > 0:
                    return sym, float(close.iloc[-1])
            except Exception as e:
                print(f"[quotes] {sym} {interval} failed: {e}")
        return sym, None

    if misses:
        with ThreadPoolExecutor(max_workers=min(12, len(misses))) as ex:
            for fut in as_completed([ex.submit(_fetch, s) for s in misses]):
                sym, price = fut.result()
                out[sym] = price
                _quote_cache[sym] = (price, now)

    return out


@app.get("/api/watchlist")
def watchlist(symbols: str, response: Response = None):
    """Per-stock monitoring data for the watchlist page.

    Takes a comma-separated symbol list (the user's saved watchlist) and returns
    one enriched row per symbol focused on *what changed / what's actionable*:
    latest + previous close (for day change), 52-week range position, the trailing
    up/down streak, analyst consensus/upside/revision, risk score, and recent RNS
    and press activity. Built for a small curated set, so it computes everything in
    a handful of bulk queries rather than per-stock. Prices are in pence (LSE
    convention); the frontend converts and derives day-change / range / target-gap.
    """
    requested = [s.strip() for s in symbols.split(",") if s.strip()]
    if not requested:
        return []

    # Per-user symbol set, so edge hit-rate is lower than the single-symbol
    # endpoints, but a 60s hold still collapses the repeated polls from each open
    # watchlist tab into one function call per minute per distinct set.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=60"

    # 1. Base metadata + the TTM fields the risk scorer needs + latest analyst snapshot.
    rows = query(
        """
        SELECT m.symbol, m.name, m.sector, m.ftse_index, m.financial_currency,
               t.market_cap, t.revenue, t.operating_margin, t.price_to_book, t.roe,
               CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END AS price_to_earnings,
               a.consensus, a.upside_pct, a.revision_score, a.total_analysts
        FROM company_metadata m
        LEFT JOIN ttm_financials t ON t.company_symbol = m.symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol)
                symbol, consensus, upside_pct, revision_score, total_analysts
            FROM analyst_snapshots
            ORDER BY symbol, snapshot_date DESC
        ) a ON a.symbol = m.symbol
        WHERE m.symbol = ANY(%s)
        """,
        (requested,),
    )
    by_symbol = {r["symbol"]: r for r in rows}

    # 2. Price history (last 252 closes per symbol, oldest-first) → current/prev
    #    close (day change), 52-week high/low (range position), and the streak.
    price_rows = query(
        """
        WITH numbered AS (
            SELECT symbol, close,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM price_history
            WHERE symbol = ANY(%s)
        )
        SELECT symbol, close FROM numbered WHERE rn <= 252 ORDER BY symbol, rn DESC
        """,
        (requested,),
    )
    closes_map = {}
    for r in price_rows:
        closes_map.setdefault(r["symbol"], []).append(float(r["close"]))

    for sym, r in by_symbol.items():
        closes = closes_map.get(sym, [])
        r["current_price"] = closes[-1] if closes else None
        r["prev_close"] = closes[-2] if len(closes) >= 2 else None
        r["high_52w"] = round(max(closes), 4) if closes else None
        r["low_52w"] = round(min(closes), 4) if closes else None
        r["streak"] = _trailing_streak(closes)
        # Last ~3 months (≈63 trading days) of closes for the watchlist sparkline.
        r["spark"] = [round(c, 2) for c in closes[-63:]]

    # 3. Risk score — reuse the screener's blended Altman-Z + volatility scorer.
    _attach_risk_score(list(by_symbol.values()))

    # 4. Recent RNS — count in the last 7 days + the single latest headline (for a tooltip).
    rns_latest = query(
        """
        SELECT DISTINCT ON (symbol) symbol, headline, tier, category, published_at
        FROM rns_announcements
        WHERE symbol = ANY(%s) AND published_at >= NOW() - INTERVAL '7 days'
        ORDER BY symbol, published_at DESC
        """,
        (requested,),
    )
    rns_counts = query(
        """
        SELECT symbol, COUNT(*) AS n
        FROM rns_announcements
        WHERE symbol = ANY(%s) AND published_at >= NOW() - INTERVAL '7 days'
        GROUP BY symbol
        """,
        (requested,),
    )
    count_map = {r["symbol"]: r["n"] for r in rns_counts}
    latest_map = {r["symbol"]: r for r in rns_latest}
    for sym, r in by_symbol.items():
        latest = latest_map.get(sym)
        r["rns_count"] = count_map.get(sym, 0)
        r["rns_latest"] = (
            {
                "headline": latest["headline"],
                "tier": latest["tier"],
                "category": latest["category"],
                "published_at": latest["published_at"],
            }
            if latest
            else None
        )

    # 5. Press coverage count (last 7 days). company_news is created lazily by the
    #    news endpoints, so tolerate it not existing yet.
    news_map = {}
    try:
        news_counts = query(
            """
            SELECT symbol, COUNT(*) AS n
            FROM company_news
            WHERE symbol = ANY(%s) AND published_at >= NOW() - INTERVAL '7 days'
            GROUP BY symbol
            """,
            (requested,),
        )
        news_map = {r["symbol"]: r["n"] for r in news_counts}
    except Exception:
        news_map = {}
    for sym, r in by_symbol.items():
        r["news_count"] = news_map.get(sym, 0)

    # Preserve the caller's order; silently skip symbols we have no metadata for.
    return [by_symbol[s] for s in requested if s in by_symbol]


@app.get("/api/help-doc")
def help_doc(slug: str = "user-manual"):
    """Stream a stored app document (default: the user manual) from Postgres.

    The bytes live in app_documents (see migration 003), served with the stored
    filename. PDFs are sent inline so the browser's built-in viewer renders them
    in the new tab the Tool Manual link opens; anything else downloads as an
    attachment. Stored in the DB rather than as a static file because Vercel's
    Python runtime has no persistent local filesystem to serve from.
    """
    rows = query(
        "SELECT filename, content_type, data FROM app_documents WHERE slug = %s",
        (slug,),
    )
    if not rows:
        raise HTTPException(404, "Document not found")
    row = rows[0]
    data = row["data"]
    # psycopg2 hands BYTEA back as a memoryview; FastAPI's Response wants bytes.
    if isinstance(data, memoryview):
        data = data.tobytes()
    ctype = row["content_type"] or "application/octet-stream"
    disposition = "inline" if ctype == "application/pdf" else "attachment"
    return Response(
        content=bytes(data),
        media_type=ctype,
        headers={
            "Content-Disposition": f'{disposition}; filename="{row["filename"]}"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/api/filters")
def filters(response: Response = None):
    # Sector/country lists only change on the quarterly index refresh — hold a day
    # at the edge. Called by the screener on every page load.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=86400"
    sectors = query(
        "SELECT DISTINCT sector FROM company_metadata WHERE sector IS NOT NULL ORDER BY sector"
    )
    countries = query(
        "SELECT DISTINCT country FROM company_metadata WHERE country IS NOT NULL ORDER BY country"
    )
    # Map GICS → ICB for display, then dedupe/sort (two GICS names could collapse
    # to one ICB name). The screener maps the selection back to GICS on filter.
    icb_sectors = sorted({to_icb(r["sector"]) for r in sectors})
    return {
        "sectors": icb_sectors,
        "countries": [r["country"] for r in countries],
    }


@app.get("/api/sector-constituents")
def sector_constituents(response: Response):
    """Constituents of each ICB sector basket shown in the sidebar.

    The sidebar's per-sector move is the basket average of these representative
    stocks (market.SECTOR_TICKERS). This returns the same baskets enriched with
    company names so the sidebar can show which companies sit in each sector.
    """
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    from market import SECTOR_TICKERS, _get_prices, _pct_change_today

    all_syms = [s for tickers in SECTOR_TICKERS.values() for s in tickers]
    rows = query(
        "SELECT symbol, name FROM company_metadata WHERE symbol = ANY(%s)",
        (all_syms,),
    )
    names = {r["symbol"]: r["name"] for r in rows}
    # Live: per-company moves track the current-day bar, matching the live sector
    # badge in the sidebar.
    prices = _get_prices()
    return {
        sector: [
            {
                "symbol": s,
                "name": names.get(s) or s.replace(".L", ""),
                "pct_change": _pct_change_today(prices, s),
            }
            for s in tickers
        ]
        for sector, tickers in SECTOR_TICKERS.items()
    }


_heatmap_cache: dict = {}
_HEATMAP_TTL = 900  # 15 minutes — price history refreshes once/day
_HEATMAP_LIVE_TTL = 60  # live mode: near-real-time, refreshed each minute


def _live_moves(symbols):
    """Latest daily % move per symbol via a single batched ``yf.download``.

    Uses daily bars (close-to-close), the same method and source as the sidebar,
    so the two agree exactly. During market hours yfinance's current-day bar
    tracks the live price; once closed it settles to the official close. Returns
    {symbol: pct or None}; units cancel in the ratio so pence-vs-pounds is moot.
    """
    import yfinance as yf

    out = {s: None for s in symbols}
    if not symbols:
        return out

    multi = len(symbols) > 1
    try:
        df = yf.download(
            symbols, period="5d", interval="1d", group_by="ticker",
            auto_adjust=True, threads=True, progress=False,
        )
        for s in symbols:
            try:
                # group_by="ticker" gives a (ticker, field) column index for >1
                # symbol; a single symbol comes back with flat columns.
                closes = (df[s]["Close"] if multi else df["Close"]).dropna()
            except Exception:
                continue
            if len(closes) >= 2 and float(closes.iloc[-2]):
                out[s] = float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1
    except Exception as e:
        print(f"[heatmap-live] batch daily failed: {e}")

    return out


@app.get("/api/heatmap")
def heatmap(response: Response, ftse_index: Optional[str] = None, live: bool = False):
    """Universe heatmap data: one tile per active company, sized by market cap
    and coloured by its latest daily % move.

    Returns a flat list of {symbol, name, sector, market_cap, pct_change}; the
    frontend groups by sector into a treemap.

    pct_change is close-to-close from price_history by default. With live=true it
    is recomputed from yfinance daily bars (the latest session's close-to-close
    move, tracking the live price during market hours) using the same method as
    the sidebar, cached for 60s; symbols without a quote keep their DB value.
    """
    import time

    ttl = _HEATMAP_LIVE_TTL if live else _HEATMAP_TTL
    s_maxage = 60 if live else 900
    response.headers["Cache-Control"] = (
        f"public, s-maxage={s_maxage}, stale-while-revalidate=3600"
    )

    cache_key = (ftse_index or "all", live)
    now = time.time()
    cached = _heatmap_cache.get(cache_key)
    if cached and now - cached[1] < ttl:
        return cached[0]

    wheres = ["m.sector IS NOT NULL", "t.market_cap IS NOT NULL"]
    params: list = []
    if ftse_index:
        if ftse_index == "FTSE 350":
            wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250')")
        elif ftse_index == "FTSE All-Share":
            wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250', 'FTSE SmallCap')")
        else:
            wheres.append("m.ftse_index = %s")
            params.append(ftse_index)

    sql = f"""
        WITH recent AS (
            SELECT p.symbol, p.close,
                   ROW_NUMBER() OVER (PARTITION BY p.symbol ORDER BY p.date DESC) AS rn
            FROM price_history p
            JOIN company_metadata m ON m.symbol = p.symbol AND m.is_active
        )
        SELECT m.symbol, m.name, m.sector, t.market_cap, r.close, r.rn
        FROM recent r
        JOIN company_metadata m ON m.symbol = r.symbol
        JOIN ttm_financials t ON t.company_symbol = m.symbol
        WHERE r.rn <= 2 AND {' AND '.join(wheres)}
        ORDER BY m.symbol, r.rn
    """
    rows = query(sql, params)

    # Group the (at most) two closes per symbol: rn=1 latest, rn=2 previous.
    by_symbol: dict = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], {"meta": r, "closes": {}})
        by_symbol[r["symbol"]]["closes"][r["rn"]] = r["close"]

    out = []
    for sym, d in by_symbol.items():
        meta = d["meta"]
        latest = d["closes"].get(1)
        prev = d["closes"].get(2)
        pct = None
        if latest is not None and prev not in (None, 0):
            pct = float(latest) / float(prev) - 1
        out.append(
            {
                "symbol": sym,
                "name": meta["name"] or sym.replace(".L", ""),
                "sector": meta["sector"],
                "market_cap": float(meta["market_cap"]),
                "pct_change": pct,
            }
        )

    if live:
        moves = _live_moves([r["symbol"] for r in out])
        for r in out:
            live_pct = moves.get(r["symbol"])
            if live_pct is not None:
                r["pct_change"] = live_pct

    out.sort(key=lambda r: r["market_cap"], reverse=True)
    _heatmap_cache[cache_key] = (out, now)
    return out


# ── Cron-job.org digest endpoint ──────────────────────────────────────────────

_DIGEST_TOKEN = os.environ.get("DIGEST_CRON_TOKEN", "")


@app.get("/api/digest")
def digest(token: str = Query(...)):
    """HTTP endpoint for cron-job.org to trigger the RNS email digest.

    Called by cron-job.org Mon–Fri at 07:30 UK time.
    Requires ?token=<DIGEST_CRON_TOKEN> for basic auth.
    """
    if not _DIGEST_TOKEN:
        return {"ok": False, "error": "DIGEST_CRON_TOKEN not configured"}
    if token != _DIGEST_TOKEN:
        raise HTTPException(403, "Invalid token")

    exit_code = run_digest()
    if exit_code == 0:
        return {"ok": True, "message": "Digest sent"}
    else:
        return {"ok": False, "error": f"Digest failed with exit code {exit_code}"}
