import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import psycopg2.extras
import psycopg2.pool
from typing import Optional
from dotenv import load_dotenv
import os
from market import router as market_router
from prices import router as prices_router, _attach_momentum

load_dotenv()

app = FastAPI(title="Finance API")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(market_router)
app.include_router(prices_router)

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require"
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

@app.get("/api/search")
def search(q: str = Query(..., min_length=1)):
    return query("""
        SELECT symbol, name, sector, industry, exchange, country
        FROM company_metadata
        WHERE symbol ILIKE %s OR name ILIKE %s
        ORDER BY symbol LIMIT 20
    """, (f"{q}%", f"%{q}%"))

@app.get("/api/company")
def company(symbol: str = Query(...)):
    rows = query("SELECT * FROM company_metadata WHERE symbol = %s", (symbol,))
    if not rows: raise HTTPException(404, "Not found")
    return rows[0]

@app.get("/api/snapshot")
def snapshot(symbol: str = Query(...)):
    rows = query("SELECT * FROM ttm_financials WHERE company_symbol = %s", (symbol,))
    if not rows: raise HTTPException(404, "No data")
    return rows[0]

@app.get("/api/annual")
def annual(symbol: str = Query(...)):
    return query("""
        SELECT * FROM annual_financials
        WHERE company_symbol = %s
        ORDER BY period_end_date ASC
    """, (symbol,))

@app.get("/api/quarterly")
def quarterly(symbol: str = Query(...)):
    return query("""
        SELECT * FROM quarterly_financials
        WHERE company_symbol = %s
        ORDER BY period_end_date ASC
        LIMIT 20
    """, (symbol,))

def _piotroski_score(row):
    """Compute Piotroski F-Score (0-9) from an annual_financials row pair."""
    score = 0
    roa_cur   = row.get('roa_cur')
    roa_prev  = row.get('roa_prev')
    cfo       = row.get('cf_cfo')
    ta_cur    = row.get('ta_cur') or 0
    de_cur    = row.get('de_cur')
    de_prev   = row.get('de_prev')
    cr_cur    = row.get('cr_cur')
    cr_prev   = row.get('cr_prev')
    sh_cur    = row.get('sh_cur')
    sh_prev   = row.get('sh_prev')
    gm_cur    = row.get('gm_cur')
    gm_prev   = row.get('gm_prev')
    rev_cur   = row.get('rev_cur')
    rev_prev  = row.get('rev_prev')
    ta_prev   = row.get('ta_prev') or 0

    # Profitability
    if roa_cur  is not None and roa_cur > 0:                              score += 1  # F1
    if cfo      is not None and cfo > 0:                                  score += 1  # F2
    if roa_cur  is not None and roa_prev is not None and roa_cur > roa_prev: score += 1  # F3
    if cfo is not None and ta_cur > 0 and roa_cur is not None and (cfo / ta_cur) > roa_cur: score += 1  # F4 accruals
    # Leverage / liquidity
    if de_cur   is not None and de_prev  is not None and de_cur < de_prev: score += 1  # F5
    if cr_cur   is not None and cr_prev  is not None and cr_cur > cr_prev: score += 1  # F6
    if sh_cur   is not None and sh_prev  is not None and sh_cur <= sh_prev: score += 1  # F7 no dilution
    # Efficiency
    if gm_cur   is not None and gm_prev  is not None and gm_cur > gm_prev: score += 1  # F8
    if (rev_cur is not None and ta_cur > 0 and                                          # F9 asset turnover
        rev_prev is not None and ta_prev > 0 and
        rev_cur / ta_cur > rev_prev / ta_prev):                           score += 1

    return score


