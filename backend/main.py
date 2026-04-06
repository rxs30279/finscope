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

load_dotenv()

app = FastAPI(title="Finance API")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(market_router)

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
    try:
        pool = get_pool()
    except Exception as e:
        print(f"[db] pool creation failed: {e}")
        raise
    try:
        conn = pool.getconn()
    except Exception as e:
        print(f"[db] getconn failed: {e}")
        raise
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] query failed: {e}")
        raise
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
               t.revenue_cagr_10, t.eps_cagr_10, t.period_end_date
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY t.market_cap DESC NULLS LAST
        LIMIT %s
    """
    return query(sql, params)

@app.get("/api/filters")
def filters():
    sectors  = query("SELECT DISTINCT sector FROM company_metadata WHERE sector IS NOT NULL ORDER BY sector")
    countries = query("SELECT DISTINCT country FROM company_metadata WHERE country IS NOT NULL ORDER BY country")
    return {
        "sectors":  [r["sector"] for r in sectors],
        "countries": [r["country"] for r in countries],
    }
