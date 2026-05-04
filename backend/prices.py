from fastapi import APIRouter, HTTPException
import yfinance as yf
import pandas as pd
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
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
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
    conn.autocommit = True  # prevent idle-in-transaction; query() is read-only
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        pool.putconn(conn)


def _upsert_rows(rows):
    """Insert (symbol, date, open, high, low, close, volume) tuples into price_history.
    Uses ON CONFLICT DO UPDATE so re-runs fill in any missing OHLCV columns.
    Returns row count.
    """
    if not rows:
        return 0
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO price_history (symbol, date, open, high, low, close, volume)"
            " VALUES %s"
            " ON CONFLICT (symbol, date) DO UPDATE SET"
            "   open  = COALESCE(EXCLUDED.open,  price_history.open),"
            "   high  = COALESCE(EXCLUDED.high,  price_history.high),"
            "   low   = COALESCE(EXCLUDED.low,   price_history.low),"
            "   close = COALESCE(EXCLUDED.close, price_history.close),"
            "   volume= COALESCE(EXCLUDED.volume,price_history.volume)",
            rows,
            page_size=1000,
        )
        count = max(0, cur.rowcount)
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Price fetch ───────────────────────────────────────────────────────────────


def _fetch_ohlcv(symbols, start_date):
    """Fetch adjusted daily OHLCV for symbols from start_date to today.
    Returns list of (symbol, date, open, high, low, close, volume) tuples."""
    end_date = (
        date.today()
    )  # yf.download end is exclusive — today's partial session is intentionally excluded
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
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return []
        ohlcv = df[list(required)].copy()
        ohlcv.columns = symbols  # flatten: each col becomes the symbol name
    else:
        top = df.columns.get_level_values(0)
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(top):
            return []
        ohlcv = df  # keep MultiIndex, we'll index by (attr, sym) below

    rows = []
    if len(symbols) == 1:
        sym = symbols[0]
        for dt, row in ohlcv.iterrows():
            rows.append(
                (
                    sym,
                    dt.date(),
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    int(row["Volume"]),
                )
            )
    else:
        for sym in symbols:
            for dt in ohlcv.index:
                o = ohlcv["Open"][sym][dt]
                h = ohlcv["High"][sym][dt]
                l = ohlcv["Low"][sym][dt]
                c = ohlcv["Close"][sym][dt]
                v = ohlcv["Volume"][sym][dt]
                # Skip rows where any OHLC value is NaN
                if any(pd.isna(x) for x in (o, h, l, c)):
                    continue
                rows.append(
                    (
                        sym,
                        dt.date(),
                        float(o),
                        float(h),
                        float(l),
                        float(c),
                        int(v),
                    )
                )
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

    symbols = [r["symbol"] for r in results]

    # Stocks without exactly 252+ rows of history silently get momentum_score=None via scores.get()
    rows = query(
        """
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
    """,
        (symbols,),
    )

    returns = {}
    for r in rows:
        c63, c252 = r["close_63"], r["close_252"]
        if c63 is not None and c252 is not None and float(c252) > 0:
            returns[r["symbol"]] = float(c63) / float(c252) - 1

    # Rank within universe → 1-10 score
    scores = {}
    if returns:
        sorted_syms = sorted(returns, key=lambda s: returns[s])
        n = len(sorted_syms)
        for i, sym in enumerate(sorted_syms):
            scores[sym] = max(1, min(10, int(i / n * 10) + 1))

    for r in results:
        r["momentum_score"] = scores.get(r["symbol"])
    return results


# ── Refresh endpoint ──────────────────────────────────────────────────────────


@router.post("/api/prices/refresh")
def refresh_prices():
    """Fetch missing price history for all stocks via yfinance and upsert."""
    t0 = time.time()

    # All symbols in the universe
    all_symbols = [
        r["symbol"]
        for r in query("SELECT symbol FROM company_metadata ORDER BY symbol")
    ]

    # Latest stored date per symbol
    latest = {
        r["symbol"]: r["latest"]
        for r in query(
            "SELECT symbol, MAX(date) AS latest FROM price_history GROUP BY symbol"
        )
    }

    # Earliest stored date per symbol (for backfill detection)
    earliest = {
        r["symbol"]: r["earliest"]
        for r in query(
            "SELECT symbol, MIN(date) AS earliest FROM price_history GROUP BY symbol"
        )
    }

    target_start = date.today() - timedelta(days=5 * 365)

    # Group symbols by the start date we need to fetch from
    groups = {}  # start_date -> [symbols]
    for sym in all_symbols:
        if sym in latest and latest[sym] is not None:
            # Top-up from latest stored date
            top_up_start = latest[sym] + timedelta(days=1)
            groups.setdefault(top_up_start, []).append(sym)
            # Backfill if we don't have 5Y of history
            if sym in earliest and earliest[sym] > target_start:
                groups.setdefault(target_start, []).append(sym)
        else:
            groups.setdefault(target_start, []).append(sym)

    total_rows = 0
    for start_date, symbols in groups.items():
        if start_date >= date.today():
            continue  # already up to date
        rows = _fetch_ohlcv(symbols, start_date)
        total_rows += _upsert_rows(rows)

    return {
        "updated": len(all_symbols),
        "rows_added": total_rows,
        "duration_seconds": round(time.time() - t0, 1),
    }


@router.get("/api/prices/{symbol}")
def get_prices(symbol: str):
    """Return full close history for a symbol, oldest first."""
    rows = query(
        "SELECT date, close FROM price_history WHERE symbol = %s ORDER BY date ASC",
        (symbol,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No price history")
    return [{"date": str(r["date"]), "close": float(r["close"])} for r in rows]


@router.post("/api/prices/refresh/{symbol}")
def refresh_symbol(symbol: str):
    """Top up price history for a single symbol to today, backfilling to 5Y if needed."""
    rows = query(
        "SELECT MIN(date) AS earliest, MAX(date) AS latest FROM price_history WHERE symbol = %s",
        (symbol,),
    )
    earliest = rows[0]["earliest"] if rows else None
    latest = rows[0]["latest"] if rows else None

    target_start = date.today() - timedelta(days=5 * 365)
    total = 0

    # Backfill older history if we have less than 5Y
    if earliest is None or earliest > target_start:
        fetched = _fetch_ohlcv([symbol], target_start)
        total += _upsert_rows(fetched)

    # Top-up from latest stored date to today
    if latest is not None:
        top_up_start = latest + timedelta(days=1)
        if top_up_start < date.today():
            fetched = _fetch_ohlcv([symbol], top_up_start)
            total += _upsert_rows(fetched)

    return {"rows_added": total}
