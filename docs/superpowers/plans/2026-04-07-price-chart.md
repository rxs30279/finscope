# Price Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-company price chart (Chart tab, default view) with MA20/MA50 overlays, range selector, and automatic price top-up on load.

**Architecture:** Two new backend endpoints in `prices.py` (GET prices, POST per-symbol refresh). A `PriceChart` React component in `App.js` calls refresh then fetches, computes MAs client-side, and slices by range. The Chart tab becomes the default tab in `CompanyDetail`.

**Tech Stack:** Python/FastAPI backend, PostgreSQL via psycopg2, yfinance, React with Recharts (already installed), pytest + unittest.mock for tests.

---

## File Map

| File | Change |
|------|--------|
| `backend/prices.py` | Add `GET /api/prices/{symbol}` and `POST /api/prices/refresh/{symbol}` |
| `backend/tests/test_prices.py` | Add tests for both new endpoints |
| `frontend/src/App.js` | Add `PriceChart` component; make Chart the default tab in `CompanyDetail` |

---

## Task 1: `GET /api/prices/{symbol}`

**Files:**
- Modify: `backend/prices.py` (add route after existing `refresh_prices`)
- Modify: `backend/tests/test_prices.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_prices.py`:

```python
# ── GET /api/prices/{symbol} ──────────────────────────────────────────────────

def test_get_prices_returns_list(client):
    rows = [
        {'date': date(2024, 1, 2), 'close': 310.5},
        {'date': date(2024, 1, 3), 'close': 315.0},
    ]
    with patch('prices.query', return_value=rows):
        r = client.get('/api/prices/SHEL.L')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]['date'] == '2024-01-02'
    assert data[0]['close'] == 310.5


def test_get_prices_404_when_no_data(client):
    with patch('prices.query', return_value=[]):
        r = client.get('/api/prices/UNKNOWN.L')
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && python -m pytest tests/test_prices.py::test_get_prices_returns_list tests/test_prices.py::test_get_prices_404_when_no_data -v
```

Expected: `FAILED` — route not defined yet.

- [ ] **Step 3: Add endpoint to `backend/prices.py`**

Add after the closing `return` of `refresh_prices` (after line 197):

```python
from fastapi import HTTPException


@router.get("/api/prices/{symbol}")
def get_prices(symbol: str):
    """Return full close history for a symbol, oldest first."""
    rows = query(
        "SELECT date, close FROM price_history WHERE symbol = %s ORDER BY date ASC",
        (symbol,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No price history")
    return [{"date": str(r["date"]), "close": float(r["close"])} for r in rows]
```

Note: `HTTPException` is already imported in `main.py` but not in `prices.py` — add the import at the top of the `prices.py` imports block:

```python
from fastapi import APIRouter, HTTPException
```

(Replace the existing `from fastapi import APIRouter` line.)

- [ ] **Step 4: Run tests — both should pass**

```bash
cd backend && python -m pytest tests/test_prices.py::test_get_prices_returns_list tests/test_prices.py::test_get_prices_404_when_no_data -v
```

Expected: `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add backend/prices.py backend/tests/test_prices.py && git commit -m "feat: add GET /api/prices/{symbol} endpoint"
```

---

## Task 2: `POST /api/prices/refresh/{symbol}`

**Files:**
- Modify: `backend/prices.py` (add route)
- Modify: `backend/tests/test_prices.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_prices.py`:

```python
# ── POST /api/prices/refresh/{symbol} ────────────────────────────────────────

def test_refresh_symbol_already_up_to_date(client):
    from datetime import date as _date
    today = _date.today()
    yesterday = today - timedelta(days=1)
    with patch('prices.query', return_value=[{'latest': yesterday}]):
        r = client.post('/api/prices/refresh/SHEL.L')
    assert r.status_code == 200
    assert r.json() == {'rows_added': 0}


def test_refresh_symbol_fetches_missing_rows(client):
    from datetime import date as _date
    stale_date = _date(2026, 4, 2)
    with patch('prices.query', return_value=[{'latest': stale_date}]), \
         patch('prices._fetch_closes', return_value=[('SHEL.L', _date(2026, 4, 3), 320.0)]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=1) as mock_upsert:
        r = client.post('/api/prices/refresh/SHEL.L')
    assert r.status_code == 200
    assert r.json()['rows_added'] == 1
    mock_fetch.assert_called_once()
    mock_upsert.assert_called_once()


def test_refresh_symbol_no_history_uses_3yr_start(client):
    from datetime import date as _date
    with patch('prices.query', return_value=[{'latest': None}]), \
         patch('prices._fetch_closes', return_value=[]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=0):
        r = client.post('/api/prices/refresh/NEW.L')
    assert r.status_code == 200
    called_start = mock_fetch.call_args[0][1]
    assert (_date.today() - called_start).days >= 3 * 365 - 1
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && python -m pytest tests/test_prices.py::test_refresh_symbol_already_up_to_date tests/test_prices.py::test_refresh_symbol_fetches_missing_rows tests/test_prices.py::test_refresh_symbol_no_history_uses_3yr_start -v
```

