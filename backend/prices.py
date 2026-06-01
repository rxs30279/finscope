from fastapi import APIRouter, HTTPException, Response
import yfinance as yf
import pandas as pd
import psycopg2
import psycopg2.extras
import psycopg2.pool
import holidays
import os
import time
import logging
from datetime import date, timedelta
from dotenv import load_dotenv
from _mem import snapshot as _mem

# LSE follows England & Wales bank holidays.
_LSE_HOLIDAYS = holidays.UnitedKingdom(subdiv="ENG")

logger = logging.getLogger(__name__)

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


# ── Helpers ────────────────────────────────────────────────────────────────────


def _next_trading_day(d: date) -> date:
    """Advance *d* past weekends and UK bank holidays (LSE non-trading days).

    Without this, a top-up scheduled the day after a UK bank holiday (e.g.
    Tue after Spring Bank Holiday) would request data for the holiday itself
    and yfinance would return empty for every symbol, triggering retries
    that previously OOM'd the Render worker on 2026-05-26.
    """
    # Monday=0 … Sunday=6
    while d.weekday() >= 5 or d in _LSE_HOLIDAYS:
        d += timedelta(days=1)
    return d


# ── Price fetch ───────────────────────────────────────────────────────────────

_BATCH_SIZE = 25  # yfinance chokes on large batches — keep small
_BATCH_SLEEP_S = 1.5  # delay between batches to avoid rate limiting
_MAX_RETRIES = 2  # retry a failed batch once
_DEACTIVATE_AFTER = 3  # consecutive empty refreshes before a symbol is dropped


