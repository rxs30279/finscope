# Analyst Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add daily analyst consensus snapshots from Yahoo Finance to the stock screener, surfaced in the screener table, a new Analysts tab on stock detail, and a dedicated Analyst Monitor page.

**Architecture:** A standalone `refresh_analysts.py` script fetches yfinance data in parallel for all stocks, upserts into `analyst_snapshots` (one row per stock per day), and is called nightly by Windows Task Scheduler. A new `analysts.py` FastAPI router serves the data. The frontend adds an `AnalystTab` component, an `AnalystMonitorTab` page component, and wires analyst columns into the existing screener.

**Tech Stack:** Python 3.11, FastAPI, psycopg2, yfinance (already installed), React 18, recharts (already used), PostgreSQL.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/analysts.py` | Create | FastAPI router + DB helpers + pure parsing functions |
| `backend/refresh_analysts.py` | Create | Standalone nightly refresh script |
| `backend/tests/test_analysts.py` | Create | Tests for analysts.py endpoints and parsing |
| `backend/main.py` | Modify | Register analysts router; add analyst JOIN + filters to screener |
| `frontend/src/components/AnalystTab.js` | Create | Analysts tab panel for stock detail view |
| `frontend/src/components/AnalystMonitorTab.js` | Create | Dedicated Analyst Monitor page |
| `frontend/src/App.js` | Modify | Import new components; wire nav entry; add screener columns/filters |

---

## Task 1: DB Migration

**Files:**
- Run SQL against the production database

- [ ] **Step 1: Create the analyst_snapshots table**

Connect to your PostgreSQL database and run:

```sql
CREATE TABLE analyst_snapshots (
    id                       SERIAL PRIMARY KEY,
    symbol                   VARCHAR     NOT NULL,
    snapshot_date            DATE        NOT NULL,

    strong_buy               INT,
    buy                      INT,
    hold                     INT,
    sell                     INT,
    strong_sell              INT,
    total_analysts           INT,
    consensus                VARCHAR,
    buy_pct                  NUMERIC,

    price_target_mean        NUMERIC,
    price_target_high        NUMERIC,
    price_target_low         NUMERIC,
    price_target_median      NUMERIC,
    current_price            NUMERIC,
    upside_pct               NUMERIC,

    eps_est_current_q        NUMERIC,
    eps_est_next_q           NUMERIC,
    eps_est_current_yr       NUMERIC,
    eps_est_next_yr          NUMERIC,

    rev_est_current_yr       NUMERIC,
    rev_est_next_yr          NUMERIC,

    revisions_up_7d          INT,
    revisions_down_7d        INT,
    revisions_up_30d         INT,
    revisions_down_30d       INT,
    revision_score           INT,

    eps_growth_current_yr    NUMERIC,
    eps_growth_next_yr       NUMERIC,

    fetched_at               TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (symbol, snapshot_date)
);

CREATE INDEX ON analyst_snapshots (symbol, snapshot_date DESC);
```

- [ ] **Step 2: Verify table exists**

```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'analyst_snapshots'
ORDER BY ordinal_position;
```

Expected: 30 rows listing all columns.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: add analyst_snapshots table migration"
```

---

## Task 2: Core Parsing Logic

**Files:**
- Create: `backend/analysts.py`
- Create: `backend/tests/test_analysts.py`

- [ ] **Step 1: Write failing tests for _derive_consensus**

Create `backend/tests/test_analysts.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from analysts import _derive_consensus, _parse_snapshot


# ── _derive_consensus ──────────────────────────────────────────────────────────

def test_derive_consensus_buy_when_buy_pct_ge_60():
    consensus, buy_pct, total = _derive_consensus(10, 8, 3, 1, 0)
    # strong_buy=10 buy=8 → bullish=18, total=22 → buy_pct=81.8%
    assert consensus == 'Buy'
    assert total == 22
    assert buy_pct >= 60

def test_derive_consensus_sell_when_bearish_ge_40():
    consensus, buy_pct, total = _derive_consensus(1, 2, 2, 5, 5)
    # bearish=10/15=66.7%
    assert consensus == 'Sell'

def test_derive_consensus_hold_in_middle():
    consensus, buy_pct, total = _derive_consensus(2, 4, 8, 2, 0)
    # buy_pct=37.5%, sell_pct=12.5%
    assert consensus == 'Hold'

def test_derive_consensus_none_when_no_analysts():
    consensus, buy_pct, total = _derive_consensus(0, 0, 0, 0, 0)
    assert consensus is None
    assert buy_pct is None
    assert total is None

def test_derive_consensus_none_inputs_treated_as_zero():
    consensus, buy_pct, total = _derive_consensus(None, None, None, None, None)
    assert consensus is None
    assert total is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_analysts.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — analysts.py doesn't exist yet.

- [ ] **Step 3: Create analysts.py with _derive_consensus**

Create `backend/analysts.py`:

```python
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
```

- [ ] **Step 4: Run tests to confirm _derive_consensus passes**

```bash
cd backend && python -m pytest tests/test_analysts.py::test_derive_consensus_buy_when_buy_pct_ge_60 tests/test_analysts.py::test_derive_consensus_sell_when_bearish_ge_40 tests/test_analysts.py::test_derive_consensus_hold_in_middle tests/test_analysts.py::test_derive_consensus_none_when_no_analysts tests/test_analysts.py::test_derive_consensus_none_inputs_treated_as_zero -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Write failing tests for _parse_snapshot**

Append to `backend/tests/test_analysts.py`:

