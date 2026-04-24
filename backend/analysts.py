import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import APIRouter, BackgroundTasks
import psycopg2
import psycopg2.extras
import psycopg2.pool
import yfinance as yf
import pandas as pd
import time
import threading
from datetime import date
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/analysts", tags=["analysts"])

# ── DB (own pool) ─────────────────────────────────────────────────────────────

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
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **_DB_CONFIG)
    return _pool

def _query(sql, params=None):
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


# ── Pure parsing helpers ───────────────────────────────────────────────────────

def _derive_consensus(strong_buy, buy, hold, sell, strong_sell):
    """Return (consensus, buy_pct, total) from raw recommendation counts.

    Returns (None, None, None) if there are no analysts.
    """
    sb = strong_buy or 0
    b  = buy        or 0
    h  = hold       or 0
    s  = sell       or 0
    ss = strong_sell or 0
    total = sb + b + h + s + ss
    if total == 0:
        return None, None, None
    bullish  = sb + b
    bearish  = ss + s
    buy_pct  = round(bullish / total * 100, 1)
    if buy_pct >= 60:
        consensus = 'Buy'
    elif bearish / total >= 0.4:
        consensus = 'Sell'
    else:
        consensus = 'Hold'
    return consensus, buy_pct, total


def _parse_snapshot(symbol, recs, targets, earnings_est, rev_est, eps_rev, growth_est):
    """Parse raw yfinance data into a dict ready for DB upsert.

    All arguments may be None or empty DataFrames — returns NULL for missing fields.
    """
    # Consensus
    sb = b = h = s = ss = None
    if recs is not None and not recs.empty:
        r0 = recs.iloc[0]
        sb = int(r0.get('strongBuy', 0))
        b  = int(r0.get('buy',       0))
        h  = int(r0.get('hold',      0))
        s  = int(r0.get('sell',      0))
        ss = int(r0.get('strongSell', 0))
    consensus, buy_pct, total = _derive_consensus(sb, b, h, s, ss)

    # Price targets
    pt_mean = pt_high = pt_low = pt_median = current_price = upside_pct = None
    if targets:
        pt_mean    = targets.get('mean')
        pt_high    = targets.get('high')
        pt_low     = targets.get('low')
        pt_median  = targets.get('median')
        current_price = targets.get('current')
        if pt_mean and current_price and float(current_price) > 0:
            upside_pct = round((float(pt_mean) - float(current_price)) / float(current_price) * 100, 1)

    # EPS estimates (use 'avg' column, rows indexed by period)
    def _df_val(df, period, col):
        if df is None or df.empty:
            return None
        try:
            v = df.loc[period, col]
            return float(v) if pd.notna(v) else None
        except (KeyError, TypeError):
            return None

    eps_cq = _df_val(earnings_est, '0q',  'avg')
    eps_nq = _df_val(earnings_est, '+1q', 'avg')
    eps_cy = _df_val(earnings_est, '0y',  'avg')
    eps_ny = _df_val(earnings_est, '+1y', 'avg')

    rev_cy = _df_val(rev_est, '0y',  'avg')
    rev_ny = _df_val(rev_est, '+1y', 'avg')

    # EPS revisions (use current quarter '0q' as primary signal)
    rev_up_7  = _df_val(eps_rev, '0q', 'upLast7days')
    rev_dn_7  = _df_val(eps_rev, '0q', 'downLast7Days')
    rev_up_30 = _df_val(eps_rev, '0q', 'upLast30days')
    rev_dn_30 = _df_val(eps_rev, '0q', 'downLast30days')

    rev_up_7  = int(rev_up_7)  if rev_up_7  is not None else None
    rev_dn_7  = int(rev_dn_7)  if rev_dn_7  is not None else None
    rev_up_30 = int(rev_up_30) if rev_up_30 is not None else None
    rev_dn_30 = int(rev_dn_30) if rev_dn_30 is not None else None
    revision_score = (rev_up_30 - rev_dn_30) if (rev_up_30 is not None and rev_dn_30 is not None) else None

    # Growth estimates
    eps_g_cy = _df_val(growth_est, '0y',  'stockTrend')
    eps_g_ny = _df_val(growth_est, '+1y', 'stockTrend')

    return {
        'symbol':               symbol,
        'snapshot_date':        date.today().isoformat(),
        'strong_buy':           sb,
        'buy':                  b,
        'hold':                 h,
        'sell':                 s,
        'strong_sell':          ss,
        'total_analysts':       total,
        'consensus':            consensus,
        'buy_pct':              buy_pct,
        'price_target_mean':    pt_mean,
        'price_target_high':    pt_high,
        'price_target_low':     pt_low,
        'price_target_median':  pt_median,
        'current_price':        current_price,
        'upside_pct':           upside_pct,
        'eps_est_current_q':    eps_cq,
        'eps_est_next_q':       eps_nq,
        'eps_est_current_yr':   eps_cy,
        'eps_est_next_yr':      eps_ny,
        'rev_est_current_yr':   rev_cy,
        'rev_est_next_yr':      rev_ny,
        'revisions_up_7d':      rev_up_7,
        'revisions_down_7d':    rev_dn_7,
        'revisions_up_30d':     rev_up_30,
        'revisions_down_30d':   rev_dn_30,
        'revision_score':       revision_score,
        'eps_growth_current_yr': eps_g_cy,
        'eps_growth_next_yr':    eps_g_ny,
    }


