import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import psycopg2.pool
from typing import Optional
from dotenv import load_dotenv
import os
import re
import statistics
from datetime import timezone
from email.utils import format_datetime
from market import router as market_router
from prices import router as prices_router, _attach_momentum, _trailing_streak
from analysts import router as analysts_router
from rns import router as rns_router
from rns_llm import router as rns_llm_router
from news import router as news_router
from subscribers import router as subscribers_router
from feedback import router as feedback_router
from showcase import router as showcase_router
from research import router as research_router, published_slugs as _research_slugs
from dividends import router as dividends_router
from shorts import router as shorts_router
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
app.include_router(showcase_router)
app.include_router(research_router)
app.include_router(dividends_router)
app.include_router(shorts_router)

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
    ("/high-impact-rns", "daily", "0.7"),
    ("/research", "weekly", "0.7"),
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
        # Clean company URL: /company/<TICKER> with the ".L" suffix stripped, to
        # mirror the Next route (see frontend/src/lib/company.ts). Must stay in
        # sync with tickerSlug() there.
        sym = r["symbol"]
        ticker = sym[:-2] if sym.upper().endswith(".L") else sym
        loc = escape(f"{SITEMAP_BASE}/company/{quote(ticker.upper())}")
        parts.append(
            f"<url><loc>{loc}</loc><changefreq>daily</changefreq>"
            f"<priority>0.6</priority></url>"
        )
    # Published Research posts — a lastmod helps search engines re-crawl edits.
    try:
        for post in _research_slugs():
            loc = escape(f"{SITEMAP_BASE}/research/{quote(post['slug'])}")
            lastmod = ""
            if post.get("updated_at"):
                lastmod = f"<lastmod>{post['updated_at'].date().isoformat()}</lastmod>"
            parts.append(
                f"<url><loc>{loc}</loc>{lastmod}"
                f"<changefreq>monthly</changefreq><priority>0.6</priority></url>"
            )
    except Exception:
        # Sitemap must never 500 on the research table (e.g. pre-migration) — the
        # company URLs above are the important payload.
        pass
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


@app.get("/api/valuation")
def valuation(symbol: str = Query(...), response: Response = None):
    # Peer-relative fair value, precomputed daily into valuation_estimates by
    # compute_and_store_valuations(). Holds 6h at the edge like the other
    # daily-refreshed per-company endpoints. Returns an 'insufficient' shape
    # (rather than 404) when the company has no row yet, so the UI can render its
    # "not enough comparable peers" state without special-casing.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=21600, stale-while-revalidate=86400"
    rows = query(
        "SELECT * FROM valuation_estimates WHERE symbol = %s", (symbol,)
    )
    if not rows:
        return {"symbol": symbol, "peer_basis": "insufficient", "fair_value": None}
    result = rows[0]
    # peer_symbols only stores tickers; look up display names for the dropdown
    # (single cheap keyed lookup, same pattern as /api/sector-constituents).
    peer_syms = result.get("peer_symbols") or []
    if peer_syms:
        name_rows = query(
            "SELECT symbol, name FROM company_metadata WHERE symbol = ANY(%s)",
            (peer_syms,),
        )
        names = {r["symbol"]: r["name"] for r in name_rows}
        result["peers"] = [
            {"symbol": s, "name": names.get(s, s)} for s in peer_syms
        ]
    else:
        result["peers"] = []
    return result


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


def _value_score(r):
    """Value score 0-10: how cheap the stock looks across several valuation
    lenses — earnings (forward P/E), book, sales, free-cash-flow yield, dividend
    yield, and growth-adjusted (PEGY). Each available lens is mapped to 0-1
    (1 = cheapest), then averaged and scaled to 0-10, so a stock isn't penalised
    for a lens it lacks (e.g. a loss-maker with no P/E). Returns None if fewer
    than two lenses are available.

    Uses the forward P/E (analyst-rebased) so one-off statutory items can't make
    a stock look cheap when it isn't — same basis as PEGY (see _forward_pe).

    Thresholds are absolute, so the score is comparable across the whole
    universe but blunt across sectors (banks/insurers screen 'cheap' on P/E and
    P/B by design). Read it alongside quality_score and the sector, not alone.
    """
    def _f(x):
        try:
            return float(x) if x is not None else None
        except (TypeError, ValueError):
            return None

    def low_cheap(x, cheap, rich):
        # Lower is cheaper: x<=cheap -> 1.0, x>=rich -> 0.0, linear between.
        if x is None or x <= 0:
            return None
        if x <= cheap:
            return 1.0
        if x >= rich:
            return 0.0
        return (rich - x) / (rich - cheap)

    def high_cheap(x, low, high):
        # Higher is cheaper (yields): x<=low -> 0.0, x>=high -> 1.0, linear.
        if x is None:
            return None
        if x <= low:
            return 0.0
        if x >= high:
            return 1.0
        return (x - low) / (high - low)

    lenses = [
        low_cheap(_forward_pe(r, _f), 8.0, 25.0),   # earnings
        low_cheap(_f(r.get("price_to_book")), 0.75, 4.0),
        low_cheap(_f(r.get("price_to_sales")), 0.5, 6.0),
        low_cheap(_f(r.get("pegy")), 0.75, 3.0),     # growth-adjusted
        high_cheap(_f(r.get("dividend_yield")), 0.0, 0.06),
    ]

    # FCF yield = free cash flow / market cap (both in the reporting currency,
    # so the ratio is currency-safe).
    fcf, mc = _f(r.get("fcf")), _f(r.get("market_cap"))
    if fcf is not None and mc and mc > 0:
        lenses.append(high_cheap(fcf / mc, 0.0, 0.10))

    legs = [v for v in lenses if v is not None]
    if len(legs) < 2:
        return None
    return round(sum(legs) / len(legs) * 10)


import math as _math


def _lin(x, safe, risky):
    """Map x onto a 1-10 risk component, linear between safe (→1) and risky (→10).

    Direction-agnostic: works whether safe < risky (net-debt/EBITDA) or
    safe > risky (interest coverage, Altman Z). None in → None out.
    """
    if x is None:
        return None
    frac = (x - safe) / (risky - safe)
    if frac <= 0:
        return 1
    if frac >= 1:
        return 10
    return round(1 + frac * 9)


