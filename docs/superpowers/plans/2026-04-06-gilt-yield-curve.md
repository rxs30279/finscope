# Gilt Yield Curve Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a UK Gilt Yield Curve section to the Cross-Asset tab showing a current yield curve snapshot and 5-year historical chart for 2Y, 5Y, 10Y, 20Y, 30Y maturities.

**Architecture:** New `/api/market/gilt-yields` backend endpoint fetches from the Bank of England IADB public API, cached at 4 hours. CrossAssetTab fetches this independently and renders two Recharts charts below the existing asset cards.

**Tech Stack:** Python `requests` (already imported), FastAPI, Recharts (`LineChart`, `Line`, `XAxis`, `YAxis`, `Tooltip`, `Legend`, `ResponsiveContainer`), React `useState`/`useEffect`.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/market.py` | Modify | Replace `_fetch_boe_gilt_yields()`, add `/api/market/gilt-yields` endpoint |
| `frontend/src/components/CrossAssetTab.js` | Modify | Add gilt state, second useEffect, two chart components |

---

## Task 1: Verify BoE API Series Codes

The BoE IADB series codes for nominal spot gilt yields are the primary unknown. This task confirms the correct codes before building anything else.

**Files:**
- No file changes — manual verification only

- [ ] **Step 1: Test BoE API with a known-good series**

Open a browser or run in a Python shell:
```
https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?Travel=NIxRSx&C=IUDBEDR&DAT=RNG&VFD=Y&html.x=66&html.y=26&CSVF=TT&UsingCodes=Y&FD=1&FM=Jan&FY=2026&TD=6&TM=Apr&TY=2026
```
Expected: tab- or comma-separated CSV with `DATE` and `IUDBEDR` columns, showing Bank Rate values (~4.5).

- [ ] **Step 2: Test the nominal gilt yield series codes**

Test each of these URLs in a browser. Replace `{CODE}` with each code below:
```
https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?Travel=NIxRSx&C={CODE}&DAT=RNG&VFD=Y&html.x=66&html.y=26&CSVF=TT&UsingCodes=Y&FD=1&FM=Jan&FY=2026&TD=6&TM=Apr&TY=2026
```

Try in order (stop at first one that returns numeric data, not HTML):
1. `IUDSNS10` — nominal spot 10Y
2. `IUDPNB10` — nominal par bond 10Y
3. `IUDMNPY` — nominal par yield (may be 20Y)
4. `IUMASNB10` — monthly nominal spot bond 10Y

- [ ] **Step 3: Identify the correct prefix and derive all 5 codes**

Once you find the working 10Y code, apply the same prefix to other maturities:
- Replace `10` with `02`, `05`, `20`, `30`
- Test one more (e.g. the 2Y variant) to confirm the pattern holds

- [ ] **Step 4: Note the confirmed series codes**

Write down the 5 confirmed codes. They will be used in Task 2. Example:
```
GILT_SERIES = {2: "IUDSNS02", 5: "IUDSNS05", 10: "IUDSNS10", 20: "IUDSNS20", 30: "IUDSNS30"}
```

---

## Task 2: Replace `_fetch_boe_gilt_yields()` in backend

**Files:**
- Modify: `backend/market.py` — replace existing `_fetch_boe_gilt_yields()` (lines ~413–438)

- [ ] **Step 1: Replace the function with the full 5-maturity implementation**

Locate the existing `_fetch_boe_gilt_yields()` function and replace it entirely with:

```python
def _fetch_boe_gilt_yields():
    """Fetch UK nominal spot gilt yields from Bank of England IADB.
    Returns snapshot (latest values) and 5Y daily history for 2,5,10,20,30Y maturities.
    Series codes confirmed in Task 1 — update GILT_SERIES if codes differ."""
    GILT_SERIES = {
        2:  "IUDSNS02",
        5:  "IUDSNS05",
        10: "IUDSNS10",
        20: "IUDSNS20",
        30: "IUDSNS30",
    }
    BASE_URL = (
        "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
        "?Travel=NIxRSx&C={code}&DAT=RNG&VFD=Y&html.x=66&html.y=26"
        "&CSVF=TT&UsingCodes=Y&FD=1&FM=Jan&FY=2021&TD=31&TM=Dec&TY=2026"
    )
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    def fetch_series(maturity, code):
        try:
            r = requests.get(BASE_URL.format(code=code), timeout=15, headers=HEADERS)
            r.raise_for_status()
            rows = {}
            for line in r.text.splitlines():
                # Handle both tab and comma separated
                parts = line.replace('\t', ',').split(',')
                if len(parts) < 2:
                    continue
                date_str = parts[0].strip().strip('"')
                val_str  = parts[1].strip().strip('"')
                if date_str == 'DATE' or date_str == code:
                    continue
                try:
                    # BoE date format: "01 Jan 2021"
                    dt = datetime.strptime(date_str, "%d %b %Y")
                    rows[dt.strftime("%Y-%m-%d")] = float(val_str)
                except (ValueError, TypeError):
                    continue
            return maturity, rows
        except Exception as e:
            print(f"[market] BoE gilt fetch failed for {maturity}Y ({code}): {e}")
            return maturity, {}

    all_series = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_series, m, c): m for m, c in GILT_SERIES.items()}
        for future in as_completed(futures):
            maturity, rows = future.result()
            if rows:
                all_series[maturity] = rows

    if not all_series:
        return {"snapshot": {}, "history": []}

    # Build snapshot: latest value per maturity
    snapshot = {}
    for maturity, rows in all_series.items():
        if rows:
            latest_date = max(rows.keys())
            snapshot[maturity] = rows[latest_date]

    # Build history: list of {date, y2, y5, y10, y20, y30}
    all_dates = sorted(set(d for rows in all_series.values() for d in rows.keys()))
    history = []
    for date in all_dates:
        row = {"date": date}
        for maturity in [2, 5, 10, 20, 30]:
            row[f"y{maturity}"] = all_series.get(maturity, {}).get(date)
        # Only include rows with at least one value
        if any(v is not None for k, v in row.items() if k != "date"):
            history.append(row)

    return {"snapshot": snapshot, "history": history}