```python
# ── _parse_snapshot ────────────────────────────────────────────────────────────

def _make_recs(sb=6, b=11, h=4, s=1, ss=0):
    return pd.DataFrame([{
        'period': '0m', 'strongBuy': sb, 'buy': b,
        'hold': h, 'sell': s, 'strongSell': ss
    }])

def _make_targets(mean=1600, high=2000, low=1200, median=1650, current=1400):
    return {'mean': mean, 'high': high, 'low': low, 'median': median, 'current': current}

def _make_earnings_est():
    return pd.DataFrame({
        'avg':  [1.5, 1.8, 6.2, 7.1]
    }, index=pd.Index(['0q', '+1q', '0y', '+1y'], name='period'))

def _make_rev_est():
    return pd.DataFrame({
        'avg': [5e9, 5.5e9]
    }, index=pd.Index(['0y', '+1y'], name='period'))

def _make_eps_rev():
    return pd.DataFrame({
        'upLast7days': [2, 1, 0, 0],
        'upLast30days': [4, 3, 2, 1],
        'downLast30days': [1, 2, 3, 2],
        'downLast7Days': [0, 0, 1, 0],
    }, index=pd.Index(['0q', '+1q', '0y', '+1y'], name='period'))

def _make_growth():
    return pd.DataFrame({
        'stockTrend': [0.12, 0.10, 0.15, 0.09]
    }, index=pd.Index(['0q', '+1q', '0y', '+1y'], name='period'))

def test_parse_snapshot_consensus_fields():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['symbol'] == 'AZN.L'
    assert row['strong_buy'] == 6
    assert row['buy'] == 11
    assert row['total_analysts'] == 22
    assert row['consensus'] == 'Buy'        # (6+11)/22 = 77% ≥ 60%
    assert row['buy_pct'] == 77.3

def test_parse_snapshot_price_targets():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['price_target_mean'] == 1600
    assert row['current_price'] == 1400
    assert row['upside_pct'] == round((1600 - 1400) / 1400 * 100, 1)

def test_parse_snapshot_eps_estimates():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['eps_est_current_q']  == 1.5
    assert row['eps_est_next_q']     == 1.8
    assert row['eps_est_current_yr'] == 6.2
    assert row['eps_est_next_yr']    == 7.1

def test_parse_snapshot_revisions():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['revisions_up_30d']   == 4
    assert row['revisions_down_30d'] == 1
    assert row['revision_score']     == 3   # 4 - 1

def test_parse_snapshot_none_recs_gives_null_consensus():
    row = _parse_snapshot('AZN.L', None, None, None, None, None, None)
    assert row['consensus'] is None
    assert row['total_analysts'] is None
    assert row['upside_pct'] is None
```

- [ ] **Step 6: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_analysts.py::test_parse_snapshot_consensus_fields -v
```

Expected: `ImportError: cannot import name '_parse_snapshot' from 'analysts'`

- [ ] **Step 7: Implement _parse_snapshot in analysts.py**

Append to `backend/analysts.py` (after `_derive_consensus`):

```python
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
```

- [ ] **Step 8: Run all parsing tests**

```bash
cd backend && python -m pytest tests/test_analysts.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/analysts.py backend/tests/test_analysts.py
git commit -m "feat: add analyst parsing logic (_derive_consensus, _parse_snapshot)"
```

---

## Task 3: DB Upsert + API Endpoints

**Files:**
- Modify: `backend/analysts.py`
- Modify: `backend/tests/test_analysts.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing endpoint tests**

Append to `backend/tests/test_analysts.py`:

```python
# ── API endpoint tests ─────────────────────────────────────────────────────────
# conftest.py already provides `client` via TestClient(app)

def test_get_analyst_history_returns_list(client):
    rows = [
        {'symbol': 'AZN.L', 'snapshot_date': '2026-04-01', 'consensus': 'Buy', 'buy_pct': 77.3},
        {'symbol': 'AZN.L', 'snapshot_date': '2026-04-02', 'consensus': 'Buy', 'buy_pct': 79.0},
    ]
    with patch('analysts._query', return_value=rows):
        r = client.get('/api/analysts/AZN.L')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]['consensus'] == 'Buy'

def test_get_analyst_history_404_when_no_data(client):
    with patch('analysts._query', return_value=[]):
        r = client.get('/api/analysts/UNKNOWN.L')
    assert r.status_code == 404

def test_get_analyst_latest_returns_list(client):
    rows = [
        {'symbol': 'AZN.L', 'snapshot_date': '2026-04-07', 'consensus': 'Buy',  'buy_pct': 77.3},
        {'symbol': 'SHEL.L','snapshot_date': '2026-04-07', 'consensus': 'Hold', 'buy_pct': 45.0},
    ]
    with patch('analysts._query', return_value=rows):
        r = client.get('/api/analysts/latest')
    assert r.status_code == 200
    assert len(r.json()) == 2

def test_get_analyst_changes_returns_list(client):
    rows = [
        {'symbol': 'AZN.L', 'prev_consensus': 'Hold', 'consensus': 'Buy',
         'prev_upside': 5.0, 'upside_pct': 22.0, 'snapshot_date': '2026-04-07'}
    ]
    with patch('analysts._query', return_value=rows):
        r = client.get('/api/analysts/changes')
    assert r.status_code == 200
    assert r.json()[0]['symbol'] == 'AZN.L'

def test_refresh_endpoint_returns_started(client):
    with patch('analysts._run_refresh') as mock_refresh:
        r = client.post('/api/analysts/refresh')
    assert r.status_code == 200
    assert r.json() == {'status': 'refresh started'}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_analysts.py::test_get_analyst_history_returns_list -v
```

Expected: FAIL — endpoints not defined yet.

- [ ] **Step 3: Implement _upsert_snapshot and all endpoints in analysts.py**

Append to `backend/analysts.py`:

```python
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

def _fetch_one(symbol):
    """Fetch all yfinance analyst data for one symbol. Returns parsed row dict or None."""
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
        print(f"[analysts] skip {symbol}: {e}")
        return None

def _run_refresh():
    """Fetch analyst data for all symbols and upsert. Called by script and refresh endpoint."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    symbols = [r['symbol'] for r in _query("SELECT symbol FROM company_metadata ORDER BY symbol")]
    processed = skipped = errors = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
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
            # Rate-limit: sleep 0.5s every 10 stocks
            if (i + 1) % 10 == 0:
                time.sleep(0.5)
    print(f"[analysts] refresh done — processed={processed} skipped={skipped} errors={errors}")
    return {'processed': processed, 'skipped': skipped, 'errors': errors}


# ── API endpoints ──────────────────────────────────────────────────────────────

@router.get("/latest")
def get_latest():
    """Latest analyst snapshot for every stock."""
    return _query("""
        SELECT DISTINCT ON (symbol)
            symbol, snapshot_date, consensus, buy_pct, total_analysts,
            price_target_mean, price_target_high, price_target_low, price_target_median,
            current_price, upside_pct, revision_score,
            eps_est_current_yr, eps_est_next_yr, rev_est_current_yr, rev_est_next_yr,
            eps_growth_current_yr, eps_growth_next_yr
        FROM analyst_snapshots
        ORDER BY symbol, snapshot_date DESC
    """)

@router.get("/changes")
def get_changes():
    """Stocks where consensus changed or upside_pct shifted >5pts since prior snapshot."""
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
            cur.revision_score
        FROM cur
        JOIN prev ON prev.symbol = cur.symbol
        WHERE cur.consensus IS DISTINCT FROM prev.consensus
           OR ABS(COALESCE(cur.upside_pct,0) - COALESCE(prev.upside_pct,0)) > 5
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
```

- [ ] **Step 4: Register analysts router in main.py**

Open `backend/main.py`. Find the existing router imports and add analysts:

```python
from analysts import router as analysts_router
```

Find the `app.include_router` lines and add:

```python
app.include_router(analysts_router)
```

- [ ] **Step 5: Run endpoint tests**

```bash
cd backend && python -m pytest tests/test_analysts.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/analysts.py backend/tests/test_analysts.py backend/main.py
git commit -m "feat: add analysts.py router with endpoints and DB upsert"
```

---

## Task 4: Refresh Script

**Files:**
- Create: `backend/refresh_analysts.py`

- [ ] **Step 1: Create the standalone refresh script**

Create `backend/refresh_analysts.py`:

```python
"""Standalone nightly refresh script for analyst data.

Run directly:    python refresh_analysts.py
Or scheduled:    Windows Task Scheduler → python C:\\...\\refresh_analysts.py

Uses the same _run_refresh() logic as the POST /api/analysts/refresh endpoint.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from analysts import _run_refresh
import time

if __name__ == '__main__':
    print(f"[analysts] starting refresh at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    t0 = time.time()
    result = _run_refresh()
    elapsed = round(time.time() - t0, 1)
    print(f"[analysts] complete in {elapsed}s — {result}")
```

- [ ] **Step 2: Smoke-test against a single stock**

This hits Yahoo Finance's servers — run it manually:

```bash
cd backend && python -c "
from dotenv import load_dotenv; load_dotenv()
from analysts import _fetch_one, _upsert_snapshot
row = _fetch_one('AZN.L')
print('parsed row:', {k:v for k,v in row.items() if v is not None})
if row.get('total_analysts'):
    _upsert_snapshot(row)
    print('upserted OK')
else:
    print('no analyst data (expected for some stocks)')
"
```

Expected: prints a dict with `consensus`, `buy_pct`, `price_target_mean` populated (or "no analyst data" which is also valid for some smaller stocks).

- [ ] **Step 3: Configure Windows Task Scheduler**

Open Task Scheduler → Create Basic Task:
- Name: `Stock Screener — Analyst Refresh`
- Trigger: Daily at 02:00
- Action: Start a program
  - Program: `C:\Users\richa\AppData\Local\Programs\Python\Python311\python.exe`
  - Arguments: `C:\Users\richa\Documents\WebProjects\UK_stocks\stock_screener\backend\refresh_analysts.py`
  - Start in: `C:\Users\richa\Documents\WebProjects\UK_stocks\stock_screener\backend`

- [ ] **Step 4: Commit**

```bash
git add backend/refresh_analysts.py
git commit -m "feat: add refresh_analysts.py standalone nightly script"
```

---

## Task 5: Screener Analyst JOIN

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/tests/test_analysts.py`

- [ ] **Step 1: Write failing test for screener analyst columns**

Append to `backend/tests/test_analysts.py`:

```python
# ── Screener analyst integration ───────────────────────────────────────────────

def test_screener_includes_analyst_columns(client):
    screener_row = {
        'symbol': 'AZN.L', 'name': 'AstraZeneca', 'sector': 'Health Care',
        'country': 'GB', 'exchange': 'LSE', 'ftse_index': 'FTSE 100',
        'financial_currency': 'GBP', 'market_cap': 200e9, 'revenue': 40e9,
        'net_income': 5e9, 'price_to_earnings': 18.0, 'price_to_book': 4.0,
        'price_to_sales': 3.0, 'roe': 0.25, 'roa': 0.08, 'roic': 0.12,
        'roce': 0.15, 'gross_margin': 0.72, 'operating_margin': 0.28,
        'net_income_margin': 0.14, 'revenue_growth': 0.10, 'eps_diluted_growth': 0.12,
        'fcf_growth': 0.08, 'debt_to_equity': 0.8, 'current_ratio': 1.5,
        'fcf': 6e9, 'ebitda': 10e9, 'revenue_cagr_10': 0.07, 'eps_cagr_10': 0.09,
        'period_end_date': '2025-12-31', 'fcf_margin': 0.15,
        'gross_margin_median': 0.70, 'operating_margin_median': 0.26,
        'net_margin_median': 0.13, 'roe_median': 0.22, 'roic_median': 0.11,
        # analyst fields joined from analyst_snapshots
        'consensus': 'Buy', 'buy_pct': 77.3, 'upside_pct': 14.3,
        'total_analysts': 22, 'revision_score': 3,
    }
    with patch('main.query', return_value=[screener_row]), \
         patch('prices._attach_momentum', side_effect=lambda r: r), \
         patch('main._attach_piotroski', side_effect=lambda r: r), \
         patch('main._attach_risk_score', side_effect=lambda r: r):
        r = client.get('/api/screener')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]['consensus'] == 'Buy'
    assert data[0]['upside_pct'] == 14.3