def _weighted_blend(components):
    """Blend (component, weight) pairs into a 1-10 score.

    Weights are renormalised over the non-None components, so a missing input
    redistributes its weight instead of dragging the score down. Returns None
    when every component is None.
    """
    avail = [(c, w) for c, w in components if c is not None]
    if not avail:
        return None
    total = sum(w for _, w in avail)
    return max(1, min(10, round(sum(c * w for c, w in avail) / total)))


_ASSET_HEAVY_SECTORS = {"Utilities", "Real Estate", "Energy", "Basic Materials"}
# Below this revenue/total_assets the classic Z-Score is out of its calibration
# domain: asset/goodwill-heavy names outside the sectors above (Whitbread,
# Ocado, BATS) and float-heavy fintechs (Boku carries merchant float like a
# bank but is filed under Technology) all read as "distressed manufacturers".
_ASSET_HEAVY_TURNOVER = 0.4


def _is_financial(row):
    """True for banks/insurers/financials by sector naming.

    Kept for the fair-value eligibility check (_valuation_eligible); the risk
    score itself now routes through _classify_risk_model below, which splits
    this group into bank / insurer / financial.
    """
    sector = (row.get("sector") or "").lower()
    return "financ" in sector or "bank" in sector or "insurance" in sector


def _classify_risk_model(row):
    """Route a company to the risk model that fits its business.

    Order matters: investment trusts (Yahoo gives them no sector/industry)
    first, banks/insurers by industry before the broad financial-sector
    catch-all, then asset-heavy by sector, telecom industry, or measured
    asset turnover. See docs/superpowers/specs/2026-07-03-risk-score-v2-design.md.
    """
    sector = (row.get("sector") or "").lower()
    industry = (row.get("industry") or "").lower()
    if not sector and not industry:
        return "trust"
    if "bank" in industry:
        return "bank"
    if "insur" in industry:
        return "insurer"
    if "financ" in sector or "bank" in sector or "insurance" in sector:
        return "financial"
    if row.get("sector") in _ASSET_HEAVY_SECTORS or "telecom" in industry:
        return "asset_heavy"
    revenue, ta = row.get("revenue"), row.get("total_assets")
    if revenue is not None and ta and ta > 0 and revenue / ta < _ASSET_HEAVY_TURNOVER:
        return "asset_heavy"
    return "general"


def _altman_terms(row):
    """X1-X5 ratios from real ttm_financials balance-sheet fields.

    Returns a dict holding only the genuinely computable terms (a missing
    term simply contributes nothing — conservative, since omitting a positive
    term understates safety), or None when total_assets is unusable.
    """
    ta = row.get("total_assets")
    if not ta or ta <= 0:
        return None
    terms = {}
    wc = row.get("working_capital")
    if wc is not None:
        terms["x1"] = wc / ta
    retained, equity = row.get("retained_earnings"), row.get("total_equity")
    if retained is not None:
        terms["x2"] = retained / ta
    elif equity is not None:
        terms["x2"] = equity / ta
    oi = row.get("operating_income")
    if oi is not None:
        terms["x3"] = oi / ta
    mc = row.get("market_cap")
    if mc and equity is not None and ta - equity > 0:
        terms["x4"] = mc / (ta - equity)
    revenue = row.get("revenue")
    if revenue is not None:
        terms["x5"] = revenue / ta
    return terms or None


_Z_WEIGHTS = {"x1": 1.2, "x2": 1.4, "x3": 3.3, "x4": 0.6, "x5": 1.0}
# Altman Z'' (non-manufacturers): drops asset turnover (X5) and reweights, so
# structurally asset-heavy balance sheets aren't read as distress.
_ZDD_WEIGHTS = {"x1": 6.56, "x2": 3.26, "x3": 6.72, "x4": 1.05}


def _z_score(terms, weights):
    """Weighted Altman score over whichever terms are available."""
    if not terms:
        return None
    used = [k for k in weights if k in terms]
    if not used:
        return None
    return round(sum(weights[k] * terms[k] for k in used), 3)


def _z_to_risk(z):
    """Classic Altman Z → 1-10 risk. Z >= 3.0 safe, <= 1.0 distress."""
    return _lin(z, 3.0, 1.0)


def _zdd_to_risk(z):
    """Altman Z'' → 1-10 risk. Z'' >= 2.6 safe, <= 1.1 distress."""
    return _lin(z, 2.6, 1.1)


# Winsorise daily log returns: suspension/relisting gaps otherwise print 800%+
# "volatility" (FXPO, SAVE) and pin the component at 10 regardless of the real
# trading range.
_VOL_RETURN_CAP = 0.25


def _annualised_vol(closes):
    """Compute annualised volatility from a list of closes (oldest first).

    Annualised std of winsorised daily log returns, or None if fewer than
    2 prices.
    """
    if len(closes) < 2:
        return None
    log_returns = [
        max(-_VOL_RETURN_CAP, min(_VOL_RETURN_CAP, _math.log(closes[i] / closes[i - 1])))
        for i in range(1, len(closes))
    ]
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