```

- [ ] **Step 2: Update the series codes**

Replace the `GILT_SERIES` dict inside the function with the confirmed codes from Task 1.

- [ ] **Step 3: Add the new endpoint**

Find the `/api/market/cross-asset` endpoint block and add after it:

```python
@router.get("/gilt-yields")
def gilt_yields():
    return _cached("gilt_yields", _fetch_boe_gilt_yields)
```

Note: cache key `"gilt_yields"` is separate from the existing cross-asset cache so they expire independently.

- [ ] **Step 4: Remove the old unused gilt_2y/gilt_10y references from `_compute_cross_asset`**

In `_compute_cross_asset()`, the return dict currently includes `gilt_2y` and `gilt_10y` items that reference the old fetch. Remove them — they now come from the new endpoint instead:

```python
def _compute_cross_asset():
    prices = _get_prices()
    t = CROSS_ASSET_TICKERS
    gbpusd = _cross_asset_item(prices, t["gbpusd"])
    brent  = _cross_asset_item(prices, t["brent"])
    gold   = _cross_asset_item(prices, t["gold"])
    zscore = _gilt_vs_utilities_zscore(prices)

    return {
        "gbpusd":            gbpusd,
        "brent":             brent,
        "gold":              gold,
        "gilt_vs_utilities": {"zscore": zscore, "bias": "Gilts expensive vs Utilities" if zscore is not None and zscore < -1 else None},
    }