def test_screener_filter_by_consensus(client):
    with patch('main.query', return_value=[]) as mock_q, \
         patch('prices._attach_momentum', side_effect=lambda r: r), \
         patch('main._attach_piotroski', side_effect=lambda r: r), \
         patch('main._attach_risk_score', side_effect=lambda r: r):
        r = client.get('/api/screener?consensus=Buy')
    assert r.status_code == 200
    # Verify the SQL was called with consensus filter param
    call_args = mock_q.call_args
    assert 'Buy' in call_args[0][1]   # params tuple contains 'Buy'
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_analysts.py::test_screener_includes_analyst_columns -v
```

Expected: FAIL — screener doesn't join analyst data yet.

- [ ] **Step 3: Update /api/screener in main.py**

In `backend/main.py`, find the `screener` function. Update the signature to add two new params:

```python
@app.get("/api/screener")
def screener(
    sector: Optional[str]=None,
    country: Optional[str]=None,
    ftse_index: Optional[str]=None,
    min_market_cap: Optional[float]=None,
    max_pe: Optional[float]=None,
    min_roe: Optional[float]=None,
    min_revenue_growth: Optional[float]=None,
    consensus: Optional[str]=None,
    min_upside_pct: Optional[float]=None,
    limit: int=100
):
```

In the `wheres`/`params` block, add after the existing filters:

```python
    if consensus:      wheres.append("a.consensus = %s");    params.append(consensus)
    if min_upside_pct: wheres.append("a.upside_pct >= %s");  params.append(min_upside_pct)
```

Replace the `sql` definition. Find the line:

```python
    sql = f"""
        SELECT m.symbol, m.name, ...
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY t.market_cap DESC NULLS LAST
        LIMIT %s
    """
```

And replace it with (adding the analyst LEFT JOIN and new SELECT columns):

```python
    sql = f"""
        SELECT m.symbol, m.name, m.sector, m.country, m.exchange, m.ftse_index, m.financial_currency,
               t.market_cap, t.revenue, t.net_income,
               CASE WHEN t.price_to_earnings > 999 THEN NULL ELSE t.price_to_earnings END as price_to_earnings,
               t.price_to_book, t.price_to_sales, t.roe, t.roa, t.roic, t.roce,
               t.gross_margin, t.operating_margin, t.net_income_margin,
               t.revenue_growth, t.eps_diluted_growth, t.fcf_growth,
               t.debt_to_equity, t.current_ratio, t.fcf, t.ebitda,
               t.revenue_cagr_10, t.eps_cagr_10, t.period_end_date,
               t.fcf_margin,
               t.gross_margin_median, t.operating_margin_median,
               t.net_margin_median, t.roe_median, t.roic_median,
               a.consensus, a.buy_pct, a.upside_pct, a.total_analysts, a.revision_score
        FROM ttm_financials t
        JOIN company_metadata m ON m.symbol = t.company_symbol
        LEFT JOIN (
            SELECT DISTINCT ON (symbol)
                symbol, consensus, buy_pct, upside_pct, total_analysts, revision_score
            FROM analyst_snapshots
            ORDER BY symbol, snapshot_date DESC
        ) a ON a.symbol = m.symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY t.market_cap DESC NULLS LAST
        LIMIT %s
    """
```

- [ ] **Step 4: Run screener tests**

```bash
cd backend && python -m pytest tests/test_analysts.py::test_screener_includes_analyst_columns tests/test_analysts.py::test_screener_filter_by_consensus -v
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite to confirm nothing broken**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_analysts.py
git commit -m "feat: add analyst JOIN and filters to screener endpoint"
```

---

## Task 6: AnalystTab Component (Stock Detail)

**Files:**
- Create: `frontend/src/components/AnalystTab.js`

- [ ] **Step 1: Create AnalystTab.js**

Create `frontend/src/components/AnalystTab.js`:

```javascript
import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts';
import { API, fmt } from '../utils';

const CONSENSUS_COLORS = {
  Buy:  { bg: '#0d3320', color: '#10b981' },
  Hold: { bg: '#1a1400', color: '#f59e0b' },
  Sell: { bg: '#2a0d0d', color: '#ef4444' },
};

function ConsensusBadge({ value }) {
  if (!value) return <span style={{ color: '#444' }}>—</span>;
  const c = CONSENSUS_COLORS[value] || { bg: '#1a1a1a', color: '#94a3b8' };
  return (
    <span style={{
      ...c, padding: '3px 10px', borderRadius: 2,
      fontSize: 11, fontFamily: 'monospace', fontWeight: 700
    }}>
      {value}
    </span>
  );
}