def _quality_score(r):
    """Quality score 0-10: rewards high AND consistent returns/margins."""
    score = 0
    roic   = r.get('roic');            roic_med = r.get('roic_median')
    roe    = r.get('roe');             roe_med  = r.get('roe_median')
    gm     = r.get('gross_margin');    gm_med   = r.get('gross_margin_median')
    om     = r.get('operating_margin');om_med   = r.get('operating_margin_median')
    fcfm   = r.get('fcf_margin')
    nm     = r.get('net_income_margin');nm_med  = r.get('net_margin_median')

    if roic is not None:
        if roic > 0.10: score += 1
        if roic_med is not None and roic >= roic_med: score += 1
    if roe is not None:
        if roe > 0.15: score += 1
        if roe_med is not None and roe >= roe_med: score += 1
    if gm is not None:
        if gm > 0.30: score += 1
        if gm_med is not None and gm >= gm_med: score += 1
    if om is not None:
        if om > 0.10: score += 1
        if om_med is not None and om >= om_med: score += 1
    if fcfm is not None:
        if fcfm > 0.05: score += 1
        if nm is not None and nm_med is not None and nm >= nm_med: score += 1

    return score


def _attach_piotroski(results):
    """Add piotroski_score to each screener result row."""
    if not results:
        return results
    symbols = [r['symbol'] for r in results]
    rows = query("""
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
    """, (symbols,))

    scores = {r['company_symbol']: _piotroski_score(r) for r in rows}
    for r in results:
        r['piotroski_score'] = scores.get(r['symbol'])
    return results


@app.get("/api/screener")
def screener(
    sector: Optional[str]=None,
    country: Optional[str]=None,
    ftse_index: Optional[str]=None,
    min_market_cap: Optional[float]=None,
    max_pe: Optional[float]=None,
    min_roe: Optional[float]=None,
    min_revenue_growth: Optional[float]=None,
    limit: int=100
):
    wheres = ["1=1"]
    params = []
    if sector: wheres.append("m.sector = %s"); params.append(sector)
    if country: wheres.append("m.country = %s"); params.append(country)
    if ftse_index:
        if ftse_index == 'FTSE 350':
            wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250')")
        elif ftse_index == 'FTSE All-Share':
            wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250', 'FTSE SmallCap')")
        else:
            wheres.append("m.ftse_index = %s"); params.append(ftse_index)
    if min_market_cap: wheres.append("t.market_cap >= %s"); params.append(min_market_cap)
    if max_pe: wheres.append("t.price_to_earnings <= %s AND t.price_to_earnings > 0"); params.append(max_pe)
    if min_roe: wheres.append("t.roe >= %s"); params.append(min_roe)
    if min_revenue_growth: wheres.append("t.revenue_growth >= %s"); params.append(min_revenue_growth)
    params.append(limit)
    sql = f"""
        SELECT m.symbol, m.name, m.sector, m.country, m.exchange, m.ftse_index,
               t.market_cap, t.revenue, t.net_income,
               CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END as price_to_earnings,
               t.price_to_book, t.price_to_sales, t.roe, t.roa, t.roic, t.roce,
               t.gross_margin, t.operating_margin, t.net_income_margin,
               t.revenue_growth, t.eps_diluted_growth, t.fcf_growth,
               t.debt_to_equity, t.current_ratio, t.fcf, t.ebitda,
               t.revenue_cagr_10, t.eps_cagr_10, t.period_end_date,
               t.fcf_margin,
               t.gross_margin_median, t.operating_margin_median,
               t.net_margin_median, t.roe_median, t.roic_median
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY t.market_cap DESC NULLS LAST
        LIMIT %s
    """
    results = query(sql, params)
    for r in results:
        r['quality_score'] = _quality_score(r)
    _attach_momentum(results)
    return _attach_piotroski(results)

@app.get("/api/filters")
def filters():
    sectors  = query("SELECT DISTINCT sector FROM company_metadata WHERE sector IS NOT NULL ORDER BY sector")
    countries = query("SELECT DISTINCT country FROM company_metadata WHERE country IS NOT NULL ORDER BY country")
    return {
        "sectors":  [r["sector"] for r in sectors],
        "countries": [r["country"] for r in countries],
    }