# ── DB write ───────────────────────────────────────────────────────────────────

def _upsert_snapshot(row):
    """Upsert one analyst snapshot row. row is a dict from _parse_snapshot."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO analyst_snapshots (
                symbol, snapshot_date,
                strong_buy, buy, hold, sell, strong_sell, total_analysts,
                consensus, buy_pct,
                price_target_mean, price_target_high, price_target_low, price_target_median,
                current_price, upside_pct,
                eps_est_current_q, eps_est_next_q, eps_est_current_yr, eps_est_next_yr,
                rev_est_current_yr, rev_est_next_yr,
                revisions_up_7d, revisions_down_7d, revisions_up_30d, revisions_down_30d,
                revision_score, eps_growth_current_yr, eps_growth_next_yr
            ) VALUES (
                %(symbol)s, %(snapshot_date)s,
                %(strong_buy)s, %(buy)s, %(hold)s, %(sell)s, %(strong_sell)s, %(total_analysts)s,
                %(consensus)s, %(buy_pct)s,
                %(price_target_mean)s, %(price_target_high)s, %(price_target_low)s, %(price_target_median)s,
                %(current_price)s, %(upside_pct)s,
                %(eps_est_current_q)s, %(eps_est_next_q)s, %(eps_est_current_yr)s, %(eps_est_next_yr)s,
                %(rev_est_current_yr)s, %(rev_est_next_yr)s,
                %(revisions_up_7d)s, %(revisions_down_7d)s, %(revisions_up_30d)s, %(revisions_down_30d)s,
                %(revision_score)s, %(eps_growth_current_yr)s, %(eps_growth_next_yr)s
            )
            ON CONFLICT (symbol, snapshot_date) DO UPDATE SET
                strong_buy = EXCLUDED.strong_buy, buy = EXCLUDED.buy,
                hold = EXCLUDED.hold, sell = EXCLUDED.sell, strong_sell = EXCLUDED.strong_sell,
                total_analysts = EXCLUDED.total_analysts, consensus = EXCLUDED.consensus,
                buy_pct = EXCLUDED.buy_pct,
                price_target_mean = EXCLUDED.price_target_mean,
                price_target_high = EXCLUDED.price_target_high,
                price_target_low  = EXCLUDED.price_target_low,
                price_target_median = EXCLUDED.price_target_median,
                current_price = EXCLUDED.current_price, upside_pct = EXCLUDED.upside_pct,
                eps_est_current_q = EXCLUDED.eps_est_current_q,
                eps_est_next_q = EXCLUDED.eps_est_next_q,
                eps_est_current_yr = EXCLUDED.eps_est_current_yr,
                eps_est_next_yr = EXCLUDED.eps_est_next_yr,
                rev_est_current_yr = EXCLUDED.rev_est_current_yr,
                rev_est_next_yr = EXCLUDED.rev_est_next_yr,
                revisions_up_7d = EXCLUDED.revisions_up_7d,
                revisions_down_7d = EXCLUDED.revisions_down_7d,
                revisions_up_30d = EXCLUDED.revisions_up_30d,
                revisions_down_30d = EXCLUDED.revisions_down_30d,
                revision_score = EXCLUDED.revision_score,
                eps_growth_current_yr = EXCLUDED.eps_growth_current_yr,
                eps_growth_next_yr = EXCLUDED.eps_growth_next_yr,
                fetched_at = NOW()
        """, row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Refresh logic (shared by script and endpoint) ─────────────────────────────

_RATE_LIMIT_PHRASES = ('429', 'too many requests', 'rate limit')

def _fetch_one(symbol, max_retries=3):
    """Fetch all yfinance analyst data for one symbol. Returns parsed row dict or None.

    Retries up to max_retries times with exponential backoff on rate-limit errors.
    """
    delay = 30  # initial backoff in seconds
    for attempt in range(max_retries + 1):
        try:
            t = yf.Ticker(symbol)
            row = _parse_snapshot(
                symbol,
                t.recommendations,
                t.analyst_price_targets,
                t.earnings_estimate,
                t.revenue_estimate,
                t.eps_revisions,
                t.growth_estimates,
            )
            return row
        except Exception as e:
            msg = str(e).lower()
            is_rate_limit = any(p in msg for p in _RATE_LIMIT_PHRASES)
            if is_rate_limit and attempt < max_retries:
                print(f"[analysts] rate-limited on {symbol}, retry {attempt + 1}/{max_retries} in {delay}s")
                time.sleep(delay)
                delay *= 2  # exponential backoff: 5s → 10s → 20s
            else:
                if is_rate_limit:
                    print(f"[analysts] skip {symbol}: rate limit, max retries exceeded")
                else:
                    print(f"[analysts] skip {symbol}: {e}")
                return None

_LOG_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "analysts_refresh.log")