function ConsensusBar({ row }) {
  const total = row.total_analysts || 0;
  if (!total) return <div style={{ color: '#444', fontSize: 12 }}>No consensus data</div>;
  const segments = [
    { key: 'strong_buy',   label: 'Strong Buy',   color: '#059669' },
    { key: 'buy',          label: 'Buy',           color: '#10b981' },
    { key: 'hold',         label: 'Hold',          color: '#f59e0b' },
    { key: 'sell',         label: 'Sell',          color: '#ef4444' },
    { key: 'strong_sell',  label: 'Strong Sell',   color: '#b91c1c' },
  ];
  return (
    <div>
      <div style={{ display: 'flex', height: 24, borderRadius: 3, overflow: 'hidden', marginBottom: 10 }}>
        {segments.map(({ key, color }) => {
          const pct = total ? ((row[key] || 0) / total * 100) : 0;
          if (pct === 0) return null;
          return (
            <div key={key} style={{ width: `${pct}%`, background: color, transition: 'width 0.3s' }} />
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {segments.map(({ key, label, color }) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontFamily: 'monospace' }}>
            <div style={{ width: 8, height: 8, borderRadius: 1, background: color }} />
            <span style={{ color: '#666' }}>{label}</span>
            <span style={{ color: '#e5e5e5', fontWeight: 700 }}>{row[key] || 0}</span>
          </div>
        ))}
        <span style={{ color: '#444', fontSize: 11 }}>({total} analysts)</span>
      </div>
    </div>
  );
}

function PriceTargetRange({ row }) {
  const { price_target_low: low, price_target_high: high,
          price_target_mean: mean, price_target_median: median,
          current_price: current } = row;
  if (!low || !high || !current) return <div style={{ color: '#444', fontSize: 12 }}>No price target data</div>;
  const range = high - low;
  if (range <= 0) return null;
  const pct  = (v) => Math.max(0, Math.min(100, ((v - low) / range * 100)));
  const markers = [
    { val: current, label: 'Current', color: '#6366f1' },
    { val: mean,    label: 'Mean',    color: '#f97316' },
    { val: median,  label: 'Median',  color: '#a855f7' },
  ].filter(m => m.val);

  return (
    <div>
      <div style={{ position: 'relative', height: 28, margin: '16px 0 32px' }}>
        {/* Track */}
        <div style={{
          position: 'absolute', top: '50%', left: 0, right: 0,
          height: 4, background: '#2a2a2a', transform: 'translateY(-50%)', borderRadius: 2
        }} />
        {/* Buy zone (low → mean) */}
        <div style={{
          position: 'absolute', top: '50%',
          left: `${pct(low)}%`, width: `${pct(mean) - pct(low)}%`,
          height: 4, background: '#10b98144', transform: 'translateY(-50%)'
        }} />
        {/* Markers */}
        {markers.map(({ val, label, color }) => (
          <div key={label} style={{
            position: 'absolute', top: '50%', left: `${pct(val)}%`,
            transform: 'translate(-50%, -50%)',
          }}>
            <div style={{ width: 12, height: 12, borderRadius: '50%', background: color, border: '2px solid #0a0a0a' }} />
            <div style={{
              position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)',
              fontSize: 9, color, fontFamily: 'monospace', whiteSpace: 'nowrap'
            }}>
              {label}<br />{val?.toFixed(0)}p
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#444', fontFamily: 'monospace' }}>
        <span>Low: {low?.toFixed(0)}p</span>
        {row.upside_pct != null && (
          <span style={{ color: row.upside_pct >= 0 ? '#10b981' : '#ef4444', fontWeight: 700 }}>
            {row.upside_pct >= 0 ? '+' : ''}{row.upside_pct?.toFixed(1)}% to mean target
          </span>
        )}
        <span>High: {high?.toFixed(0)}p</span>
      </div>
    </div>
  );
}

export default function AnalystTab({ symbol }) {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/analysts/${encodeURIComponent(symbol)}`)
      .then(r => r.ok ? r.json() : [])
      .then(d => { setHistory(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>Loading analyst data…</div>;
  if (!history.length) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>No analyst data available for {symbol}</div>;

  // Latest snapshot is last in array (ORDER BY ASC)
  const latest = history[history.length - 1];
  const trendData = history.map(r => ({
    date: r.snapshot_date,
    buy_pct: r.buy_pct,
  }));

  const cardStyle = {
    background: '#141414', border: '1px solid #2a2a2a',
    borderRadius: 3, padding: 20, marginBottom: 16
  };
  const titleStyle = {
    fontSize: 10, color: '#666', textTransform: 'uppercase',
    letterSpacing: 1, fontFamily: 'monospace', marginBottom: 14, marginTop: 0
  };

  return (
    <div>
      {/* Header row: consensus label + key numbers */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
        <ConsensusBadge value={latest.consensus} />
        {latest.buy_pct != null && (
          <span style={{ color: '#94a3b8', fontSize: 12, fontFamily: 'monospace' }}>
            {latest.buy_pct?.toFixed(1)}% bullish
          </span>
        )}
        {latest.total_analysts != null && (
          <span style={{ color: '#555', fontSize: 12, fontFamily: 'monospace' }}>
            {latest.total_analysts} analysts
          </span>
        )}
      </div>

      {/* Panel 1: Consensus bar */}
      <div style={cardStyle}>
        <p style={titleStyle}>Analyst Consensus</p>
        <ConsensusBar row={latest} />
      </div>

      {/* Panel 2: Price target range */}
      <div style={cardStyle}>
        <p style={titleStyle}>Price Target Range</p>
        <PriceTargetRange row={latest} />
      </div>

      {/* Panel 3: Consensus trend (only if ≥2 snapshots) */}
      {trendData.length >= 2 && (
        <div style={cardStyle}>
          <p style={titleStyle}>Consensus Trend — % Bullish</p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={trendData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#555', fontFamily: 'monospace' }} unit="%" />
              <Tooltip
                formatter={v => [`${v?.toFixed(1)}%`, 'Buy%']}
                contentStyle={{ background: '#141414', border: '1px solid #2a2a2a', borderRadius: 2, fontFamily: 'monospace', fontSize: 11 }}
              />
              <Line type="monotone" dataKey="buy_pct" stroke="#10b981" strokeWidth={2} dot={{ r: 3 }} name="Buy%" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Panel 4: Estimates & revisions */}
      <div style={cardStyle}>
        <p style={titleStyle}>Estimates & Revisions</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          <div>
            <div style={{ fontSize: 10, color: '#555', marginBottom: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: 1 }}>EPS Estimates</div>
            {[
              ['Current Year', latest.eps_est_current_yr],
              ['Next Year',    latest.eps_est_next_yr],
              ['Current Q',    latest.eps_est_current_q],
              ['Next Q',       latest.eps_est_next_q],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace' }}>
                <span style={{ color: '#666' }}>{label}</span>
                <span style={{ color: '#e5e5e5' }}>{val != null ? val.toFixed(2) : '—'}</span>
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontSize: 10, color: '#555', marginBottom: 10, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: 1 }}>Estimate Revisions (30d)</div>
            <div style={{ display: 'flex', gap: 20, marginBottom: 12 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#10b981', fontFamily: 'monospace' }}>
                  ↑{latest.revisions_up_30d ?? '—'}
                </div>
                <div style={{ fontSize: 10, color: '#444' }}>Up</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#ef4444', fontFamily: 'monospace' }}>
                  ↓{latest.revisions_down_30d ?? '—'}
                </div>
                <div style={{ fontSize: 10, color: '#444' }}>Down</div>
              </div>
            </div>
            {[
              ['Current Year EPS Growth', latest.eps_growth_current_yr],
              ['Next Year EPS Growth',    latest.eps_growth_next_yr],
            ].map(([label, val]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace' }}>
                <span style={{ color: '#666' }}>{label}</span>
                <span style={{ color: val >= 0 ? '#10b981' : '#ef4444' }}>
                  {val != null ? `${(val * 100).toFixed(1)}%` : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Smoke-test in browser**

Start the dev server (`npm start` in frontend/), open a stock detail, confirm no JS errors in the console. The Analysts tab won't appear yet (wired in Task 8).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AnalystTab.js
git commit -m "feat: add AnalystTab component for stock detail view"
```

---

## Task 7: AnalystMonitorTab Component

**Files:**
- Create: `frontend/src/components/AnalystMonitorTab.js`

- [ ] **Step 1: Create AnalystMonitorTab.js**

Create `frontend/src/components/AnalystMonitorTab.js`:

```javascript
import { useState, useEffect, useMemo } from 'react';
import { API } from '../utils';

const CONSENSUS_COLORS = {
  Buy:  { bg: '#0d3320', color: '#10b981' },
  Hold: { bg: '#1a1400', color: '#f59e0b' },
  Sell: { bg: '#2a0d0d', color: '#ef4444' },
};

function ConsensusBadge({ value }) {
  if (!value) return <span style={{ color: '#444' }}>—</span>;
  const c = CONSENSUS_COLORS[value] || { bg: '#1a1a1a', color: '#94a3b8' };
  return (
    <span style={{
      ...c, padding: '2px 8px', borderRadius: 2,
      fontSize: 10, fontFamily: 'monospace', fontWeight: 700
    }}>
      {value}
    </span>
  );
}

function UpsideCell({ value }) {
  if (value == null) return <span style={{ color: '#444' }}>—</span>;
  const color = value >= 0 ? '#10b981' : '#ef4444';
  return <span style={{ color, fontFamily: 'monospace', fontSize: 12 }}>{value >= 0 ? '+' : ''}{value.toFixed(1)}%</span>;
}

// Composite bullish score: buy% + upside (capped at 100, halved) + revision_score * 10
const compositeScore = (r) =>
  (r.buy_pct || 0) +
  Math.min(Math.max(r.upside_pct || 0, -50), 100) * 0.5 +
  (r.revision_score || 0) * 10;

export default function AnalystMonitorTab({ refreshKey }) {
  const [latest, setLatest]   = useState([]);
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast]     = useState(null);
  const [search, setSearch]   = useState('');
  const [sortKey, setSortKey] = useState('buy_pct');
  const [sortDir, setSortDir] = useState('desc');

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/analysts/latest`).then(r => r.json()),
      fetch(`${API}/analysts/changes`).then(r => r.json()),
    ])
      .then(([l, c]) => {
        setLatest(Array.isArray(l) ? l : []);
        setChanges(Array.isArray(c) ? c : []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetch(`${API}/analysts/refresh`, { method: 'POST' });
      setToast('Refresh started — this takes a few minutes');
    } catch {
      setToast('Refresh failed');
    } finally {
      setRefreshing(false);
      setTimeout(() => setToast(null), 5000);
    }
  };

  const stocksWithData = useMemo(
    () => latest.filter(r => r.consensus != null),
    [latest]
  );

  const topBullish = useMemo(
    () => [...stocksWithData].sort((a, b) => compositeScore(b) - compositeScore(a)).slice(0, 5),
    [stocksWithData]
  );

  const topBearish = useMemo(
    () => [...stocksWithData].sort((a, b) => compositeScore(a) - compositeScore(b)).slice(0, 5),
    [stocksWithData]
  );

  const filtered = useMemo(() => {
    let rows = stocksWithData;
    if (search) {
      const q = search.toLowerCase();
      rows = rows.filter(r =>
        r.symbol?.toLowerCase().includes(q) || r.name?.toLowerCase().includes(q)
      );
    }
    return [...rows].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity;
      const bv = b[sortKey] ?? -Infinity;
      return sortDir === 'desc' ? bv - av : av - bv;
    });
  }, [stocksWithData, search, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(key); setSortDir('desc'); }
  };

  const colStyle = (key) => ({
    cursor: 'pointer', userSelect: 'none', color: sortKey === key ? '#f97316' : '#555',
    fontSize: 10, textTransform: 'uppercase', letterSpacing: 1,
    padding: '8px 12px', textAlign: 'right', fontFamily: 'monospace',
  });

  const S = {
    card: { background: '#141414', border: '1px solid #2a2a2a', borderRadius: 3, padding: 16 },
    th:   { fontSize: 10, color: '#555', textTransform: 'uppercase', letterSpacing: 1, padding: '8px 12px', fontFamily: 'monospace', textAlign: 'left' },
    td:   { padding: '8px 12px', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace', color: '#e5e5e5' },
    tdR:  { padding: '8px 12px', borderBottom: '1px solid #1a1a1a', fontSize: 12, fontFamily: 'monospace', color: '#e5e5e5', textAlign: 'right' },
  };

  if (loading) return <div style={{ color: '#444', padding: 32, fontFamily: 'monospace' }}>Loading analyst data…</div>;

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ fontFamily: 'monospace', fontSize: 14, color: '#f97316', textTransform: 'uppercase', letterSpacing: 2, margin: 0 }}>
          Analyst Monitor
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {toast && <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>{toast}</span>}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            style={{ background: '#1a1a1a', color: refreshing ? '#444' : '#666', border: '1px solid #2a2a2a', padding: '4px 12px', borderRadius: 2, fontFamily: 'monospace', fontSize: 10, cursor: refreshing ? 'default' : 'pointer' }}
          >
            {refreshing ? '↻ Starting…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {/* Signals board */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        {[
          { title: 'Top Bullish', stocks: topBullish, accent: '#10b981' },
          { title: 'Top Bearish', stocks: topBearish, accent: '#ef4444' },
        ].map(({ title, stocks, accent }) => (
          <div key={title} style={S.card}>
            <div style={{ fontSize: 10, color: accent, textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', marginBottom: 12 }}>{title}</div>
            {stocks.length === 0 && <div style={{ color: '#444', fontSize: 11 }}>No data yet</div>}
            {stocks.map(r => (
              <div key={r.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #1a1a1a' }}>
                <div>
                  <span style={{ color: '#e5e5e5', fontFamily: 'monospace', fontSize: 12, fontWeight: 700 }}>{r.symbol}</span>
                  <ConsensusBadge value={r.consensus} />
                </div>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <UpsideCell value={r.upside_pct} />
                  {r.revision_score != null && (
                    <span style={{ fontSize: 10, color: r.revision_score > 0 ? '#10b981' : r.revision_score < 0 ? '#ef4444' : '#555', fontFamily: 'monospace' }}>
                      {r.revision_score > 0 ? `↑${r.revision_score}` : r.revision_score < 0 ? `↓${Math.abs(r.revision_score)}` : '—'}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Main layout: table + change feed */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16, alignItems: 'start' }}>

        {/* Full table */}
        <div style={S.card}>
          <div style={{ marginBottom: 12 }}>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter by symbol or name…"
              style={{ background: '#0a0a0a', border: '1px solid #2a2a2a', color: '#e5e5e5', padding: '6px 10px', borderRadius: 2, fontFamily: 'monospace', fontSize: 11, width: '100%', boxSizing: 'border-box' }}
            />
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2a2a2a' }}>
                  <th style={S.th}>Symbol</th>
                  <th style={S.th}>Consensus</th>
                  <th style={{ ...colStyle('buy_pct'), textAlign: 'right' }} onClick={() => toggleSort('buy_pct')}>
                    Buy% {sortKey === 'buy_pct' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('upside_pct'), textAlign: 'right' }} onClick={() => toggleSort('upside_pct')}>
                    Upside {sortKey === 'upside_pct' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('revision_score'), textAlign: 'right' }} onClick={() => toggleSort('revision_score')}>
                    Revisions {sortKey === 'revision_score' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                  <th style={{ ...colStyle('total_analysts'), textAlign: 'right' }} onClick={() => toggleSort('total_analysts')}>
                    Analysts {sortKey === 'total_analysts' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={6} style={{ ...S.td, color: '#444', textAlign: 'center', padding: 24 }}>No results</td></tr>
                )}
                {filtered.map(r => (
                  <tr key={r.symbol} style={{ borderBottom: '1px solid #141414' }}>
                    <td style={S.td}>
                      <span style={{ fontWeight: 700 }}>{r.symbol}</span>
                    </td>
                    <td style={S.td}><ConsensusBadge value={r.consensus} /></td>
                    <td style={S.tdR}>{r.buy_pct != null ? `${r.buy_pct.toFixed(1)}%` : '—'}</td>
                    <td style={S.tdR}><UpsideCell value={r.upside_pct} /></td>
                    <td style={{ ...S.tdR, color: r.revision_score > 0 ? '#10b981' : r.revision_score < 0 ? '#ef4444' : '#555' }}>
                      {r.revision_score != null ? (r.revision_score > 0 ? `+${r.revision_score}` : r.revision_score) : '—'}
                    </td>
                    <td style={S.tdR}>{r.total_analysts ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Change feed */}
        <div style={S.card}>
          <div style={{ fontSize: 10, color: '#f97316', textTransform: 'uppercase', letterSpacing: 1, fontFamily: 'monospace', marginBottom: 12 }}>
            Recent Changes
          </div>
          {changes.length === 0 && (
            <div style={{ color: '#444', fontSize: 11, fontFamily: 'monospace' }}>
              No significant changes since last refresh
            </div>
          )}
          {changes.map((c, i) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #1a1a1a' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ color: '#e5e5e5', fontFamily: 'monospace', fontSize: 12, fontWeight: 700 }}>{c.symbol}</span>
                <span style={{ color: '#444', fontSize: 10, fontFamily: 'monospace' }}>{c.snapshot_date}</span>
              </div>
              {c.prev_consensus !== c.consensus && (
                <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#94a3b8' }}>
                  <span style={{ color: '#666' }}>{c.prev_consensus || '—'}</span>
                  {' → '}
                  <span style={{ color: CONSENSUS_COLORS[c.consensus]?.color || '#94a3b8' }}>{c.consensus}</span>
                </div>
              )}
              {c.upside_pct != null && (
                <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
                  <span style={{ color: '#555' }}>Upside </span>
                  <UpsideCell value={c.upside_pct} />
                </div>
              )}
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/AnalystMonitorTab.js
git commit -m "feat: add AnalystMonitorTab component"
```

---

## Task 8: Wire Everything into App.js

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Add imports at the top of App.js**

Find the existing component imports (lines 8-12):

```javascript
import RotationTab from './components/RotationTab';
import BreadthTab from './components/BreadthTab';
import FearGreedTab from './components/FearGreedTab';
import CrossAssetTab from './components/CrossAssetTab';
import SignalsTab from './components/SignalsTab';
```

Add two lines after:

```javascript
import AnalystTab from './components/AnalystTab';
import AnalystMonitorTab from './components/AnalystMonitorTab';
```

- [ ] **Step 2: Add Analysts tab to CompanyDetail**

Find the `tabs` array in `CompanyDetail`:

```javascript
  const tabs = ['chart','overview','financials','valuation','health','growth'];
```

Replace with:

```javascript
  const tabs = ['chart','overview','financials','valuation','health','growth','analysts'];
```

Find the last tab content block in `CompanyDetail` (the `{tab==='growth' && ...}` closing section) and add after it:

```javascript
      {/* ANALYSTS */}
      {tab==='analysts' && (
        <AnalystTab symbol={symbol} />
      )}
```

- [ ] **Step 3: Add Analyst Monitor to NAV_GROUPS**

Find the `NAV_GROUPS` array:

```javascript
  const NAV_GROUPS = [
    { id: 'screener', label: 'Screener' },
    { id: 'sector-analysis', label: 'Sector Analysis', children: [
```

Add an entry before sector-analysis:

```javascript
  const NAV_GROUPS = [
    { id: 'screener',         label: 'Screener' },
    { id: 'analyst-monitor',  label: 'Analysts' },
    { id: 'sector-analysis',  label: 'Sector Analysis', children: [
```

- [ ] **Step 4: Add page render for analyst-monitor**

Find the page render block:

```javascript
            <Screener onSelect={selectCompany} highlightSymbol={highlightSymbol} />
```

The section below it renders other pages. Add after the last `{page==='signals' && ...}` line:

```javascript
          {page==='analyst-monitor' && <AnalystMonitorTab refreshKey={refreshKey} />}
```

- [ ] **Step 5: Add Consensus and Upside columns to the screener table**

Find the screener table header row. Look for the `<th>` block with the existing column headers. Find where the last financial columns are (around `Momentum`, `Quality`, etc.) and add after the existing analyst-adjacent columns:

```javascript
<th style={S.th}>Consensus</th>
<th style={S.th}>Upside</th>
```

Find the corresponding `<td>` data row rendering for each stock `r` and add matching cells in the same position:

```javascript
<td style={S.td}>
  {r.consensus
    ? <span style={{
        ...({ Buy: { background:'#0d3320', color:'#10b981' }, Hold: { background:'#1a1400', color:'#f59e0b' }, Sell: { background:'#2a0d0d', color:'#ef4444' } }[r.consensus] || {}),
        padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', fontWeight:700
      }}>{r.consensus}</span>
    : <span style={{ color:'#2a2a2a' }}>—</span>}
</td>
<td style={{ ...S.td, textAlign:'right', color: r.upside_pct >= 0 ? '#10b981' : r.upside_pct < 0 ? '#ef4444' : '#555' }}>
  {r.upside_pct != null ? `${r.upside_pct >= 0 ? '+' : ''}${r.upside_pct.toFixed(1)}%` : '—'}
</td>
```

- [ ] **Step 6: Add Analyst filter section to the screener filter panel**

Find the advanced filter panel in the `Screener` component. Look for an existing filter section (e.g., `Min ROE`, `Max P/E`) to understand the pattern. Add a new Analyst section alongside existing filter groups:

```javascript
{/* Analyst filters */}
<div>
  <div style={{ fontSize:10, color:'#555', textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>Analyst</div>
  <select
    value={filters.consensus || ''}
    onChange={e => setFilters(f => ({ ...f, consensus: e.target.value || null }))}
    style={{ background:'#0a0a0a', border:'1px solid #2a2a2a', color:'#e5e5e5', padding:'5px 8px', borderRadius:2, fontFamily:'monospace', fontSize:11, width:'100%', marginBottom:6 }}
  >
    <option value="">All Consensus</option>
    <option value="Buy">Buy</option>
    <option value="Hold">Hold</option>
    <option value="Sell">Sell</option>
  </select>
  <input
    type="number"
    placeholder="Min Upside %"
    value={filters.min_upside_pct || ''}
    onChange={e => setFilters(f => ({ ...f, min_upside_pct: e.target.value ? parseFloat(e.target.value) : null }))}
    style={{ background:'#0a0a0a', border:'1px solid #2a2a2a', color:'#e5e5e5', padding:'5px 8px', borderRadius:2, fontFamily:'monospace', fontSize:11, width:'100%', boxSizing:'border-box' }}
  />
</div>
```

Find where `EMPTY_FILTERS` is defined in the Screener component and add the new fields:

```javascript
const EMPTY_FILTERS = {
  sector: null, country: null, ftse_index: null,
  min_market_cap: null, max_pe: null, min_roe: null, min_revenue_growth: null,
  consensus: null, min_upside_pct: null,
};
```

Find the `runScreener` function where URL params are built and add:

```javascript
    if (f.consensus)      params.append('consensus',      f.consensus);
    if (f.min_upside_pct) params.append('min_upside_pct', f.min_upside_pct);
```

- [ ] **Step 7: Verify in browser**

Start both backend (`uvicorn main:app --reload`) and frontend (`npm start`). Check:
1. Screener shows Consensus and Upside columns (may be `—` until first refresh runs)
2. Stock detail has an "Analysts" tab (shows "No analyst data available" until refresh runs)
3. Nav has "Analysts" entry that loads the Analyst Monitor page
4. Refresh button on Analyst Monitor page returns "Refresh started"

- [ ] **Step 8: Run the refresh manually to populate data**

```bash
cd backend && python refresh_analysts.py
```

Expected output like:
```
[analysts] starting refresh at 2026-04-08 ...
[analysts] refresh done — processed=287 skipped=113 errors=0
```

Then refresh the browser — screener, detail, and monitor page should all show live data.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/App.js
git commit -m "feat: wire analyst tabs, monitor page, and screener columns into App.js"
```

---

## Task 9: Final Test Run + Task Scheduler Confirmation

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 2: Confirm Task Scheduler is configured**

Open Windows Task Scheduler, find "Stock Screener — Analyst Refresh", right-click → Run. Confirm it completes without error (check the Last Run Result column — should show `0x0`).

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: analyst monitor complete — screener, detail tab, monitor page, nightly refresh"
```
