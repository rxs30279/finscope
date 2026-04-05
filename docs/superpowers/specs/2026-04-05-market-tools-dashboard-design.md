# Market Tools Dashboard — Design Spec
**Date:** 2026-04-05  
**Status:** Approved

---

## Overview

Add a multi-tool market analysis dashboard to the existing UK stock screener. The current app (FastAPI + React + PostgreSQL) gains five navigation tabs, a persistent sidebar, and a suite of momentum, breadth, and cross-asset tools for selecting UK stocks.

All new market data is sourced from Yahoo Finance via the `yfinance` Python library. Computation happens entirely on the backend. The frontend receives pre-computed results and renders them.

---

## Architecture

### Backend additions (FastAPI)

Six new endpoint groups added to `backend/main.py` (or split into `backend/market.py` and included via `app.include_router`):

| Endpoint | Description |
|---|---|
| `GET /api/market/sidebar` | 11 ICB sector % changes, FTSE 100/250/All-Share % changes, model signal summary (cycle phase, top RS sector, breadth reading, cross-asset bias) |
| `GET /api/market/rotation` | RS score per sector (sector price index / FTSE All-Share, 63-day rolling), trend direction (rising/falling based on 10-day RS slope), breadth per sector (% stocks above 50-day MA), BUY/AVOID signal per sector |
| `GET /api/market/breadth` | Market-wide % above 50-day MA, advance/decline counts, 52-week new highs count, 52-week new lows count, H/L ratio, A/D cumulative line (20 data points for chart) |
| `GET /api/market/cross-asset` | GBP/USD spot, UK 10Y gilt yield, Brent crude price, gold price, VFTSE volatility index, gilt-vs-utilities z-score spread |
| `GET /api/market/signals` | Timestamped signal log — events generated when thresholds are crossed (RS > 1.10, breadth > 65%, RS < 0.85, etc.) stored in-memory per session |
| `GET /api/market/cycle` + `POST /api/market/cycle` | GET returns current cycle phase and sector guidance. POST sets the phase manually (one of: Recovery, Expansion, Slowdown, Contraction) |

**Caching:** All `GET /api/market/*` endpoints (except `/cycle`) use a simple in-memory dict cache with a 15-minute TTL. Cache is invalidated on server restart. This prevents hammering yfinance on every tab switch.

**yfinance tickers used:**

| Instrument | Ticker |
|---|---|
| FTSE 100 | `^FTSE` |
| FTSE 250 | `^FT2MI` |
| FTSE All-Share | `^VUKE` (proxy) or `VUKE.L` |
| ICB sector proxies | iShares FTSE sector ETFs (e.g. `IENR.L`, `IUKF.L`, etc.) or constructed from constituent prices |
| GBP/USD | `GBPUSD=X` |
| UK 10Y Gilt Yield | `^TNX` fallback to `GB10YT=RR` |
| Brent Crude | `BZ=F` |
| Gold | `GC=F` |
| VFTSE / UK Vol | `^VFTSE` |

> **Note:** yfinance ticker availability for UK sector indices should be validated during implementation. Fallback: compute sector performance from constituent stocks already in the PostgreSQL `company_metadata` table grouped by ICB sector.

### Frontend additions (React)

**New components:**
- `<Sidebar>` — persistent left panel (180px wide), rendered on all tabs. Fetches from `/api/market/sidebar` on mount and on manual refresh.
- `<Header>` — updated to include five nav tabs (Screener, Rotation, Breadth, Cross-Asset, Signals), last-updated timestamp, and Refresh button.
- `<RotationTab>` — sector heatmap grid + business cycle wheel + RS ranking table.
- `<BreadthTab>` — semicircle needle gauge + 52-week highs/lows card + A/D line chart.
- `<CrossAssetTab>` — six KPI cards (GBP/USD, gilt yield, crude, gold, volatility, gilt-vs-utilities spread).
- `<SignalsTab>` — timestamped event feed with BUY / AVOID / ALERT / INFO badge types.

**Shared data fetching:**  
Each tab fetches its own endpoint independently on mount. No global state store — keep it simple with `useState` + `useEffect` per component, matching the existing pattern in `App.js`.

**No real-time polling.** Data is fetched on tab mount and on manual Refresh button click. A "Last updated HH:MM" label appears in the header.

---

## Component Details

### Sidebar
- **Benchmarks section:** FTSE 100, FTSE 250, All-Share — each with a green/amber/red % change badge.
- **ICB Sectors section:** All 11 sectors listed with % change badges. Colour scale: green (> +0.5%), amber (−0.5% to +0.5%), red (< −0.5%).
- **Model Signal box:** Compact summary card showing cycle phase, breadth reading, top RS sector, and cross-asset bias.

