from fastapi import APIRouter, Query, Response
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import time
import logging
from datetime import date, timedelta
from dotenv import load_dotenv

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


# ── Ingestion ──────────────────────────────────────────────────────────────────

_SLEEP_S = 1.0  # delay between tickers to avoid yfinance rate limiting (updater.py convention)


def _fetch_symbol_events(symbol, currency):
    """Fetch full per-payment dividend history for one symbol via yfinance.

    Returns a list of (symbol, ex_date, amount, currency) tuples, or [] if the
    symbol has no dividend history (or the fetch failed). Amounts are left
    exactly as yfinance reports them — denominated in the quote currency, the
    same currency the price used for the yield calc is in, so no FX conversion
    is needed anywhere downstream.
    """
    import yfinance as yf  # deferred: heaviest import, only the refresh path needs it

    try:
        divs = yf.Ticker(symbol).dividends
    except Exception as e:
        logger.warning("yfinance dividends fetch failed for %s: %s", symbol, e)
        return []

    if divs is None or divs.empty:
        return []

    # Index is tz-aware (Europe/London); collapse to a plain date and sum any
    # same-day duplicates (rare special+regular payment on one ex-date) so the
    # (symbol, ex_date) primary key holds.
    totals = {}
    for ts, amount in divs.items():
        if amount is None or amount <= 0:
            continue
        d = ts.date()
        totals[d] = totals.get(d, 0.0) + float(amount)

    return [(symbol, d, amt, currency) for d, amt in totals.items()]


