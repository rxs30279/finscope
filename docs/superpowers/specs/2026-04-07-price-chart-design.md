# Price Chart Design Spec

**Date:** 2026-04-07
**Feature:** Per-company stock price chart with MA overlays and range selector

---

## Goal

Show a price chart when a user clicks on a company. The Chart tab is the default view. Price data is automatically topped up to today when the chart loads.

---

## Backend

### New endpoint 1: `POST /api/prices/refresh/{symbol}`

- **Location:** `backend/prices.py`
- Checks latest stored date for that symbol in `price_history`
- If behind today, fetches missing closes via yfinance (`_fetch_closes` with `[symbol]` and `start = latest + 1 day`)
- Upserts new rows; returns `{"rows_added": N}`
- If already up to date, returns `{"rows_added": 0}` immediately (no yfinance call)

### New endpoint 2: `GET /api/prices/{symbol}`

- **Location:** `backend/prices.py`
- Query: `SELECT date, close FROM price_history WHERE symbol = %s ORDER BY date ASC`
- Response: `[{"date": "2023-04-11", "close": 321.65}, ...]`
- 404 if no rows found

---

## Frontend

### Tab change

- `'chart'` added as first item in `tabs` array in `CompanyDetail`
- Initial `tab` state changes from `'overview'` to `'chart'`

### `PriceChart` component

Inline in `App.js`, consistent with existing component pattern.

**Props:** `symbol` (string)

**State:**

| Name | Default | Purpose |
|------|---------|---------|
| `priceData` | `[]` | Full close history `[{date, close}]` |
| `loading` | `true` | Show spinner while fetching |
| `range` | `'1Y'` | Selected time range |
| `showMA20` | `true` | Toggle 20-day MA line |
| `showMA50` | `true` | Toggle 50-day MA line |

**Load sequence on mount / symbol change:**
1. Set `loading = true`
2. `POST /api/prices/refresh/{symbol}` — tops up missing days (fast)
3. `GET /api/prices/{symbol}` — fetch full history
4. Set `priceData`, `loading = false`

**MA computation:**
- Computed over the **full** `priceData` before range slicing so MAs are accurate at the left edge
- Standard rolling mean: MA_n at index i = mean of `close[i-n+1..i]`
- Points with fewer than n predecessors → `null` (Recharts skips with `connectNulls={false}`)

**Range filtering:**
- Applied after MA computation; slices `priceData` to cutoff date

| Button | Cutoff |
|--------|--------|
| 1M | 30 days before latest date |
| 3M | 90 days |
| 6M | 180 days |
| 1Y | 365 days |
| 3Y | 1095 days |
| All | no cutoff |

**Chart:**
- Recharts `AreaChart`
- Price: area with indigo gradient fill (`#6366f1`), matching existing chart gradients
- MA20: `Line`, amber `#f59e0b`, `dot={false}`, `strokeWidth={1.5}`, `strokeDasharray="4 2"`
- MA50: `Line`, purple `#a855f7`, `dot={false}`, `strokeWidth={1.5}`
- `XAxis`: date string, `interval="preserveStartEnd"`
- `YAxis`: auto-domain
- `Tooltip`: shows date, close, and any visible MAs
- No `CartesianGrid` — matches revenue/EBITDA chart style

**Controls (rendered above chart):**
- Range pills: `1M 3M 6M 1Y 3Y All` — active state highlighted in indigo
- MA toggle pills: `MA20` `MA50` — highlighted when active

**Loading/error:**
- Loading: centred "Loading…" text in chart area height
- No data: "No price history available"

---

## File Map

| File | Change |
|------|--------|
| `backend/prices.py` | Add `POST /api/prices/refresh/{symbol}` and `GET /api/prices/{symbol}` |
| `frontend/src/App.js` | Add `PriceChart` component, add Chart as default tab |

---

## Out of Scope

- Volume bars (not stored in DB)
- Candlestick chart
- Comparison vs index
- Drawing tools or annotations