def _roe_blend(row):
    """Average of TTM ROE and its multi-year median — a through-cycle quality
    read, so one flattering or ugly IFRS year can't dominate."""
    vals = [v for v in (row.get("roe"), row.get("roe_median")) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _debt_service_component(row):
    """1-10 debt-service risk from interest coverage + net-debt/EBITDA.

    The right lens for structurally leveraged balance sheets — distinguishes
    Severn Trent (large but serviceable debt) from Tullow (not). Averages
    whichever legs are available: net cash → 1; EBITDA <= 0 drops the
    ND/EBITDA leg (negative interest coverage already carries that signal).

    Coverage band: regulated utilities structurally run 2-3x cover, so "safe"
    starts at 6x rather than the sub-1x that actually signals distress.
    """
    legs = []
    ic = row.get("interest_coverage")
    if ic is not None:
        legs.append(_lin(ic, 6.0, 0.5))
    nd, ebitda = row.get("net_debt"), row.get("ebitda")
    # updater.py derives net_debt = st_debt + lt_debt - cash even when both
    # debt fields are NULL, so a missing balance sheet prints as "net cash"
    # (PHP: -cash with real 48% LTV). Only trust nd <= 0 when debt was reported.
    debt_reported = row.get("st_debt") is not None or row.get("lt_debt") is not None
    if nd is not None:
        if nd <= 0:
            if debt_reported:
                legs.append(1)
        elif ebitda is not None and ebitda > 0:
            legs.append(_lin(nd / ebitda, 1.0, 8.0))
    if not legs:
        return None
    return round(sum(legs) / len(legs))


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
    """Add risk_score (1-10), risk_model, altman_z, volatility_annualised and
    risk_components to each result row.

    Sector-aware (docs/superpowers/specs/2026-07-03-risk-score-v2-design.md):
    each company routes to one model — general (classic Z + vol), asset_heavy
    (Z'' + debt service + vol), bank, insurer, financial, trust. Two bulk
    queries: ttm_financials + company_metadata supply every fundamental input
    (callers only need a 'symbol' key on each row), price_history supplies
    volatility. altman_z holds the classic Z for general rows and Z'' for
    asset_heavy rows — risk_model tells the UI which scale applies.
    """
    if not results:
        return results

    symbols = [r["symbol"] for r in results]

    # 1. Fundamental inputs + sector/industry for model routing
    fin_rows = query(
        """
        SELECT t.company_symbol, m.sector, m.industry,
               t.market_cap, t.price_to_book, t.revenue, t.operating_income,
               t.working_capital, t.retained_earnings, t.total_equity,
               t.total_assets, t.interest_coverage, t.net_debt, t.ebitda,
               t.st_debt, t.lt_debt, t.roe, t.roe_median
        FROM ttm_financials t
        LEFT JOIN company_metadata m ON m.symbol = t.company_symbol
        WHERE t.company_symbol = ANY(%s)
    """,
        (symbols,),
    )
    fin_map = {r["company_symbol"]: r for r in fin_rows}

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

    # 3. Route each symbol to its model, compute and attach
    for r in results:
        sym = r["symbol"]
        f = fin_map.get(sym) or {}

        closes = closes_map.get(sym, [])
        vol = _annualised_vol(closes) if len(closes) >= 63 else None
        vol_c = _vol_to_score(vol)

        # No ttm row at all → no sector/industry to route on; "general" keeps
        # the row from being mistaken for a trust (whose signature is a real
        # row with no classification).
        model = _classify_risk_model(f) if f else "general"
        z_display = None
        components = {"volatility": vol_c}

        if model == "trust":
            # Closed-end funds: any Altman flavour reads their balance sheet
            # as a failing manufacturer's. Volatility is the only stored signal.
            score = _weighted_blend([(vol_c, 1.0)])
        elif model == "bank":
            eq, ta = f.get("total_equity"), f.get("total_assets")
            leverage = eq / ta if (eq is not None and ta and ta > 0) else None
            components["roe"] = _roe_to_risk(_roe_blend(f))
            # equity/assets is a CET1 proxy: UK banks span ~5-14%, the ~3.25%
            # regulatory leverage floor anchors the risky end.
            components["leverage"] = _lin(leverage, 0.10, 0.03)
            # A bank below ~0.6x book is the market pricing balance-sheet doubt.
            components["price_to_book"] = _lin(f.get("price_to_book"), 1.0, 0.35)
            score = _weighted_blend([
                (components["roe"], 0.30),
                (components["leverage"], 0.25),
                (components["price_to_book"], 0.20),
                (vol_c, 0.25),
            ])
        elif model == "insurer":
            # ROE demoted vs banks (IFRS-17 noise); equity/assets is
            # meaningless against policy liabilities so it's not used.
            components["roe"] = _roe_to_risk(_roe_blend(f))
            components["price_to_book"] = _lin(f.get("price_to_book"), 1.0, 0.35)
            score = _weighted_blend([
                (components["roe"], 0.35),
                (components["price_to_book"], 0.25),
                (vol_c, 0.40),
            ])
        elif model == "financial":
            # Asset managers etc. — asset-light, the v1 formula is honest here.
            components["roe"] = _roe_to_risk(_roe_blend(f))
            score = _weighted_blend([(vol_c, 0.6), (components["roe"], 0.4)])
        elif model == "asset_heavy":
            z_display = _z_score(_altman_terms(f), _ZDD_WEIGHTS)
            components["altman"] = _zdd_to_risk(z_display)
            components["debt_service"] = _debt_service_component(f)
            score = _weighted_blend([
                (components["altman"], 0.4),
                (components["debt_service"], 0.3),
                (vol_c, 0.3),
            ])
        else:  # general
            z_display = _z_score(_altman_terms(f), _Z_WEIGHTS)
            components["altman"] = _z_to_risk(z_display)
            score = _weighted_blend([(components["altman"], 0.6), (vol_c, 0.4)])

        r["risk_score"] = score
        r["risk_model"] = model
        # Clamp for display sanity — tiny asset bases print absurd Z values
        # (EEE.L: Z=1402). The 1-10 mapping saturates long before the clamp.
        r["altman_z"] = (
            max(-10.0, min(30.0, z_display)) if z_display is not None else None
        )
        r["volatility_annualised"] = round(vol * 100, 1) if vol is not None else None
        r["risk_components"] = components

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
    # The scorers bulk-fetch their own inputs keyed by symbol, so the universe
    # is just the symbol list (risk additionally re-joins ttm + metadata itself).
    universe = query(
        """
        SELECT m.symbol
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
            r.get("risk_model"),
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
            " (symbol, momentum_score, piotroski_score, risk_score, risk_model,"
            "  altman_z, volatility_annualised, computed_at)"
            " VALUES %s"
            " ON CONFLICT (symbol) DO UPDATE SET"
            "   momentum_score        = EXCLUDED.momentum_score,"
            "   piotroski_score       = EXCLUDED.piotroski_score,"
            "   risk_score            = EXCLUDED.risk_score,"
            "   risk_model            = EXCLUDED.risk_model,"
            "   altman_z              = EXCLUDED.altman_z,"
            "   volatility_annualised = EXCLUDED.volatility_annualised,"
            "   computed_at           = now()",
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, now())",
            page_size=1000,
        )
        conn.commit()
        return {"symbols": len(universe), "stored": len(rows)}
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Peer-relative fair value ────────────────────────────────────────────────
#
# Deliberately narrow and EV/EBITDA-only. A dry run showed a plain peer-median is
# only defensible for profitable, non-financial, moderately-geared companies:
#   - financials/REITs trade on book/NAV, not EBITDA — and a high-ROE insurer next
#     to a low-ROE bank reads as wildly overvalued under a shared P/B median;
#   - P/S across firms with different margins is meaningless (distributor vs
#     software in the same sector);
#   - the EV→equity bridge amplifies a small multiple gap into a huge equity swing
#     once leverage is high (FirstGroup, EnQuest read +600–800%).
# So everything outside that safe subset gets no estimate (the UI shows "no
# comparable basis") rather than a misleading number.
#
# Peers are TRUE peers only: same yfinance `industry` (with over-split industries
# merged into analytical groups, see _INDUSTRY_GROUPS / _peer_group), no sector
# fallback. A sector-wide median (e.g. all 80 Industrials) isn't a peer group — it
# lumped a lighting maker in with the whole sector — so a thin group (<MIN_PEERS)
# gets no estimate rather than a diluted one.

MIN_PEERS = 3  # genuine industry peers required (a 3-name median still resists one outlier)
MAX_NET_DEBT_TO_MKT_CAP = 1.0  # leverage cap → equity-bridge amplification <= ~2x
SANITY_MAX_ABS_UPSIDE = 150.0  # final backstop (percent) against data glitches
MAX_PEER_MULTIPLE = 40.0  # ceiling: beyond this it's a depressed-EBITDA artifact, not pricing
PEER_TRIM_RATIO = 3.0  # relative fences: drop peers >3x or <1/3x the group median
# Sectors with no meaningful EV/EBITDA (book/NAV-valued). Raw GICS names as stored
# in company_metadata.sector (see backend/sectors.py); _is_financial also catches
# bank/insurance naming as a belt-and-braces.
_EXCLUDED_SECTORS = {"Financial Services", "Real Estate"}

# Financial firms and investment trusts that yfinance tags with an *operating*
# sector, so the sector/naming checks miss them. All are Financials in the LSE's
# official ICB classification (issuer list, cross-checked 2026-07).
_EXCLUDED_SYMBOLS = {
    "XPS.L",   # XPS Pensions — pensions consulting/admin, tagged Consumer Cyclical "Personal Services"
    "IBT.L",   # International Biotechnology Trust — a fund, tagged Healthcare "Biotechnology"
    "UKW.L",   # Greencoat UK Wind — renewables fund, tagged Utilities
    "TRIG.L",  # Renewables Infrastructure Group — renewables fund, tagged Utilities
}


def _valuation_excluded(r):
    """True when a company has no meaningful EV/EBITDA basis: financials/REITs
    by sector or naming, plus the symbol-level exceptions above. Applied both to
    the subject company (no estimate) and to peer candidates (a trust's multiple
    must not sit in an operating peer group's median)."""
    sector = r.get("sector") or ""
    return (sector in _EXCLUDED_SECTORS or _is_financial(r)
            or r.get("symbol") in _EXCLUDED_SYMBOLS)

# yfinance over-splits some industries, stranding true peers below MIN_PEERS
# (e.g. AZN + GSK alone in "Drug Manufacturers - General"; SHEL + BP alone in
# "Oil & Gas Integrated"). Merge the over-split ones into a single analytical peer
# group. Keys are raw yfinance industries; anything unlisted passes through as-is.
_INDUSTRY_GROUPS = {
    "Drug Manufacturers - General": "Pharmaceuticals",
    "Drug Manufacturers - Specialty & Generic": "Pharmaceuticals",
    "Oil & Gas Integrated": "Oil & Gas",
    "Oil & Gas E&P": "Oil & Gas",
    "Oil & Gas Equipment & Services": "Oil & Gas",
    "Oil & Gas Refining & Marketing": "Oil & Gas",
    "Gold": "Metals & Mining",
    "Other Industrial Metals & Mining": "Metals & Mining",
    "Copper": "Metals & Mining",
    "Other Precious Metals & Mining": "Metals & Mining",
    "Steel": "Metals & Mining",
    "Leisure": "Travel & Leisure",
    "Travel Services": "Travel & Leisure",
    "Lodging": "Travel & Leisure",
    "Resorts & Casinos": "Travel & Leisure",
    "Gambling": "Travel & Leisure",
    "Marine Shipping": "Transportation",
    "Airlines": "Transportation",
    "Railroads": "Transportation",
    "Medical Devices": "Medical Devices & Supplies",
    "Medical Instruments & Supplies": "Medical Devices & Supplies",
    "Medical Distribution": "Medical Devices & Supplies",
    "Computer Hardware": "Tech Hardware",
    "Electronic Components": "Tech Hardware",
    "Communication Equipment": "Tech Hardware",
    "Electronics & Computer Distribution": "Tech Hardware",
    "Auto & Truck Dealerships": "Automotive",
    "Auto Parts": "Automotive",
    "Auto Manufacturers": "Automotive",
    "Grocery Stores": "Food Retail & Distribution",
    "Discount Stores": "Food Retail & Distribution",
    "Food Distribution": "Food Retail & Distribution",
    "Beverages - Non-Alcoholic": "Beverages",
    "Beverages - Brewers": "Beverages",
    "Beverages - Wineries & Distilleries": "Beverages",
}

# Per-symbol overrides for companies yfinance mis-tags into the wrong industry, so
# they're valued against their real peers rather than an unrelated group.
_SYMBOL_GROUPS = {
    "GAW.L": "Specialty Retail",                  # hobby manufacturer/retailer, tagged "Leisure"
    "VSVS.L": "Specialty Industrial Machinery",   # steel-industry supplier, tagged "Steel" (not a miner)
    "BNZL.L": "Industrial Distribution",          # B2B distributor, tagged "Food Distribution"
    "DCC.L": "Industrial Distribution",           # distribution/support-services group, tagged Oil & Gas
    "HLN.L": "Household & Personal Products",     # consumer health (Sensodyne/Panadol) — staples comps, tagged "Drug Manufacturers - Specialty & Generic"
    "HLMA.L": "Scientific & Technical Instruments",  # safety/health sensor maker, tagged "Conglomerates"; ICB: Electronic Equipment & Parts
    "BAB.L": "Aerospace & Defense",               # defence services, tagged "Engineering & Construction"; ICB: Aerospace & Defence
    "MRO.L": "Aerospace & Defense",               # pure aero since the GKN breakup, tagged "Specialty Industrial Machinery"; ICB: Aerospace & Defence
}


def _peer_group(symbol, industry):
    """Canonical peer group for a company: a per-symbol override if any, else the
    merged industry group, else the raw industry. None when industry is unknown."""
    if symbol in _SYMBOL_GROUPS:
        return _SYMBOL_GROUPS[symbol]
    if not industry:
        return None
    return _INDUSTRY_GROUPS.get(industry, industry)


def _own_ev_ebitda(r, _f):
    """EV/EBITDA computed from the same stored fields the equity bridge uses:
    (market_cap + net_debt) / EBITDA, all one reporting currency.

    Deliberately NOT yfinance's enterpriseToEbitda — that field routinely
    disagrees with these inputs (different EBITDA normalization/date; RR.L reads
    22.5x there but ~13x here), and mixing the two flipped verdicts: a company
    whose own multiple sat above the peer median could still read "undervalued"
    because the bridge silently used the cheaper implied multiple. One
    definition for the subject, the peers and the bridge keeps the estimate
    monotonic: own above median always reads overvalued. Returns None when the
    inputs are missing or EV is non-positive (net cash exceeding market cap).
    """
    ebitda = _f(r.get("ebitda"))
    mkt = _f(r.get("market_cap"))
    net_debt = _f(r.get("net_debt"))
    if ebitda is None or ebitda <= 0 or mkt is None or mkt <= 0 or net_debt is None:
        return None
    ev = mkt + net_debt
    if ev <= 0:
        return None
    return ev / ebitda


def _valuation_eligible(r, _f):
    """Return the company's own EV/EBITDA when it's a defensible fair-value fit,
    else None.

    Restricted to profitable, non-financial, moderately-geared companies — the
    only group where a single peer-median EV/EBITDA is trustworthy (see the block
    comment above). Financials/REITs, loss-makers and highly-levered names return
    None and get no estimate.
    """
    if _valuation_excluded(r):
        return None
    ni = _f(r.get("net_income"))
    ebitda = _f(r.get("ebitda"))
    if ni is None or ni <= 0 or ebitda is None or ebitda <= 0:
        return None
    mkt = _f(r.get("market_cap"))
    if mkt is None or mkt <= 0:
        return None
    net_debt = _f(r.get("net_debt"))
    if net_debt is not None and net_debt > MAX_NET_DEBT_TO_MKT_CAP * mkt:
        return None
    return _own_ev_ebitda(r, _f)


def _peer_median(vals):
    """Median peer multiple. Median (not mean) so a single extreme peer — common
    in thin UK industries — can't swing the fair value."""
    return statistics.median(vals)


def _trim_peer_multiples(syms, vals):
    """Drop junk multiples from a peer set before the median is taken,
    returning the surviving (symbols, values) parallel lists.

    The median resists ONE outlier but not a cluster: Tech Hardware's median
    sat at ~34x because four members had collapsed EBITDA (40-50x artifacts).
    Two passes:
      1. Absolute ceiling (MAX_PEER_MULTIPLE) — a multiple that high isn't
         market pricing, it's a distressed denominator. This is the only pass
         that works when the junk is the majority, so it runs first.
      2. Median-relative fences (PEER_TRIM_RATIO) on the survivors — catches
         mid-range misfits an absolute cap can't (a 33x test-systems maker
         among 6x car dealerships, a 0.7x cash-pile airline among 9x leisure
         names) while staying scale-free across cheap (oil ~3x) and expensive
         (instruments ~25x) groups. The median element always survives its own
         fences, so this pass never empties the set.
    """
    kept = [(s, v) for s, v in zip(syms, vals) if v <= MAX_PEER_MULTIPLE]
    if not kept:
        return [], []
    med = statistics.median(v for _, v in kept)
    kept = [(s, v) for s, v in kept
            if med / PEER_TRIM_RATIO <= v <= med * PEER_TRIM_RATIO]
    return [s for s, _ in kept], [v for _, v in kept]


def _fair_value_upside(peer_median, r, _f):
    """Currency-safe fractional upside (fair_value / current_price - 1) via the
    EV/EBITDA equity bridge.

    fair_equity = peer_median * EBITDA - net_debt, compared to market_cap. EBITDA,
    net_debt and market_cap share one reporting currency, so the ratio is
    dimensionless — no FX needed (mirrors the ratio trick in _forward_pe). Returns
    None when inputs are unusable.
    """
    ebitda = _f(r.get("ebitda"))
    net_debt = _f(r.get("net_debt"))
    market_cap = _f(r.get("market_cap"))
    if ebitda is None or net_debt is None or not market_cap or market_cap <= 0:
        return None
    fair_equity = peer_median * ebitda - net_debt
    return fair_equity / market_cap - 1


def compute_and_store_valuations():
    """Recompute peer-relative fair value for the whole universe into
    valuation_estimates.

    Fair value = peer-median EV/EBITDA applied via the equity bridge, for the
    narrow subset where that is defensible (see _valuation_eligible). Peers are
    true peers only — the same yfinance industry, no sector fallback — with junk
    multiples trimmed before the median (see _trim_peer_multiples), and only
    when at least MIN_PEERS surviving peers exist; otherwise no fair value is
    stored rather than a sector-wide median masquerading as a peer group. A
    final SANITY_MAX_ABS_UPSIDE backstop suppresses glitch extremes. The stored
    peer_symbols are the peers actually used (post-trim).

    peer_basis distinguishes *why* there's no estimate, so the UI isn't stuck
    saying "not enough peers" for a bank that was never eligible in the first
    place: 'industry' (estimate produced), 'excluded_sector' (financials/REITs —
    book/NAV-valued, no peer search even attempted), 'insufficient' (eligible
    company, but its industry has fewer than MIN_PEERS other members), or
    'out_of_range' (enough peers, but the implied value tripped the sanity
    guards — e.g. Hikma at 5.4x vs a ~12x peer median implies +200%, past
    SANITY_MAX_ABS_UPSIDE — so the number was suppressed as indefensible).

    Currency-safe without FX: the upside is a ratio of same-currency quantities
    (EBITDA/net_debt/market_cap share one reporting currency per company), mapped
    onto the GBp quote price only for the displayed fair value. The symbols behind
    peer_count are also stored (peer_symbols), so the UI can name the peer group
    rather than just show a count. Run daily after the price refresh. Returns a
    summary.
    """
    universe = query(
        """
        SELECT m.symbol, m.sector, m.industry,
               t.ebitda, t.net_debt, t.market_cap, t.net_income,
               COALESCE(p.latest_close, t.period_end_price) AS current_price
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol) symbol, close AS latest_close
            FROM price_history
            ORDER BY symbol, date DESC
        ) p ON p.symbol = m.symbol
        WHERE m.is_active
        """
    )
    if not universe:
        return {"symbols": 0, "stored": 0}

    def _f(x):
        return float(x) if x is not None else None

    def _peer_values(self_sym, group):
        """(symbols, values) of active members of the same peer group with a
        valid computed EV/EBITDA (see _own_ev_ebitda — same definition as the
        subject and the bridge), parallel lists in matching order. Excluded
        companies (financials/trusts) can't serve as peers either — today's
        yfinance industry tags happen not to collide, but that's luck, not a
        guarantee (e.g. a fintech tagged "Software - Application")."""
        if not group:
            return [], []
        syms, vals = [], []
        for o in universe:
            if o["symbol"] == self_sym:
                continue
            if _valuation_excluded(o):
                continue
            if _peer_group(o["symbol"], o.get("industry")) != group:
                continue
            v = _own_ev_ebitda(o, _f)
            if v is not None:
                syms.append(o["symbol"])
                vals.append(v)
        return syms, vals

    rows_out = []
    for r in universe:
        sym = r["symbol"]
        cur_price = _f(r.get("current_price"))
        cur_price_r = round(cur_price, 2) if cur_price is not None else None

        own_mult = _valuation_eligible(r, _f)
        if own_mult is None:
            basis = "excluded_sector" if _valuation_excluded(r) else "insufficient"
            rows_out.append((sym, None, cur_price_r, None, None,
                             basis, 0, None, None, False, []))
            continue

        peer_syms, peer_vals = _trim_peer_multiples(
            *_peer_values(sym, _peer_group(sym, r.get("industry"))))
        basis = "industry"
        if len(peer_vals) < MIN_PEERS:
            rows_out.append((sym, None, cur_price_r, None, "EV/EBITDA",
                             "insufficient", len(peer_vals), None,
                             round(own_mult, 3), False, peer_syms))
            continue

        peer_median = _peer_median(peer_vals)
        upside = _fair_value_upside(peer_median, r, _f)

        fair_value = None
        upside_pct = None
        if upside is not None and cur_price is not None and cur_price > 0:
            fv = cur_price * (1 + upside)
            # Guard: no meaningful equity value, or a glitch-sized swing.
            if fv > 0 and abs(upside * 100) <= SANITY_MAX_ABS_UPSIDE:
                fair_value = round(fv, 2)
                upside_pct = round(upside * 100, 1)
        if fair_value is None:
            # Peers existed but the guards rejected the number — flag it so the
            # UI doesn't misreport this as "not enough peers".
            basis = "out_of_range"
        rows_out.append((sym, fair_value, cur_price_r, upside_pct, "EV/EBITDA",
                         basis, len(peer_vals), round(peer_median, 3),
                         round(own_mult, 3), False, peer_syms))

    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO valuation_estimates"
            " (symbol, fair_value, current_price, upside_pct, multiple_used,"
            "  peer_basis, peer_count, peer_median_multiple, own_multiple, caution,"
            "  peer_symbols, computed_at)"
            " VALUES %s"
            " ON CONFLICT (symbol) DO UPDATE SET"
            "   fair_value           = EXCLUDED.fair_value,"
            "   current_price        = EXCLUDED.current_price,"
            "   upside_pct           = EXCLUDED.upside_pct,"
            "   multiple_used        = EXCLUDED.multiple_used,"
            "   peer_basis           = EXCLUDED.peer_basis,"
            "   peer_count           = EXCLUDED.peer_count,"
            "   peer_median_multiple = EXCLUDED.peer_median_multiple,"
            "   own_multiple         = EXCLUDED.own_multiple,"
            "   caution              = EXCLUDED.caution,"
            "   peer_symbols         = EXCLUDED.peer_symbols,"
            "   computed_at          = now()",
            rows_out,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
            page_size=1000,
        )
        conn.commit()
        stored = sum(1 for x in rows_out if x[1] is not None)
        return {"symbols": len(universe), "stored": stored, "rows": len(rows_out)}
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Screener metric scrubbing ─────────────────────────────────────────────────
# Closed-end funds that Yahoo files under Financial Services / Asset Management
# come through _classify_risk_model as "financial"; catch them by name so their
# investment-gain "revenue" doesn't screen as operating performance. Only ever
# tested against financial-model rows, so fund-flavoured words that exist in
# other sectors ("infrastructure") are safe here. Audited against the live
# Asset Management/Capital Markets cohort (2026-07-04): "Ord"/"Income"/
# "Infrastructure"/"Investments" appear exclusively in fund names there;
# word-boundaried so Liontrust ("trust") and City of London Investment Group
# (singular "Investment") don't match. Known escapees (Pershing Square, BH
# Macro, Syncona, …) are left to the degenerate-value caps below.
_TRUST_NAME_RE = re.compile(
    r"\btrust\b|\bfund\b|\bvct\b|\bord\b|\bincome\b|\binvestments\b"
    r"|\binfrastructure\b|investment company|inv\.? company|private equity",
    re.I,
)

# Everything income-statement-derived is meaningless for a closed-end fund:
# "revenue" is investment gains/losses (BRWM printed +1,158% revenue growth,
# FEV a P/S of 1.6e-08), so margins, P/S and every growth rate are noise, and
# Piotroski leans on the same fields. P/B, dividend yield, ROE/ROA and
# volatility stay — those are the honest lenses for a trust.
_TRUST_NA_FIELDS = (
    "price_to_sales", "gross_margin", "operating_margin", "net_income_margin",
    "fcf_margin", "revenue_growth", "eps_diluted_growth", "fcf_growth",
    "revenue_cagr_10", "eps_cagr_10", "roic", "roce", "current_ratio",
    "debt_to_equity", "piotroski_score", "fcf",
)
# Banks/insurers: FCF is meaningless (deposit/claims flows swamp it — the
# NatWest +734% case), current assets/liabilities aren't reported so the
# current ratio is absent or junk (TBCG: 2,462), D/E's numerator misses the
# funding book entirely, and ROIC/ROCE have no sensible denominator. Piotroski
# loses its liquidity/margin legs and reads structurally weak (Financials
# median 3 vs 5 elsewhere) — blanked too. Operating/net margin and P/S are
# kept: for a bank they behave like efficiency ratios and are comparable.
_BANK_INSURER_NA_FIELDS = (
    "fcf_margin", "fcf_growth", "fcf", "gross_margin", "current_ratio",
    "roic", "roce", "debt_to_equity", "piotroski_score",
)
# Other financials (asset managers, capital markets, credit services): fee
# revenue is real, so margins and growth stand; only the FCF lens is junk
# (client/fund cash movements dominate the cash-flow statement).
_FINANCIAL_NA_FIELDS = ("fcf_margin", "fcf_growth", "fcf")

_NA_FIELDS_BY_MODEL = {
    "trust": _TRUST_NA_FIELDS,
    "bank": _BANK_INSURER_NA_FIELDS,
    "insurer": _BANK_INSURER_NA_FIELDS,
    "financial": _FINANCIAL_NA_FIELDS,
}

# Revenue below this (in the filing currency's base units) makes any revenue
# ratio a shell-company artifact (AVCT: £113k revenue → -34,170% net margin).
_MIN_RATIO_REVENUE = 1_000_000
_REVENUE_RATIO_FIELDS = (
    "price_to_sales", "gross_margin", "operating_margin",
    "net_income_margin", "fcf_margin", "revenue_growth",
)
_GROWTH_CAP = 5.0  # |YoY growth| beyond ±500% is a base-effect artifact
_CAGR_CAP = 1.0  # |10y CAGR| beyond ±100%/yr means a broken endpoint (MSI: +494%)
_MAX_PS = 300.0  # no real business trades at P/S > 300 (cf. the P/E > 999 cap)
_MAX_CURRENT_RATIO = 50.0  # beyond this it's client money / float, not liquidity


def _scrub_screener_metrics(results):
    """Null out metrics that are junk for a row before they can render, sort,
    filter, or feed the quality/value scores.

    Two passes per row: degenerate-value guards that apply to every company
    (negative/zero denominators, shell-sized revenue, base-effect growth,
    phantom debt-free D/E), then business-model blanking keyed on the stored
    risk_model — falling back to _classify_risk_model when screener_scores
    hasn't covered the row yet — plus the trust-name test above. Runs on the
    raw rows straight from SQL, before _attach_pegy/_quality_score/_value_score
    and before the GICS→ICB sector rename.
    """
    for r in results:
        rev = r.get("revenue")
        if rev is not None and rev < _MIN_RATIO_REVENUE:
            for k in _REVENUE_RATIO_FIELDS:
                r[k] = None
        pb = r.get("price_to_book")
        if pb is not None and pb <= 0:
            r["price_to_book"] = None  # negative equity: P/B is undefined
        ps = r.get("price_to_sales")
        if ps is not None and (ps <= 0 or ps > _MAX_PS):
            r["price_to_sales"] = None
        cr = r.get("current_ratio")
        if cr is not None and cr > _MAX_CURRENT_RATIO:
            r["current_ratio"] = None  # QLT printed 115.9 (client money)
        for k in ("revenue_growth", "eps_diluted_growth", "fcf_growth"):
            v = r.get(k)
            if v is not None and abs(v) > _GROWTH_CAP:
                r[k] = None
        for k in ("revenue_cagr_10", "eps_cagr_10"):
            v = r.get(k)
            if v is not None and abs(v) > _CAGR_CAP:
                r[k] = None
        # Historic rows derived D/E as (st+lt)/equity with absent debt fields
        # coerced to 0, so unreported debt printed as a green "debt-free" 0.0
        # (LLOY, NWG). Same phantom-net-cash trap as _debt_service_component:
        # only trust a 0 when some debt field was actually reported. updater.py
        # now writes NULL for new rows, but the upsert's COALESCE keeps old
        # values, so the stored 0.0s never self-heal — scrub at the boundary.
        if (
            r.get("debt_to_equity") == 0
            and r.get("st_debt") is None
            and r.get("lt_debt") is None
        ):
            r["debt_to_equity"] = None

        model = r.get("risk_model") or _classify_risk_model(r)
        if model == "financial" and _TRUST_NAME_RE.search(r.get("name") or ""):
            model = "trust"
        fields = _NA_FIELDS_BY_MODEL.get(model)
        if fields:
            for k in fields:
                r[k] = None

        # Fetched only for the phantom-D/E check — not part of the response.
        r.pop("st_debt", None)
        r.pop("lt_debt", None)


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
        SELECT m.symbol, m.name, m.sector, m.industry, m.country, m.exchange, m.ftse_index,
               m.financial_currency, m.currency,
               t.market_cap, t.revenue, t.net_income, t.st_debt, t.lt_debt,
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
               s.momentum_score, s.piotroski_score, s.risk_score, s.risk_model,
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
    # Scrub before anything reads the rows: junk metrics (trust "revenue",
    # bank FCF, phantom D/E zeros, shell-company ratios) must not render, sort,
    # filter, or leak into the quality/value scores computed below.
    _scrub_screener_metrics(results)
    # momentum / piotroski / risk / altman_z / volatility now come precomputed via
    # the screener_scores JOIN (see compute_and_store_scores). quality_score,
    # value_score and pegy stay inline — they read only columns already in this
    # query, no extra DB hit. PEGY is attached first because value_score uses it.
    _attach_pegy(results)
    for r in results:
        r["quality_score"] = _quality_score(r)
        r["value_score"] = _value_score(r)
    # Surface ICB labels so the table matches the sidebar/heatmap. Done last so
    # scoring above still sees the raw GICS sector it was built against.
    for r in results:
        r["sector"] = to_icb(r["sector"])
    _screener_cache[cache_key] = (results, now)
    return results


_quote_cache: dict = {}
_QUOTE_TTL = 60  # seconds
# Symbol-list endpoints take arbitrary user input, so bound both dimensions:
# how many symbols one request may carry (each /api/quotes miss is a yfinance
# fetch on a thread pool) and what a symbol may look like. The shape check
# covers LSE tickers plus the ^index / FX=X forms yfinance uses; anything else
# is silently dropped rather than fetched-and-cached.
_MAX_LIST_SYMBOLS = 100
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^=-]{1,15}$")
# The quote cache holds only 2-tuples, but garbage symbols would still grow it
# without bound on a long-lived process — prune expired entries past this size.
_QUOTE_CACHE_MAX = 2000


def _parse_symbol_list(symbols: str) -> list[str]:
    """Comma-separated symbols → deduped, shape-validated list (order kept).
    Raises 400 when the request asks for more than _MAX_LIST_SYMBOLS."""
    requested = list(dict.fromkeys(s.strip() for s in symbols.split(",") if s.strip()))
    if len(requested) > _MAX_LIST_SYMBOLS:
        raise HTTPException(400, f"Too many symbols (max {_MAX_LIST_SYMBOLS} per request)")
    return [s for s in requested if _SYMBOL_RE.match(s)]


@app.get("/api/quotes")
def quotes(symbols: str, response: Response):
    """Return live last-price for each symbol via yfinance fast_info. 60s cache per symbol."""
    import time
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    requested = _parse_symbol_list(symbols)
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

    # Bound the cache: real tickers are a finite set, but unknown-symbol probes
    # would otherwise accumulate one dead entry each, forever.
    if len(_quote_cache) > _QUOTE_CACHE_MAX:
        for k in [k for k, v in _quote_cache.items() if now - v[1] >= _QUOTE_TTL]:
            del _quote_cache[k]

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
    requested = _parse_symbol_list(symbols)
    if not requested:
        return []

    # Per-user symbol set, so edge hit-rate is lower than the single-symbol
    # endpoints, but a 60s hold still collapses the repeated polls from each open
    # watchlist tab into one function call per minute per distinct set.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=60"

    return _watchlist_rows(requested)


def _watchlist_rows(requested: list[str]) -> list[dict]:
    """Build the enriched per-stock rows for a symbol list — the body of the
    watchlist endpoint, factored out so other endpoints (e.g. the High Impact RNS
    showcase in showcase.py) can reuse the exact same enrichment. No HTTP concerns
    here; the caller sets any cache headers. Returns rows in the caller's order.
    """
    if not requested:
        return []

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
def help_doc(request: Request, slug: str = "user-manual"):
    """Stream a stored app document (default: the user manual) from Postgres.

    The bytes live in app_documents (see migration 003), served with the stored
    filename. PDFs are sent inline so the browser's built-in viewer renders them
    in the new tab the Tool Manual link opens; anything else downloads as an
    attachment. Stored in the DB rather than as a static file because Vercel's
    Python runtime has no persistent local filesystem to serve from.

    Caching: the URL is stable across manual updates, so a plain long max-age let
    clients (notably mobile Safari / a home-screen PWA) keep serving an old cover
    forever with no way to notice a newer upload. Instead we tag each response
    with an ETag/Last-Modified derived from updated_at and tell clients to always
    revalidate (max-age=0, must-revalidate). Unchanged docs still get a cheap 304
    (no 2 MB re-download); a re-uploaded manual changes the ETag and is fetched
    fresh immediately.
    """
    rows = query(
        "SELECT filename, content_type, data, updated_at FROM app_documents WHERE slug = %s",
        (slug,),
    )
    if not rows:
        raise HTTPException(404, "Document not found")
    row = rows[0]

    # Validator keyed on the upsert timestamp — it advances on every re-upload
    # (upload_help_doc.py sets updated_at = NOW()), so a new manual = a new ETag.
    updated_at = row["updated_at"].astimezone(timezone.utc)
    etag = f'"{slug}-{int(updated_at.timestamp())}"'
    cache_headers = {
        "Cache-Control": "public, max-age=0, must-revalidate",
        "ETag": etag,
        "Last-Modified": format_datetime(updated_at, usegmt=True),
    }

    # Conditional request: if the client already holds this exact version, skip
    # the body. Browsers echo the ETag back in If-None-Match on every revalidate.
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)

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
            **cache_headers,
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
_HEATMAP_LIVE_TTL = 60  # live mode, market open: near-real-time, refreshed each minute
# Live mode while the LSE is closed: the "live" figure is just the last completed
# session's close-to-close move, which is static until the next session. So the
# expensive full-universe yfinance scrape only needs to run rarely — cache it
# long instead of re-scraping every 60s, which is what made the closed-market
# heatmap slow to load.
_HEATMAP_LIVE_CLOSED_TTL = 1800  # 30 minutes