Expected: `FAILED` — route not defined yet.

- [ ] **Step 3: Add endpoint to `backend/prices.py`**

Add after `get_prices`:

```python
@router.post("/api/prices/refresh/{symbol}")
def refresh_symbol(symbol: str):
    """Top up price history for a single symbol to today."""
    rows = query(
        "SELECT MAX(date) AS latest FROM price_history WHERE symbol = %s",
        (symbol,)
    )
    latest = rows[0]["latest"] if rows else None

    if latest is not None:
        start = latest + timedelta(days=1)
    else:
        start = date.today() - timedelta(days=3 * 365)

    if start >= date.today():
        return {"rows_added": 0}

    fetched = _fetch_closes([symbol], start)
    count = _upsert_rows(fetched)
    return {"rows_added": count}
```

- [ ] **Step 4: Run tests — all three should pass**

```bash
cd backend && python -m pytest tests/test_prices.py::test_refresh_symbol_already_up_to_date tests/test_prices.py::test_refresh_symbol_fetches_missing_rows tests/test_prices.py::test_refresh_symbol_no_history_uses_3yr_start -v
```

Expected: `PASSED`.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd backend && python -m pytest -v 2>&1 | tail -10
```

Expected: same 1 pre-existing failure (`test_cross_asset_returns_expected_keys`), everything else passes.

- [ ] **Step 6: Commit**

```bash
git add backend/prices.py backend/tests/test_prices.py && git commit -m "feat: add POST /api/prices/refresh/{symbol} per-symbol price top-up"
```

---

## Task 3: Frontend — `PriceChart` component and Chart tab

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Add `PriceChart` component**

Find the line `// ── Screener ──` in `App.js` (around line 413) and insert the full `PriceChart` component **before** it:

```javascript
// ── PriceChart ────────────────────────────────────────────────────────────────
function PriceChart({ symbol }) {
  const [priceData, setPriceData] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [range, setRange]         = useState('1Y');
  const [showMA20, setShowMA20]   = useState(true);
  const [showMA50, setShowMA50]   = useState(true);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetch(`${API}/prices/refresh/${symbol}`, { method: 'POST' })
      .then(() => fetch(`${API}/prices/${symbol}`))
      .then(r => r.json())
      .then(data => { setPriceData(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [symbol]);

  const computeMA = (data, n) =>
    data.map((_, i) => {
      if (i < n - 1) return null;
      const slice = data.slice(i - n + 1, i + 1);
      return Math.round(slice.reduce((s, d) => s + d.close, 0) / n * 100) / 100;
    });

  const ma20 = computeMA(priceData, 20);
  const ma50 = computeMA(priceData, 50);

  const RANGE_DAYS = { '1M': 30, '3M': 90, '6M': 180, '1Y': 365, '3Y': 1095, 'All': null };
  const cutoffDays = RANGE_DAYS[range];
  const latest = priceData.length ? new Date(priceData[priceData.length - 1].date) : new Date();
  const cutoff  = cutoffDays ? new Date(latest.getTime() - cutoffDays * 86400000) : null;

  const chartData = priceData
    .map((d, i) => ({ date: d.date, close: d.close, ma20: ma20[i], ma50: ma50[i] }))
    .filter(d => !cutoff || new Date(d.date) >= cutoff);

  const pillBase = {
    border: '1px solid #2a2a2a', borderRadius: 4, padding: '3px 10px',
    fontSize: 12, cursor: 'pointer', fontFamily: 'monospace', background: 'none',
  };
  const rangePill   = active => ({ ...pillBase, ...(active ? { background:'#3730a3', color:'#e0e7ff', borderColor:'#4338ca' } : { color:'#64748b' }) });
  const ma20Pill    = active => ({ ...pillBase, ...(active ? { background:'#78350f', color:'#fde68a', borderColor:'#92400e' } : { color:'#64748b' }) });
  const ma50Pill    = active => ({ ...pillBase, ...(active ? { background:'#4c1d95', color:'#ddd6fe', borderColor:'#5b21b6' } : { color:'#64748b' }) });

  if (loading) return (
    <div style={{ height:400, display:'flex', alignItems:'center', justifyContent:'center', color:'#64748b', fontFamily:'monospace' }}>
      Loading…
    </div>
  );
  if (!priceData.length) return (
    <div style={{ height:400, display:'flex', alignItems:'center', justifyContent:'center', color:'#64748b' }}>
      No price history available
    </div>
  );

  return (
    <div>
      <div style={{ display:'flex', gap:8, marginBottom:12, flexWrap:'wrap', alignItems:'center' }}>
        <div style={{ display:'flex', gap:4 }}>
          {['1M','3M','6M','1Y','3Y','All'].map(r => (
            <button key={r} onClick={() => setRange(r)} style={rangePill(r === range)}>{r}</button>
          ))}
        </div>
        <div style={{ display:'flex', gap:4, marginLeft:8 }}>
          <button onClick={() => setShowMA20(v => !v)} style={ma20Pill(showMA20)}>MA20</button>
          <button onClick={() => setShowMA50(v => !v)} style={ma50Pill(showMA50)}>MA50</button>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={380}>
        <AreaChart data={chartData} margin={{ top:5, right:10, bottom:5, left:0 }}>
          <defs>
            <linearGradient id="gPrice" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.3}/>
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
            </linearGradient>
          </defs>
          <XAxis dataKey="date" tick={{ fontSize:10 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize:10 }} domain={['auto','auto']} width={60} />
          <Tooltip
            contentStyle={S.tooltip}
            formatter={(val, name) => [val != null ? val.toFixed(2) : '—', name]}
          />
          <Area type="monotone" dataKey="close" stroke="#6366f1" fill="url(#gPrice)" strokeWidth={2} dot={false} name="Close" />
          {showMA20 && <Line type="monotone" dataKey="ma20" stroke="#f59e0b" strokeWidth={1.5} dot={false} strokeDasharray="4 2" name="MA20" connectNulls={false} />}
          {showMA50 && <Line type="monotone" dataKey="ma50" stroke="#a855f7" strokeWidth={1.5} dot={false} name="MA50" connectNulls={false} />}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

```

- [ ] **Step 2: Make Chart the default tab**

Find in `CompanyDetail`:

```javascript
  const [tab, setTab]         = useState('overview');
```

Replace with:

```javascript
  const [tab, setTab]         = useState('chart');
```

- [ ] **Step 3: Add Chart to the tabs array**

Find:

```javascript
  const tabs = ['overview','financials','valuation','health','growth'];
```

Replace with:

```javascript
  const tabs = ['chart','overview','financials','valuation','health','growth'];
```

- [ ] **Step 4: Add Chart tab render**

Find the `{/* OVERVIEW */}` comment block (around line 122):

```javascript
      {/* OVERVIEW */}
      {tab==='overview' && (
```

Insert this block immediately before it:

```javascript
      {/* CHART */}
      {tab==='chart' && (
        <div>
          <PriceChart symbol={symbol} />
        </div>
      )}

      {/* OVERVIEW */}
      {tab==='overview' && (
```

- [ ] **Step 5: Verify in browser**

Start the backend and frontend:
```bash
# terminal 1
cd backend && uvicorn main:app --reload
# terminal 2
cd frontend && npm start
```

Click any company. The Chart tab should be selected by default and show:
- A loading state briefly while refresh + fetch runs
- An indigo area chart of daily closes
- MA20 (dashed amber) and MA50 (purple) overlaid
- Range buttons (1M 3M 6M 1Y 3Y All) and MA toggle buttons above the chart

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.js && git commit -m "feat: add PriceChart component with MA overlays and Chart as default tab"
```
