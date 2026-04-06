# Price History & Momentum Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store daily closing prices for all 531 FTSE stocks in PostgreSQL and use them to compute a 12-1 month momentum score (1–10) displayed in the screener table.

**Architecture:** A new `price_history` table stores adjusted daily closes. A new `backend/prices.py` FastAPI router handles the on-demand refresh endpoint (fetches missing dates via yfinance) and the `_attach_momentum` scoring function. `main.py` wires the router in and calls `_attach_momentum` in the screener endpoint.

**Tech Stack:** Python, FastAPI, yfinance, psycopg2, PostgreSQL/Supabase, React

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/prices.py` | Create | Router + refresh endpoint + `_attach_momentum` |
| `backend/main.py` | Modify | Import prices router; call `_attach_momentum` in screener |
| `backend/tests/test_prices.py` | Create | Tests for refresh endpoint and momentum scoring |
| `frontend/src/App.js` | Modify | Momentum column + Refresh Prices button |

---

## Task 1: Create the `price_history` table

**Files:**
- Run SQL directly against Supabase

- [ ] **Step 1: Create the table**

Run this SQL in your Supabase SQL editor (or via psql):

```sql
CREATE TABLE IF NOT EXISTS price_history (
    symbol  TEXT    NOT NULL,
    date    DATE    NOT NULL,
    close   NUMERIC NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS price_history_symbol_date_idx
    ON price_history (symbol, date DESC);
```

- [ ] **Step 2: Verify the table exists**

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'price_history'
ORDER BY ordinal_position;
```

Expected output:
```
 column_name | data_type
-------------+-----------
 symbol      | text
 date        | date
 close       | numeric
```

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "feat: create price_history table in Supabase"
```

---

## Task 2: Create `backend/prices.py`

**Files:**
- Create: `backend/prices.py`

- [ ] **Step 1: Write the failing test first**

Create `backend/tests/test_prices.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from datetime import date, timedelta


# ── helpers ───────────────────────────────────────────────────────────────────

def _fake_yf_download(symbols, start, rows=300):
    """Return a fake yfinance download DataFrame."""
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=rows)
    np.random.seed(42)
    if len(symbols) == 1:
        prices = 100 * np.cumprod(1 + np.random.normal(0.0002, 0.01, rows))
        df = pd.DataFrame({'Close': prices}, index=dates)
    else:
        close_data = {}
        for sym in symbols:
            prices = 100 * np.cumprod(1 + np.random.normal(0.0002, 0.01, rows))
            close_data[sym] = prices
        df = pd.DataFrame(close_data, index=dates)
        df.columns = pd.MultiIndex.from_product([['Close'], df.columns])
    return df


# ── refresh endpoint tests ────────────────────────────────────────────────────

def test_refresh_returns_summary(client):
    with patch('prices.yf.download', return_value=_fake_yf_download(['SHEL.L'], None)) as mock_dl, \
         patch('prices.query') as mock_query, \
         patch('prices._upsert_rows', return_value=10) as mock_upsert:
        mock_query.side_effect = [
            # all symbols from company_metadata
            [{'symbol': 'SHEL.L'}],
            # latest dates from price_history (empty — no history yet)
            [],
        ]
        r = client.post('/api/prices/refresh')
    assert r.status_code == 200
    data = r.json()
    assert 'rows_added' in data
    assert 'updated' in data
    assert 'duration_seconds' in data


# ── _attach_momentum tests ────────────────────────────────────────────────────

def test_attach_momentum_scores_range():
    import prices
    results = [{'symbol': f'S{i}.L'} for i in range(10)]
    mock_rows = [
        {'symbol': f'S{i}.L', 'close_63': 110 + i, 'close_252': 100.0}
        for i in range(10)
    ]
    with patch('prices.query', return_value=mock_rows):
        prices._attach_momentum(results)
    scores = [r['momentum_score'] for r in results if r['momentum_score'] is not None]
    assert all(1 <= s <= 10 for s in scores)


def test_attach_momentum_null_for_insufficient_history():
    import prices
    results = [{'symbol': 'SHEL.L'}]
    # No rows returned — stock has < 252 days of history
    with patch('prices.query', return_value=[]):
        prices._attach_momentum(results)
    assert results[0]['momentum_score'] is None


def test_attach_momentum_empty_results():
    import prices
    result = prices._attach_momentum([])
    assert result == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_prices.py -v
```

Expected: `ModuleNotFoundError: No module named 'prices'` (or similar — the module doesn't exist yet).

- [ ] **Step 3: Create `backend/prices.py`**

```python
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
        count = cur.rowcount
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
```

- [ ] **Step 4: Run tests**

```bash
cd backend
pytest tests/test_prices.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/prices.py backend/tests/test_prices.py
git commit -m "feat: add prices module with refresh endpoint and momentum scoring"
```

---

## Task 3: Wire `prices.py` into `main.py`

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add import and router registration**

In `backend/main.py`, add after the existing market router import and registration:

```python
# after: from market import router as market_router
from prices import router as prices_router

# after: app.include_router(market_router)
app.include_router(prices_router)
```

- [ ] **Step 2: Call `_attach_momentum` in the screener endpoint**

Find the screener return statement (currently `return _attach_piotroski(results)` area):

```python
# Replace:
    results = query(sql, params)
    for r in results:
        r['quality_score'] = _quality_score(r)
    return _attach_piotroski(results)