def _lse_open(now=None):
    """True if the LSE is in a regular trading session right now (Mon–Fri,
    08:00–16:30 London). Holidays aren't excluded: misjudging a holiday as
    "open" only forgoes the aggressive closed-market cache (the data is static
    anyway), so it degrades to the old 60s behaviour rather than serving wrong
    data. Mirrors isLseOpen() in frontend HeatmapTab.js."""
    from datetime import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        now = now or _dt.now(ZoneInfo("Europe/London"))
    except Exception:
        now = now or _dt.utcnow()  # London ≈ UTC; close enough for the gate
    if now.weekday() >= 5:  # Sat/Sun
        return False
    mins = now.hour * 60 + now.minute
    return 8 * 60 <= mins <= 16 * 60 + 30


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

    # While the market is open, live data moves minute-to-minute (60s). Once
    # closed, the live figure settles to the last session's move and is static
    # until the next session, so cache it long and let the edge serve it stale —
    # this is what keeps the closed-market heatmap from re-scraping yfinance on
    # every load.
    if live:
        if _lse_open():
            ttl, s_maxage, swr = _HEATMAP_LIVE_TTL, 60, 3600
        else:
            ttl, s_maxage, swr = _HEATMAP_LIVE_CLOSED_TTL, _HEATMAP_LIVE_CLOSED_TTL, 86400
    else:
        ttl, s_maxage, swr = _HEATMAP_TTL, 900, 3600
    response.headers["Cache-Control"] = (
        f"public, s-maxage={s_maxage}, stale-while-revalidate={swr}"
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
