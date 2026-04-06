# Price History & Momentum Score — Design Spec

**Date:** 2026-04-06
**Status:** Approved

## Overview

Add a `price_history` table to the existing Supabase/PostgreSQL database, populate it via yfinance, and use it to compute a 12-1 month momentum score (1–10) displayed as a new column in the stock screener table.

---

## 1. Database

### Table: `price_history`

```sql
CREATE TABLE price_history (
    symbol   TEXT    NOT NULL,
    date     DATE    NOT NULL,
    close    NUMERIC NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX ON price_history (symbol, date DESC);
```

- Stores adjusted daily closes only — no volume, OHLC, or other fields needed for this feature.
- Primary key `(symbol, date)` prevents duplicates; upserts use `ON CONFLICT DO NOTHING`.
- Index on `(symbol, date DESC)` makes per-symbol lookups fast.
- Target size: 531 stocks × ~750 trading days (3 years) ≈ 370,000 rows.

### History depth

3 years of daily closes per stock. Stocks with fewer than 252 stored trading days receive a `null` momentum score (shown as `—` in the UI).

---

## 2. Update Mechanism

### New module: `backend/prices.py`

Registered as a FastAPI router at `/api/prices`.

### Endpoint: `POST /api/prices/refresh`

**Flow:**
1. Query `SELECT symbol, MAX(date) AS latest FROM price_history GROUP BY symbol` to find each stock's most recent stored date.
2. For stocks with no history: fetch 3 years of data. For stocks with existing history: fetch from `latest_date + 1` to today.
3. Group symbols by their fetch-from date to minimise yfinance API calls (yfinance supports multi-ticker batch downloads via `yf.download(tickers, start, end)`).
4. Batch upsert results into `price_history` using `INSERT ... ON CONFLICT DO NOTHING`.
5. Return `{ "updated": <n_symbols>, "rows_added": <n_rows>, "duration_seconds": <t> }`.

**Notes:**
- Runs synchronously — acceptable since this is an explicit user-triggered action, not per page load.
- The initial run (all 531 stocks, 3 years) will take ~60–120 seconds. Subsequent runs fetch only new dates and complete in seconds.
- yfinance uses `.L` suffixed tickers (e.g. `SHEL.L`) consistent with the existing `company_metadata` table.

---

## 3. Momentum Score

### Definition

**12-1 month momentum** using trading-day approximations:

```
momentum_return = (close_63_days_ago / close_252_days_ago) - 1
```

- `252 trading days ago` ≈ 12 months (start of window)
- `63 trading days ago` ≈ 3 months (end of window, excludes recent reversal)
- Using a 3-month exclusion rather than 1-month to account for lower UK small/mid-cap liquidity

### Scoring

Raw returns are **ranked percentile** within the screener result universe and mapped to a 1–10 integer score:

| Percentile rank | Score |
|---|---|
| Top 10% | 10 |
| 80–90% | 9 |
| … | … |
| Bottom 10% | 1 |

Ranking is relative to the current screener results (respects any active filters). A score of 7 means better momentum than 70% of the currently visible stocks.

Stocks with fewer than 252 days of price history receive `null` (displayed as `—`).

### Implementation: `_attach_momentum(results)`

Same pattern as `_attach_piotroski`. After the screener SQL runs:
1. Extract symbols from results.
2. Single SQL query fetches the two required price points per symbol from `price_history`.
3. Compute raw returns in Python.
4. Rank and convert to 1–10 score.
5. Attach `momentum_score` to each result dict.

---

## 4. Screener Integration

### Backend (`backend/main.py`)

- Import and call `_attach_momentum(results)` in the screener endpoint alongside the existing `_attach_piotroski` call.
- No changes to the screener SQL query itself.

### Frontend (`frontend/src/App.js`)

- Add `Momentum` column to the screener table headers and rows.
- Same green (7–10) / amber (4–6) / red (1–3) / grey (`—`) colour scheme as Quality and Value columns.
- Add a "Refresh Prices" button in the nav bar next to the existing `↻` refresh button.
  - On click: calls `POST /api/prices/refresh`, shows a loading spinner, displays a brief success/error toast on completion.
  - Button is disabled while refresh is in progress.

---

## 5. Files Affected

| File | Change |
|---|---|
| `backend/prices.py` | New — FastAPI router with `/refresh` endpoint and `_attach_momentum` helper |
| `backend/main.py` | Import prices router; call `_attach_momentum` in screener endpoint |
| `frontend/src/App.js` | Add Momentum column; add Refresh Prices button |

---

## 6. Out of Scope

- Price charts on company detail pages (future feature — data will be available)
- Scheduled/automatic price updates (on-demand only for now)
- Intraday prices
- Volume data