```

- [ ] **Step 5: Restart backend and verify the endpoint**

```bash
curl http://localhost:8000/api/market/gilt-yields
```

Expected response shape:
```json
{
  "snapshot": {"2": 4.12, "5": 4.35, "10": 4.61, "20": 4.89, "30": 4.95},
  "history": [
    {"date": "2021-01-04", "y2": 0.05, "y5": 0.31, "y10": 0.28, "y20": 0.72, "y30": 0.82},
    ...
  ]
}
```

If `snapshot` is `{}`, the series codes are wrong — go back to Task 1 Step 2 and try the next code pattern.

- [ ] **Step 6: Commit**

```bash
git add backend/market.py
git commit -m "feat: add /api/market/gilt-yields endpoint from BoE IADB"
```

---

## Task 3: Frontend — gilt data fetch in CrossAssetTab

**Files:**
- Modify: `frontend/src/components/CrossAssetTab.js`

- [ ] **Step 1: Add Recharts imports and gilt state**

At the top of `CrossAssetTab.js`, update the import and add state:

```js
import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { API } from '../utils';
```

In the `CrossAssetTab` component, add alongside the existing state:

```js
const [giltData, setGiltData] = useState(null);
```

- [ ] **Step 2: Add a second useEffect to fetch gilt yields**

After the existing `useEffect` block, add:

```js
useEffect(() => {
  fetch(`${API}/market/gilt-yields`)
    .then(r => r.json())
    .then(setGiltData)
    .catch(() => {});
}, [refreshKey]);
```

- [ ] **Step 3: Remove the now-redundant gilt card references from the existing grid**

The `data?.gilt_2y` and `data?.gilt_10y` asset cards in the existing grid are now blank (removed from cross-asset endpoint). Remove those two lines:

```js
// Remove these two lines:
<AssetCard label="2Y Gilt Yield"   item={data?.gilt_2y}  decimals={2} suffix="%" />
<AssetCard label="10Y Gilt Yield"  item={data?.gilt_10y} decimals={2} suffix="%" />
```

- [ ] **Step 4: Verify in browser**

Refresh the Cross-Asset tab. The gilt cards should be gone and the console should show a successful fetch of `/api/market/gilt-yields`. No errors.

---

## Task 4: Frontend — Yield Curve Snapshot chart

**Files:**
- Modify: `frontend/src/components/CrossAssetTab.js`

- [ ] **Step 1: Add the `GiltYieldCurve` component above the `CrossAssetTab` export**

```js
const MATURITIES = [
  { key: 'y2',  label: '2Y'  },
  { key: 'y5',  label: '5Y'  },
  { key: 'y10', label: '10Y' },
  { key: 'y20', label: '20Y' },
  { key: 'y30', label: '30Y' },
];

