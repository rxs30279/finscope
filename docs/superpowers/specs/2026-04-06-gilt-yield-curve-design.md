# Gilt Yield Curve — Design Spec
**Date:** 2026-04-06

## Overview
Add a UK Gilt Yield Curve section to the existing Cross-Asset tab. Shows two charts:
1. Current yield curve shape (today's snapshot across 5 maturities)
2. Historical time series (5 years of daily yields, one line per maturity)

Data sourced from the Bank of England IADB (Interactive Database) public API. No auth required.

---

## Maturities
2Y, 5Y, 10Y, 20Y, 30Y — UK nominal spot gilt yields.

---

## Backend

### New endpoint: `GET /api/market/gilt-yields`

**Function:** `_fetch_boe_gilt_yields()`

Fetches 5 years of daily nominal spot gilt yields from the BoE IADB for each of the 5 maturities. One HTTP request per maturity series.

**BoE IADB URL format:**
```
https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp
  ?Travel=NIxRSx&C={SERIES_CODE}&DAT=RNG&VFD=Y
  &CSVF=TT&UsingCodes=Y
  &FD=1&FM=Jan&FY=2021&TD=31&TM=Dec&TY=2026
```

**Series codes** (to be confirmed during implementation — nominal spot yields):
- 2Y: `IUDSNS02` (or similar pattern)
- 5Y: `IUDSNS05`
- 10Y: `IUDSNS10`
- 20Y: `IUDSNS20`
- 30Y: `IUDSNS30`

> Note: Exact series codes are the primary implementation unknown. Will be tested at startup and corrected if needed.

**Return shape:**
```python
{
  "snapshot": {2: 4.12, 5: 4.35, 10: 4.61, 20: 4.89, 30: 4.95},
  "history": [
    {"date": "2021-01-04", "y2": 0.05, "y5": 0.31, "y10": 0.28, "y20": 0.72, "y30": 0.82},
    ...
  ]
}
```

**Cache TTL:** 4 hours (BoE publishes once per business day).

**Error handling:**
- Any fetch failure returns `{"snapshot": {}, "history": []}` — no crash
- Missing individual maturities are omitted rather than blocking the whole response
- Weekends/bank holidays: IADB naturally returns the most recent published value

---

## Frontend

### Placement
Below existing asset cards in `CrossAssetTab.js`. New section with title "UK Gilt Yield Curve".

### Chart 1 — Yield Curve Snapshot (40% width)
- Type: Line chart (Recharts `LineChart`)
- X axis: maturity labels — `2Y`, `5Y`, `10Y`, `20Y`, `30Y`
- Y axis: yield % (e.g. 3.5 – 5.5 range, auto-scaled)
- Single line connecting the 5 points
- Colour: green (`#10b981`) if curve is normal (30Y > 2Y), red (`#ef4444`) if inverted (2Y > 30Y)
- Tooltip showing exact yield on hover
- Reference annotation for curve shape: "Normal", "Flat", or "Inverted" label

### Chart 2 — Historical Time Series (60% width)
- Type: Line chart (Recharts `LineChart`)
- X axis: date (5 years of daily data, formatted as `MMM YY`)
- Y axis: yield %
- 5 lines, one per maturity, distinct colours:
  - 2Y: `#f97316` (orange)
  - 5Y: `#f59e0b` (amber)
  - 10Y: `#10b981` (green)
  - 20Y: `#60a5fa` (blue)
  - 30Y: `#a78bfa` (purple)
- Legend showing maturity labels
- Tooltip on hover showing all 5 yields for that date

### Loading / error states
- Section shows `—` placeholders if data is null
- Consistent with existing CrossAssetTab card styling (dark background, monospace font)

---

## Data flow
```
CrossAssetTab mounts
  → useEffect fetches /api/market/gilt-yields
  → backend _cached("gilt_yields", _fetch_boe_gilt_yields)
    → BoE IADB HTTP requests (5 series, concurrent)
    → parse CSV, build snapshot + history
    → cache for 4 hours
  → frontend renders snapshot chart + history chart
```

---

## Out of scope
- Real yield curve (index-linked gilts)
- Forward rates
- Yield spread calculations (e.g. 2s10s) — can be added later
- Moving the gilt section to its own tab