# With:
    from prices import _attach_momentum
    results = query(sql, params)
    for r in results:
        r['quality_score'] = _quality_score(r)
    _attach_momentum(results)
    return _attach_piotroski(results)
```

- [ ] **Step 3: Verify the screener still works**

```bash
cd backend
pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 4: Manually test the refresh endpoint**

```bash
curl -X POST http://localhost:8000/api/prices/refresh
```

Expected (first run, will take 60–120 seconds):
```json
{"updated": 531, "rows_added": 180000, "duration_seconds": 85.3}
```

Expected (subsequent runs, seconds):
```json
{"updated": 531, "rows_added": 531, "duration_seconds": 4.2}
```

- [ ] **Step 5: Verify momentum scores appear in screener**

```bash
curl -s "http://localhost:8000/api/screener?limit=5" | python -c "
import sys, json
data = json.load(sys.stdin)
for r in data:
    print(r['symbol'], 'momentum:', r.get('momentum_score'))
"
```

Expected: each row has a `momentum_score` of 1–10 or `null`.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire prices router and momentum score into screener endpoint"
```

---

## Task 4: Frontend — Momentum column and Refresh Prices button

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Add the Momentum column to the screener table**

Find the table headers array in the `Screener` component:

```jsx
// Replace:
{[['Symbol',false],['Name',false],['Sector',false],['Index',false],['Mkt Cap',true],['P/E',true],['P/B',true],['ROE',true],['Rev Growth',true],['D/E',true],['Quality',true],['Value',true]].map(([h,num])=>(

// With:
{[['Symbol',false],['Name',false],['Sector',false],['Index',false],['Mkt Cap',true],['P/E',true],['P/B',true],['ROE',true],['Rev Growth',true],['D/E',true],['Momentum',true],['Quality',true],['Value',true]].map(([h,num])=>(
```

Then add the Momentum `<td>` cell in the row, just before the Quality cell:

```jsx
{/* Add before the Quality <td> */}
<td style={{ ...S.tdNum,
  color: r.momentum_score == null ? '#444'
       : r.momentum_score >= 7    ? '#10b981'
       : r.momentum_score >= 4    ? '#f59e0b'
       :                            '#ef4444',
  fontWeight: 700,
}}>{r.momentum_score ?? '—'}</td>
```

- [ ] **Step 2: Add Refresh Prices button and state to the App component**

Find the `App` component state declarations (near `const [refreshKey, setRefreshKey]`). Add:

```jsx
const [priceRefreshing, setPriceRefreshing] = useState(false);
const [priceToast, setPriceToast]           = useState(null);
```

Add the handler function inside `App`, after the existing `handleRefresh`:

```jsx
const handlePriceRefresh = async () => {
  setPriceRefreshing(true);
  setPriceToast(null);
  try {
    const res = await fetch(`${API}/prices/refresh`, { method: 'POST' });
    const data = await res.json();
    setPriceToast({ ok: true, msg: `+${data.rows_added} rows (${data.duration_seconds}s)` });
  } catch {
    setPriceToast({ ok: false, msg: 'Price refresh failed' });
  } finally {
    setPriceRefreshing(false);
    setTimeout(() => setPriceToast(null), 4000);
  }
};
```

- [ ] **Step 3: Add the button and toast to the nav bar**

Find the nav bar area with the existing `↻` refresh button and add the Refresh Prices button and toast next to it:

```jsx
{/* Add after the existing ↻ button */}
<button
  onClick={handlePriceRefresh}
  disabled={priceRefreshing}
  title="Refresh price history"
  style={{
    background: '#1a1a1a', color: priceRefreshing ? '#444' : '#666',
    border: '1px solid #2a2a2a', padding: '4px 10px',
    borderRadius: 2, fontFamily: 'monospace', fontSize: 10,
    cursor: priceRefreshing ? 'not-allowed' : 'pointer',
  }}
>
  {priceRefreshing ? 'Refreshing…' : '↻ Prices'}
</button>
{priceToast && (
  <span style={{
    fontSize: 10, fontFamily: 'monospace',
    color: priceToast.ok ? '#10b981' : '#ef4444',
  }}>
    {priceToast.msg}
  </span>
)}
```

- [ ] **Step 4: Verify in browser**

1. Load the screener — Momentum column should appear with `—` for all rows until prices are fetched.
2. Click "↻ Prices" — button shows "Refreshing…" and is disabled.
3. After completion, toast shows e.g. `+182340 rows (87.3s)`.
4. Reload screener — Momentum scores (1–10) now appear in green/amber/red.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.js
git commit -m "feat: add Momentum column and Refresh Prices button to screener"
```

---

## Self-Review

**Spec coverage:**
- ✅ `price_history` table with correct schema and index — Task 1
- ✅ `POST /api/prices/refresh` fetches missing dates, groups by start date, upserts — Task 2
- ✅ Returns `{ updated, rows_added, duration_seconds }` — Task 2
- ✅ 12-1 month momentum using rn=63 and rn=252 — Task 2
- ✅ Percentile ranked 1–10 within screener universe — Task 2
- ✅ `null` for < 252 days history — Task 2
- ✅ `_attach_momentum` called in screener endpoint — Task 3
- ✅ Momentum column green/amber/red — Task 4
- ✅ Refresh Prices button with loading state and toast — Task 4

**No placeholders present.**

**Type consistency:** `_attach_momentum(results)` signature consistent across Task 2 definition and Task 3 call site. `momentum_score` key consistent in backend (Task 2/3) and frontend (Task 4).