function GiltSnapshotChart({ snapshot }) {
  if (!snapshot || Object.keys(snapshot).length === 0) {
    return <div style={{ color:'#333', fontFamily:'monospace', fontSize:11 }}>No gilt data available</div>;
  }

  const data = MATURITIES.map(({ key, label }) => {
    const maturity = parseInt(key.slice(1));
    return { label, yield: snapshot[maturity] ?? null };
  }).filter(d => d.yield !== null);

  const isInverted = data.length >= 2 && data[0].yield > data[data.length - 1].yield;
  const curveColor = isInverted ? '#ef4444' : '#10b981';
  const curveLabel = isInverted ? 'Inverted' : data[0]?.yield === data[data.length - 1]?.yield ? 'Flat' : 'Normal';

  return (
    <div>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
        <div style={{ color:'#555', fontSize:9, textTransform:'uppercase', letterSpacing:1 }}>Current Curve</div>
        <div style={{ color: curveColor, fontSize:9, fontWeight:700 }}>{curveLabel}</div>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top:5, right:10, bottom:5, left:0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
          <XAxis dataKey="label" tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }} />
          <YAxis
            tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }}
            tickFormatter={v => `${v.toFixed(1)}%`}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:11, fontFamily:'monospace' }}
            formatter={v => [`${v.toFixed(2)}%`, 'Yield']}
          />
          <Line type="monotone" dataKey="yield" stroke={curveColor} strokeWidth={2} dot={{ r:4, fill:curveColor }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Add the gilt curve section to the CrossAssetTab return**

After the closing `</div>` of the asset card grid, add:

```js
{giltData && (
  <div style={{ marginTop:24 }}>
    <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:16 }}>
      UK Gilt Yield Curve
    </div>
    <div style={{ display:'grid', gridTemplateColumns:'2fr 3fr', gap:16 }}>
      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
        <GiltSnapshotChart snapshot={giltData.snapshot} />
      </div>
      {/* History chart placeholder — Task 5 */}
      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
        <div style={{ color:'#333', fontSize:11, fontFamily:'monospace' }}>Historical chart — coming in Task 5</div>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 3: Verify in browser**

The Cross-Asset tab should show the "UK Gilt Yield Curve" section with a snapshot line chart. Check that the curve label ("Normal", "Inverted", "Flat") is correct for today's gilt market.

---

## Task 5: Frontend — Historical Time Series chart

**Files:**
- Modify: `frontend/src/components/CrossAssetTab.js`

- [ ] **Step 1: Add the `GiltHistoryChart` component above `CrossAssetTab`**

```js
const MATURITY_COLORS = {
  y2:  '#f97316',
  y5:  '#f59e0b',
  y10: '#10b981',
  y20: '#60a5fa',
  y30: '#a78bfa',
};

function GiltHistoryChart({ history }) {
  if (!history || history.length === 0) {
    return <div style={{ color:'#333', fontFamily:'monospace', fontSize:11 }}>No history available</div>;
  }

  // Thin to ~260 points max for performance (daily over 5Y = ~1300 points)
  const step = Math.max(1, Math.floor(history.length / 260));
  const thinned = history.filter((_, i) => i % step === 0);

  return (
    <div>
      <div style={{ color:'#555', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:8 }}>5-Year History</div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={thinned} margin={{ top:5, right:10, bottom:5, left:0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
          <XAxis
            dataKey="date"
            tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }}
            tickFormatter={d => d.slice(0, 7)}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }}
            tickFormatter={v => `${v.toFixed(1)}%`}
            domain={['auto', 'auto']}
          />
          <Tooltip
            contentStyle={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:10, fontFamily:'monospace' }}
            formatter={(v, name) => [v !== null ? `${v.toFixed(2)}%` : '—', name.toUpperCase()]}
            labelFormatter={l => l}
          />
          <Legend
            wrapperStyle={{ fontSize:9, fontFamily:'monospace' }}
            formatter={v => v.toUpperCase()}
          />
          {MATURITIES.map(({ key }) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={MATURITY_COLORS[key]}
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Replace the history placeholder with the real chart**

In the gilt curve section added in Task 4, replace the placeholder div:

```js
// Replace this:
<div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
  <div style={{ color:'#333', fontSize:11, fontFamily:'monospace' }}>Historical chart — coming in Task 5</div>
</div>

// With this:
<div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
  <GiltHistoryChart history={giltData.history} />
</div>
```

- [ ] **Step 3: Verify in browser**

The Cross-Asset tab should now show both charts:
- Left: snapshot line chart with 5 data points and a colour-coded "Normal/Inverted" label
- Right: 5-year history with 5 coloured lines (orange=2Y, amber=5Y, green=10Y, blue=20Y, purple=30Y)

Hover over each chart to confirm tooltips work. Check that the historical chart renders without performance issues (thinning keeps it to ~260 points).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CrossAssetTab.js
git commit -m "feat: add gilt yield curve snapshot and history charts to cross-asset tab"
```

---

## Task 6: Clean up and final verification

**Files:**
- Modify: `backend/market.py` — remove unused `_fetch_boe_gilt_yields` stub if any old version remains

- [ ] **Step 1: Confirm no stale gilt references remain in `_compute_cross_asset`**

Search `market.py` for `gilt_2y` or `gilt_10y` in the `_compute_cross_asset` function. They should not be there. If found, remove them.

- [ ] **Step 2: Confirm the sidebar still works**

The sidebar uses `_cached("fear_greed", ...)` and `_cached("sidebar", ...)` — neither touches gilt yields. Reload the app and confirm the sidebar shows correctly with no errors.

- [ ] **Step 3: Final commit**

```bash
git add backend/market.py frontend/src/components/CrossAssetTab.js
git commit -m "feat: gilt yield curve complete — BoE IADB fetch, snapshot and history charts"
```