def _append_log(line: str) -> None:
    """Append a line to the refresh log. Swallows IO errors — logging never blocks the job."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception as e:
        print(f"[analysts] log write failed: {e}")


def _run_refresh():
    """Fetch analyst data for all symbols and upsert. Called by script and refresh endpoint."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    t0 = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))
    symbols = [r['symbol'] for r in _query("SELECT symbol FROM company_metadata ORDER BY symbol")]
    total = len(symbols)
    processed = skipped = errors = 0
    # Sequential (1 worker) + 1.5s delay — Yahoo rate-limits concurrent bursts
    with ThreadPoolExecutor(max_workers=1) as ex:
        futures = {ex.submit(_fetch_one, sym): sym for sym in symbols}
        for i, fut in enumerate(as_completed(futures)):
            sym = futures[fut]
            try:
                row = fut.result()
                if row is None or row.get('total_analysts') is None:
                    skipped += 1
                else:
                    _upsert_snapshot(row)
                    processed += 1
            except Exception as e:
                errors += 1
                print(f"[analysts] error {sym}: {e}")
            # 1.5s between each request — keeps well under Yahoo's rate limit
            time.sleep(1.5)

    elapsed = round(time.time() - t0, 1)
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[analysts] refresh done — processed={processed} skipped={skipped} errors={errors}")
    _append_log(
        f"{finished_at}  started={started_at}  elapsed={elapsed}s  "
        f"total={total}  updated={processed}  skipped={skipped}  errors={errors}"
    )
    return {
        'processed':   processed,
        'skipped':     skipped,
        'errors':      errors,
        'total':       total,
        'elapsed_s':   elapsed,
        'started_at':  started_at,
        'finished_at': finished_at,
    }


@router.get("/refresh-log")
def get_refresh_log(lines: int = 20):
    """Return the last N lines of the refresh log (oldest → newest)."""
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            return {"lines": f.read().splitlines()[-max(1, min(lines, 500)):]}
    except FileNotFoundError:
        return {"lines": []}


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.get("/latest")
def get_latest():
    """Latest analyst snapshot for every stock, with company metadata."""
    return _query("""
        SELECT DISTINCT ON (s.symbol)
            s.symbol, s.snapshot_date, s.consensus, s.buy_pct, s.total_analysts,
            s.price_target_mean, s.price_target_high, s.price_target_low, s.price_target_median,
            s.current_price, s.upside_pct, s.revision_score,
            s.eps_est_current_yr, s.eps_est_next_yr, s.rev_est_current_yr, s.rev_est_next_yr,
            s.eps_growth_current_yr, s.eps_growth_next_yr,
            m.name, m.sector, m.ftse_index
        FROM analyst_snapshots s
        LEFT JOIN company_metadata m ON m.symbol = s.symbol
        ORDER BY s.symbol, s.snapshot_date DESC
    """)

@router.get("/changes")
def get_changes():
    """Stocks where consensus changed, buy_pct shifted >5pts, or upside_pct shifted >5pts since prior snapshot."""
    return _query("""
        WITH ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY snapshot_date DESC) AS rn
            FROM analyst_snapshots
        ),
        cur  AS (SELECT * FROM ranked WHERE rn = 1),
        prev AS (SELECT * FROM ranked WHERE rn = 2)
        SELECT
            cur.symbol,
            cur.snapshot_date,
            cur.consensus,
            prev.consensus   AS prev_consensus,
            cur.upside_pct,
            prev.upside_pct  AS prev_upside,
            cur.buy_pct,
            prev.buy_pct     AS prev_buy_pct,
            cur.revision_score
        FROM cur
        JOIN prev ON prev.symbol = cur.symbol
        WHERE cur.consensus IS DISTINCT FROM prev.consensus
           OR ABS(COALESCE(cur.upside_pct,0) - COALESCE(prev.upside_pct,0)) > 5
           OR ABS(COALESCE(cur.buy_pct,0)    - COALESCE(prev.buy_pct,0))    > 5
        ORDER BY cur.snapshot_date DESC
    """)

@router.post("/refresh")
def refresh(background_tasks: BackgroundTasks):
    """Trigger a full analyst data refresh in the background."""
    background_tasks.add_task(_run_refresh)
    return {'status': 'refresh started'}

@router.get("/{symbol}")
def get_history(symbol: str):
    """Full snapshot history for one stock, oldest first."""
    from fastapi import HTTPException
    rows = _query("""
        SELECT snapshot_date, consensus, buy_pct, total_analysts,
               strong_buy, buy, hold, sell, strong_sell,
               price_target_mean, price_target_high, price_target_low,
               price_target_median, current_price, upside_pct,
               eps_est_current_q, eps_est_next_q, eps_est_current_yr, eps_est_next_yr,
               rev_est_current_yr, rev_est_next_yr,
               revisions_up_7d, revisions_down_7d, revisions_up_30d, revisions_down_30d,
               revision_score, eps_growth_current_yr, eps_growth_next_yr
        FROM analyst_snapshots
        WHERE symbol = %s
        ORDER BY snapshot_date ASC
    """, (symbol,))
    if not rows:
        from fastapi import HTTPException
        raise HTTPException(404, "No analyst data for this symbol")
    return rows