### Rotation Tab
- **Sector heatmap:** 3×4 grid of sector tiles, colour intensity proportional to RS rank (deep green #1, deep red #11). Each tile shows rank badge, sector name, and day % change.
- **Business cycle wheel:** SVG dial with four quadrants (Recovery, Expansion, Slowdown, Contraction). Needle points to current phase. "Set Phase" dropdown allows manual override. Sector guidance text shown below wheel (favour/avoid lists per phase).
- **RS ranking table:** All 11 sectors ranked 1–11 by RS score. Columns: Rank, Sector, RS Score (2dp), Trend (↑ Rising / ↓ Falling), Breadth (% above 50MA), Signal (BUY / AVOID / NEUTRAL badge).

### Breadth Tab
- **Needle gauge:** SVG semicircle gauge, red→amber→green gradient arc, needle pointing to current % above 50-day MA value. Label below: Bearish (<40%), Neutral (40–60%), Bullish (>60%).
- **Advance/Decline counts:** Advancing, Declining, Unchanged stock counts for today.
- **52-week highs/lows:** New highs count, new lows count, H/L ratio.
- **A/D line chart:** 20-day cumulative A/D line vs FTSE All-Share (dashed), using Recharts `LineChart`.

### Cross-Asset Tab
- Six metric cards in a 3×2 grid: GBP/USD, 10Y Gilt Yield, Brent Crude, Gold, VFTSE, Gilt vs Utilities Spread.
- Each card: metric name, current value, day change with directional arrow, and a short bias label (e.g. "Bearish", "Risk-On").
- **Gilt vs Utilities spread:** z-score of (gilt yield − utilities sector dividend yield) over 252 trading days. Negative z-score means gilts expensive relative to utilities (bearish for utilities as bond proxy).

### Signals Tab
- Scrollable event feed, newest first.
- Each entry: timestamp, badge type (BUY green / AVOID red / ALERT amber / INFO blue), description text.
- Signals are generated server-side when thresholds are crossed:
  - RS score crosses above 1.05 → BUY signal for that sector
  - RS score crosses below 0.95 → AVOID signal for that sector
  - Market breadth crosses above 65% → ALERT (bullish breadth)
  - Market breadth falls below 40% → ALERT (bearish breadth)
  - Cycle phase manually changed → INFO entry
- Signal log persists in-memory on the backend for the server session.

### Business Cycle Phase Guidance
| Phase | Favour | Avoid |
|---|---|---|
| Recovery | Energy, Financials, Materials, Industrials | Utilities, Consumer Staples |
| Expansion | Technology, Consumer Discretionary, Industrials | Health Care, Utilities |
| Slowdown | Health Care, Consumer Staples, Utilities | Energy, Materials, Financials |
| Contraction | Utilities, Consumer Staples, Health Care | Energy, Financials, Technology |

---

## Data Flow

```
User opens tab
  → React component mounts
  → fetch(/api/market/<endpoint>)
  → FastAPI checks in-memory cache (15min TTL)
      → cache hit: return cached JSON
      → cache miss: call yfinance, compute metrics, cache, return JSON
  → React renders computed data
```

---

## RS Score Calculation

Relative Strength score for each sector = `sector_price_63d_return / ftse_allshare_63d_return`

- A score > 1.0 means the sector has outperformed the market over 63 trading days (~3 months)
- Trend direction: compare current RS score to RS score 10 trading days ago. Rising if current > prior.
- BUY signal: RS > 1.05 AND trend = Rising
- AVOID signal: RS < 0.95 AND trend = Falling
- NEUTRAL: everything else

---

## Error Handling

- If yfinance returns no data for a ticker, the endpoint returns `null` for that field — the frontend renders `—` (matching existing `fmt()` utility behaviour).
- If the entire yfinance call fails, the endpoint returns a 503 with `{"error": "market data unavailable"}`. The frontend shows a non-blocking error banner.
- The existing screener and company detail views are completely unaffected by any failure in the new endpoints.

---

## Out of Scope

- Real-time WebSocket price streaming
- Historical signal log persistence (signals reset on server restart)
- Automated cycle phase detection (manual only for now)
- Individual stock RS scores (sector-level only)
- Push notifications or alerts

---

## File Changes

**Backend:**
- `backend/main.py` — add cache utility, import yfinance, add 6 new route groups (or extract to `backend/market.py`)
- `backend/requirements.txt` — add `yfinance`

**Frontend:**
- `frontend/src/App.js` — add tab state, render Sidebar + Header + tab components
- `frontend/src/components/Sidebar.js` — new
- `frontend/src/components/RotationTab.js` — new
- `frontend/src/components/BreadthTab.js` — new
- `frontend/src/components/CrossAssetTab.js` — new
- `frontend/src/components/SignalsTab.js` — new

**Config:**
- `.gitignore` — add `.superpowers/`