def _fetch_ohlcv_batch(symbols, start_date):
    """Fetch adjusted daily OHLCV for a single batch of symbols.
    Returns list of (symbol, date, open, high, low, close, volume) tuples."""
    # yfinance's `end` is exclusive — use tomorrow so today's bar is included
    # once the LSE has closed for the day.
    end_date = date.today() + timedelta(days=1)
    if not symbols:
        return []

    try:
        df = yf.download(
            tickers=symbols,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.warning("yf.download batch failed for %d symbols: %s", len(symbols), e)
        return []

    if df is None or df.empty:
        return []

    # Branch on the actual column shape, NOT len(symbols). yfinance returns a
    # MultiIndex (attr, symbol) whenever `tickers` is a *list* — even a
    # single-element list — and flat columns only for a bare string ticker.
    # The old len==1 path assumed flat columns, so `{"Open",...}.issubset(...)`
    # always failed against the MultiIndex and every solo-symbol batch silently
    # returned [] despite yfinance returning full data — stragglers never caught
    # up and looked "delisted".
    required = {"Open", "High", "Low", "Close", "Volume"}
    rows = []
    if isinstance(df.columns, pd.MultiIndex):
        if not required.issubset(set(df.columns.get_level_values(0))):
            return []
        for sym in symbols:
            if ("Close", sym) not in df.columns:
                continue  # yfinance dropped a failed/unknown symbol from the frame
            for dt in df.index:
                o = df[("Open", sym)][dt]
                h = df[("High", sym)][dt]
                l = df[("Low", sym)][dt]
                c = df[("Close", sym)][dt]
                v = df[("Volume", sym)][dt]
                if any(pd.isna(x) for x in (o, h, l, c)):
                    continue
                rows.append(
                    (sym, dt.date(), float(o), float(h), float(l), float(c),
                     int(v) if pd.notna(v) else 0)
                )
    else:
        if not required.issubset(df.columns):
            return []
        sym = symbols[0]
        for dt, row in df.iterrows():
            o, h, l, c, v = (
                row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
            )
            if any(pd.isna(x) for x in (o, h, l, c)):
                continue
            rows.append(
                (sym, dt.date(), float(o), float(h), float(l), float(c),
                 int(v) if pd.notna(v) else 0)
            )
    return rows


def _fetch_ohlcv(symbols, start_date):
    """Fetch adjusted daily OHLCV for symbols from start_date to today.
    Splits into small batches with delays to avoid yfinance rate limiting.
    Returns list of (symbol, date, open, high, low, close, volume) tuples."""
    if not symbols:
        return []

    all_rows = []
    total = len(symbols)
    # Process in batches
    for i in range(0, total, _BATCH_SIZE):
        batch = symbols[i : i + _BATCH_SIZE]
        logger.info(
            "Fetching prices batch %d/%d (%d symbols, start=%s)",
            i // _BATCH_SIZE + 1,
            (total + _BATCH_SIZE - 1) // _BATCH_SIZE,
            len(batch),
            start_date,
        )

        # Try the batch with retries
        rows = None
        for attempt in range(_MAX_RETRIES):
            if attempt > 0:
                logger.info("Retry %d for batch starting at index %d", attempt + 1, i)
                time.sleep(_BATCH_SLEEP_S * 2)  # longer wait before retry
            rows = _fetch_ohlcv_batch(batch, start_date)
            if rows:
                break  # got data, no need to retry

        if rows:
            all_rows.extend(rows)
        else:
            logger.warning(
                "No price data for batch %d/%d (%d symbols) after %d attempts",
                i // _BATCH_SIZE + 1,
                (total + _BATCH_SIZE - 1) // _BATCH_SIZE,
                len(batch),
                _MAX_RETRIES,
            )

        _mem(
            "price_fetch",
            "batch_done",
            batch=i // _BATCH_SIZE + 1,
            total_batches=(total + _BATCH_SIZE - 1) // _BATCH_SIZE,
            rows_in_batch=len(rows) if rows else 0,
            all_rows=len(all_rows),
        )

        # Delay between batches (skip after last batch)
        if i + _BATCH_SIZE < total:
            time.sleep(_BATCH_SLEEP_S)

    return all_rows


# ── Activity tracking ───────────────────────────────────────────────────────


def _update_activity(fetched, missed):
    """Maintain is_active / empty_fetch_count on company_metadata.

    *fetched* — symbols that returned at least one row this run.
    *missed*  — symbols we attempted but got nothing back (likely delisted).

    Symbols that come back empty on _DEACTIVATE_AFTER consecutive refreshes are
    flipped to is_active=false so refresh_prices() stops querying them (and
    yfinance stops printing "possibly delisted" spam). Returns the list of
    symbols deactivated on this run.
    """
    deactivated = []
    if not fetched and not missed:
        return deactivated
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        if fetched:
            cur.execute(
                "UPDATE company_metadata SET empty_fetch_count = 0"
                " WHERE symbol = ANY(%s) AND empty_fetch_count <> 0",
                (list(fetched),),
            )
        if missed:
            cur.execute(
                "UPDATE company_metadata"
                "   SET empty_fetch_count = empty_fetch_count + 1,"
                "       is_active = (empty_fetch_count + 1 < %s)"
                " WHERE symbol = ANY(%s)"
                " RETURNING symbol, is_active",
                (_DEACTIVATE_AFTER, list(missed)),
            )
            deactivated = [row[0] for row in cur.fetchall() if not row[1]]
        conn.commit()
        return deactivated
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


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

    # Active symbols in the universe (delisted tickers are dropped — see
    # _update_activity / migrations/001_company_active_flag.sql)
    all_symbols = [
        r["symbol"]
        for r in query(
            "SELECT symbol FROM company_metadata WHERE is_active ORDER BY symbol"
        )
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
            # Top-up from latest stored date (skip weekends)
            top_up_start = _next_trading_day(latest[sym] + timedelta(days=1))
            groups.setdefault(top_up_start, []).append(sym)
            # Backfill if we don't have 5Y of history
            if sym in earliest and earliest[sym] > target_start:
                groups.setdefault(target_start, []).append(sym)
        else:
            groups.setdefault(target_start, []).append(sym)

    _mem(
        "price_refresh",
        "groups_computed",
        n_groups=len(groups),
        n_symbols=len(all_symbols),
    )

    total_rows = 0
    attempted = set()  # symbols we actually tried to fetch this run
    fetched = set()  # symbols that returned at least one row
    for start_date, symbols in groups.items():
        if start_date > date.today():
            continue  # already up to date
        attempted.update(symbols)
        _mem(
            "price_refresh",
            "group_start",
            start_date=start_date.isoformat(),
            n_symbols=len(symbols),
        )
        rows = _fetch_ohlcv(symbols, start_date)
        fetched.update(row[0] for row in rows)
        total_rows += _upsert_rows(rows)
        _mem(
            "price_refresh",
            "group_done",
            start_date=start_date.isoformat(),
            rows_added=len(rows),
        )

    # Mark symbols that came back empty; deactivate persistently-empty ones.
    # Prices are already committed, so don't fail the run if this can't write
    # (e.g. migration not yet applied) — just log and carry on.
    missed = attempted - fetched
    try:
        deactivated = _update_activity(fetched, missed)
    except Exception as e:
        logger.warning("activity update skipped: %s", e)
        deactivated = []
    if deactivated:
        logger.info("Deactivated %d delisted symbols: %s",
                    len(deactivated), ", ".join(sorted(deactivated)))
    _mem(
        "price_refresh",
        "activity_updated",
        fetched=len(fetched),
        missed=len(missed),
        deactivated=len(deactivated),
    )

    return {
        "updated": len(all_symbols),
        "rows_added": total_rows,
        "deactivated": deactivated,
        "duration_seconds": round(time.time() - t0, 1),
    }


@router.get("/api/prices/{symbol}")
def get_prices(symbol: str):
    """Return full OHLCV history for a symbol, oldest first."""
    rows = query(
        "SELECT date, open, high, low, close, volume FROM price_history"
        " WHERE symbol = %s ORDER BY date ASC",
        (symbol,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No price history")
    return [
        {
            "date": str(r["date"]),
            "open": float(r["open"]) if r.get("open") is not None else None,
            "high": float(r["high"]) if r.get("high") is not None else None,
            "low": float(r["low"]) if r.get("low") is not None else None,
            "close": float(r["close"]),
            "volume": int(r["volume"]) if r.get("volume") is not None else None,
        }
        for r in rows
    ]


# ── Trending (consecutive up / down day streaks) ──────────────────────────────

_trending_cache: dict = {}
_TRENDING_TTL = 900  # 15 min — price history only refreshes once/day


def _trailing_streak(closes):
    """Signed streak of consecutive same-direction days at the end of *closes*.

    *closes* is oldest-first. A "day" is one close vs the prior close. Returns
    +k for k consecutive up days, -k for k consecutive down days, 0 if the most
    recent move is flat or there's too little history.
    """
    if len(closes) < 2:
        return 0
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    last = diffs[-1]
    if last == 0:
        return 0
    direction = 1 if last > 0 else -1
    count = 0
    for d in reversed(diffs):
        if (direction > 0 and d > 0) or (direction < 0 and d < 0):
            count += 1
        else:
            break
    return direction * count


@router.get("/api/trending")
def trending(response: Response, min_streak: int = 3, limit: int = 40):
    """Stocks on a run of consecutive up days (risers) or down days (fallers).

    Streak = trailing run of same-direction daily closes. Only stocks with a
    streak of *min_streak* days or more are returned, ranked by streak length
    (longest first). Each row carries the latest price and market cap. Cached
    15 min since the underlying price data only refreshes once/day.
    """
    # Vercel edge CDN cache — fresh 15 min, serve stale up to 1h while
    # revalidating, mirroring /api/screener so cold-starts stay off the path.
    response.headers["Cache-Control"] = (
        "public, s-maxage=900, stale-while-revalidate=3600"
    )
    cache_key = (min_streak, limit)
    now = time.time()
    cached = _trending_cache.get(cache_key)
    if cached and now - cached[1] < _TRENDING_TTL:
        return cached[0]

    # Last ~40 closes per active symbol, oldest-first within each symbol
    # (ORDER BY rn DESC puts the largest rn — oldest date — first).
    rows = query(
        """
        WITH numbered AS (
            SELECT p.symbol, p.close,
                   ROW_NUMBER() OVER (PARTITION BY p.symbol ORDER BY p.date DESC) AS rn
            FROM price_history p
            JOIN company_metadata m ON m.symbol = p.symbol AND m.is_active
        )
        SELECT symbol, close FROM numbered
        WHERE rn <= 40
        ORDER BY symbol, rn DESC
        """
    )

    closes_map = {}
    for r in rows:
        closes_map.setdefault(r["symbol"], []).append(float(r["close"]))

    qualifying = {}
    for sym, closes in closes_map.items():
        streak = _trailing_streak(closes)
        if abs(streak) < min_streak:
            continue
        k = abs(streak)
        start = closes[-(k + 1)]
        latest = closes[-1]
        pct = (latest / start - 1) * 100 if start else None
        qualifying[sym] = {
            "symbol": sym,
            "streak": k,
            "price": latest,
            "pct": round(pct, 2) if pct is not None else None,
            "_dir": 1 if streak > 0 else -1,
        }

    # Attach name, market cap and reporting currency for the qualifying symbols.
    if qualifying:
        meta = query(
            """
            SELECT m.symbol, m.name, m.sector, m.financial_currency, t.market_cap
            FROM company_metadata m
            LEFT JOIN ttm_financials t ON t.company_symbol = m.symbol
            WHERE m.symbol = ANY(%s)
            """,
            (list(qualifying.keys()),),
        )
        meta_map = {r["symbol"]: r for r in meta}
        for sym, item in qualifying.items():
            m = meta_map.get(sym, {})
            item["name"] = m.get("name") or sym
            item["sector"] = m.get("sector")
            item["currency"] = m.get("financial_currency") or "GBP"
            item["market_cap"] = (
                float(m["market_cap"]) if m.get("market_cap") is not None else None
            )

    risers, fallers = [], []
    for item in qualifying.values():
        (risers if item.pop("_dir") > 0 else fallers).append(item)

    # Rank by streak length first, then by size of the move over the streak.
    risers.sort(key=lambda x: (x["streak"], x["pct"] or 0), reverse=True)
    fallers.sort(key=lambda x: (x["streak"], -(x["pct"] or 0)), reverse=True)

    result = {"risers": risers[:limit], "fallers": fallers[:limit]}
    _trending_cache[cache_key] = (result, now)
    return result


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

    # Top-up from latest stored date to today (skip weekends)
    if latest is not None:
        top_up_start = _next_trading_day(latest + timedelta(days=1))
        if top_up_start <= date.today():
            fetched = _fetch_ohlcv([symbol], top_up_start)
            total += _upsert_rows(fetched)

    return {"rows_added": total}
