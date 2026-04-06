from fastapi import APIRouter
import yfinance as yf
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import time
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# ── DB (own pool to avoid circular import with main.py) ───────────────────────

_DB_CONFIG = {
    "dbname":   os.environ.get("DB_NAME", "postgres"),
    "user":     os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host":     os.environ.get("DB_HOST", ""),
    "port":     os.environ.get("DB_PORT", "5432"),
    "sslmode":  "require",
}

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, **_DB_CONFIG)
    return _pool

def query(sql, params=None):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        pool.putconn(conn)

def _upsert_rows(rows):
    """Insert (symbol, date, close) tuples into price_history. Returns row count."""
    if not rows:
        return 0
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO price_history (symbol, date, close) VALUES %s ON CONFLICT DO NOTHING",
            rows,
            page_size=1000,
        )
        count = len(rows)
        conn.commit()
        return count
    finally:
        pool.putconn(conn)


# ── Price fetch ───────────────────────────────────────────────────────────────

THREE_YEARS_AGO = date.today() - timedelta(days=3 * 365)


def _fetch_closes(symbols, start_date):
    """Fetch adjusted daily closes for symbols from start_date to today.
    Returns list of (symbol, date, close) tuples."""
    end_date = date.today()
    if not symbols:
        return []

    df = yf.download(
        tickers=symbols,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        return []

    # yfinance returns MultiIndex columns for multiple tickers,
    # flat columns for a single ticker
    if len(symbols) == 1:
        if 'Close' not in df.columns:
            return []
        closes = df[['Close']].copy()
        closes.columns = [symbols[0]]
    else:
        if 'Close' not in df.columns.get_level_values(0):
            return []
        closes = df['Close']

    rows = []
    for sym in closes.columns:
        for dt, val in closes[sym].dropna().items():
            rows.append((sym, dt.date(), float(val)))
    return rows


# ── Momentum scoring ──────────────────────────────────────────────────────────

def _attach_momentum(results):
    """Add momentum_score (1-10) to each screener result row.

    Uses 12-1 month momentum: return from 252 trading days ago to 63 trading
    days ago (excludes recent 3 months to avoid short-term reversal).
    Scores are percentile-ranked within the result universe.
    """
    if not results:
        return results

    symbols = [r['symbol'] for r in results]

    rows = query("""
        WITH numbered AS (
            SELECT symbol, close,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
            FROM price_history
            WHERE symbol = ANY(%s)
        )
        SELECT symbol,
               MAX(CASE WHEN rn = 63  THEN close END) AS close_63,
               MAX(CASE WHEN rn = 252 THEN close END) AS close_252
        FROM numbered
        WHERE rn IN (63, 252)
        GROUP BY symbol
    """, (symbols,))

    returns = {}
    for r in rows:
        c63, c252 = r['close_63'], r['close_252']
        if c63 is not None and c252 is not None and float(c252) > 0:
            returns[r['symbol']] = float(c63) / float(c252) - 1

    # Rank within universe → 1-10 score
    scores = {}
    if returns:
        sorted_syms = sorted(returns, key=lambda s: returns[s])
        n = len(sorted_syms)
        for i, sym in enumerate(sorted_syms):
            scores[sym] = max(1, min(10, int(i / n * 10) + 1))

    for r in results:
        r['momentum_score'] = scores.get(r['symbol'])
    return results


# ── Refresh endpoint ──────────────────────────────────────────────────────────

@router.post("/api/prices/refresh")
def refresh_prices():
    """Fetch missing price history for all stocks via yfinance and upsert."""
    t0 = time.time()

    # All symbols in the universe
    all_symbols = [r['symbol'] for r in query(
        "SELECT symbol FROM company_metadata ORDER BY symbol"
    )]

    # Latest stored date per symbol
    latest = {
        r['symbol']: r['latest']
        for r in query(
            "SELECT symbol, MAX(date) AS latest FROM price_history GROUP BY symbol"
        )
    }

    # Group symbols by the start date we need to fetch from
    groups = {}  # start_date -> [symbols]
    for sym in all_symbols:
        if sym in latest and latest[sym] is not None:
            start = latest[sym] + timedelta(days=1)
        else:
            start = THREE_YEARS_AGO
        groups.setdefault(start, []).append(sym)

    total_rows = 0
    for start_date, symbols in groups.items():
        if start_date >= date.today():
            continue  # already up to date
        rows = _fetch_closes(symbols, start_date)
        total_rows += _upsert_rows(rows)

    return {
        "updated": len(all_symbols),
        "rows_added": total_rows,
        "duration_seconds": round(time.time() - t0, 1),
    }