def _replace_symbol_events(conn, symbol, rows):
    """Replace all dividend_events rows for *symbol* with *rows* in one transaction.

    A full per-symbol replace (rather than ON CONFLICT upsert) self-heals amount
    revisions AND shifted/cancelled ex-dates — an upsert alone would leave a
    stale ghost row behind when yfinance moves or drops a declared date.
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM dividend_events WHERE company_symbol = %s", (symbol,))
    if rows:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO dividend_events (company_symbol, ex_date, amount, currency) VALUES %s",
            rows,
        )
    conn.commit()


def refresh_dividends(symbols=None):
    """Refresh dividend_events for the given symbols (default: whole active universe).

    Fetches each symbol's complete dividend history from yfinance and replaces
    its rows wholesale. A symbol whose fetch comes back empty is SKIPPED (not
    wiped) when the DB already holds rows for it, so a transient yfinance
    failure can't silently erase history — the weekly re-run will pick it up.
    """
    t0 = time.time()

    universe = query(
        "SELECT symbol, currency FROM company_metadata WHERE is_active ORDER BY symbol"
    )
    if symbols:
        wanted = set(symbols)
        universe = [r for r in universe if r["symbol"] in wanted]

    existing_counts = {
        r["company_symbol"]: r["n"]
        for r in query(
            "SELECT company_symbol, COUNT(*) AS n FROM dividend_events GROUP BY company_symbol"
        )
    }

    pool = _get_pool()
    conn = pool.getconn()
    try:
        n_symbols = 0
        n_rows = 0
        n_skipped_empty = 0
        for i, r in enumerate(universe):
            sym, currency = r["symbol"], r.get("currency") or "GBp"
            rows = _fetch_symbol_events(sym, currency)

            if not rows and existing_counts.get(sym, 0) > 0:
                n_skipped_empty += 1
            else:
                _replace_symbol_events(conn, sym, rows)
                n_symbols += 1
                n_rows += len(rows)

            if i < len(universe) - 1:
                time.sleep(_SLEEP_S)
    finally:
        pool.putconn(conn)

    return {
        "symbols_processed": n_symbols,
        "symbols_skipped_empty": n_skipped_empty,
        "rows_written": n_rows,
        "duration_seconds": round(time.time() - t0, 1),
    }


def record_run(status: str, detail: dict):
    """Stamp pipeline_runs so healthcheck.py can tell the weekly sweep ran —
    a run that legitimately touches few/no rows leaves no other DB trace
    (migration 008 convention, see refresh_index_membership.py)."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
            VALUES ('dividends_refresh', NOW(), %s, %s)
            ON CONFLICT (pipeline) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                status      = EXCLUDED.status,
                detail      = EXCLUDED.detail
            """,
            (status, psycopg2.extras.Json(detail)),
        )
        conn.commit()
    finally:
        pool.putconn(conn)


# ── API ──────────────────────────────────────────────────────────────────────


def _empty_shape(symbol):
    return {
        "symbol": symbol,
        "currency": None,
        "price": None,
        "price_date": None,
        "ttm_dps": None,
        "ttm_yield": None,
        "ttm_yield_suspect": False,
        "last_ex_date": None,
        "last_amount": None,
        "next_ex_date": None,
        "next_amount": None,
        "years_paid": 0,
        "years_of_growth": 0,
        "annual_totals": [],
        "events": [],
    }


@router.get("/api/dividends")
def dividends(symbol: str = Query(...), response: Response = None):
    """Per-payment dividend history + computed TTM yield/streaks for a company.

    Display-only — feeds the company page Dividends tab. Returns the empty
    shape (not 404) for non-payers, the /api/valuation convention, so the UI
    doesn't need to special-case a missing company.
    """
    if response is not None:
        response.headers["Cache-Control"] = (
            "public, s-maxage=21600, stale-while-revalidate=86400"
        )

    events = query(
        "SELECT ex_date, amount, currency FROM dividend_events"
        " WHERE company_symbol = %s ORDER BY ex_date ASC",
        (symbol,),
    )
    if not events:
        return _empty_shape(symbol)

    currency = events[-1]["currency"]

    price_rows = query(
        "SELECT close, date FROM price_history WHERE symbol = %s ORDER BY date DESC LIMIT 1",
        (symbol,),
    )
    price = float(price_rows[0]["close"]) if price_rows else None
    price_date = str(price_rows[0]["date"]) if price_rows else None

    today = date.today()
    past_events = [e for e in events if e["ex_date"] <= today]
    future_events = [e for e in events if e["ex_date"] > today]

    ttm_start = today - timedelta(days=365)
    ttm_dps = sum(
        float(e["amount"]) for e in past_events if e["ex_date"] > ttm_start
    )
    ttm_dps = round(ttm_dps, 4) if ttm_dps else 0.0

    ttm_yield = (ttm_dps / price) if (price and ttm_dps) else None
    ttm_yield_suspect = bool(ttm_yield and ttm_yield > 0.25)
    if ttm_yield_suspect:
        ttm_yield = None

    last = past_events[-1] if past_events else None
    nxt = future_events[0] if future_events else None

    # Calendar-year totals, most recent ~15 years, current year flagged partial
    # so the chart can distinguish a part-year total from a completed one.
    annual = {}
    for e in events:
        y = e["ex_date"].year
        annual[y] = annual.get(y, 0.0) + float(e["amount"])
    years_sorted = sorted(annual.keys())[-15:]
    annual_totals = [
        {"year": y, "total": round(annual[y], 4), "partial": y >= today.year}
        for y in years_sorted
    ]

    # Consecutive complete calendar years (walking back from last year) with a
    # payment, and the sub-run of those where the total strictly rose year over
    # year. Dict-membership walk so a gap year (missed/cut dividend) stops the
    # streak instead of skipping over it.
    years_paid = 0
    y = today.year - 1
    while y in annual:
        years_paid += 1
        y -= 1

    years_of_growth = 0
    y = today.year - 1
    while (y in annual) and (y - 1 in annual) and annual[y] > annual[y - 1]:
        years_of_growth += 1
        y -= 1

    return {
        "symbol": symbol,
        "currency": currency,
        "price": price,
        "price_date": price_date,
        "ttm_dps": ttm_dps,
        "ttm_yield": round(ttm_yield, 4) if ttm_yield is not None else None,
        "ttm_yield_suspect": ttm_yield_suspect,
        "last_ex_date": str(last["ex_date"]) if last else None,
        "last_amount": float(last["amount"]) if last else None,
        "next_ex_date": str(nxt["ex_date"]) if nxt else None,
        "next_amount": float(nxt["amount"]) if nxt else None,
        "years_paid": years_paid,
        "years_of_growth": years_of_growth,
        "annual_totals": annual_totals,
        "events": [
            {"ex_date": str(e["ex_date"]), "amount": float(e["amount"])}
            for e in events[-12:][::-1]
        ],
    }
