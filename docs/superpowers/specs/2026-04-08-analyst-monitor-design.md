# Analyst Monitor — Design Spec

**Date:** 2026-04-08
**Status:** Approved

## Overview

Add analyst consensus monitoring to the stock screener tool. Daily snapshots of Yahoo Finance analyst data are stored in PostgreSQL and surfaced in three places: the screener table, individual stock detail view, and a dedicated Analyst Monitor page. The goal is to track consensus sentiment, price targets, EPS estimates, and revision trends over time for UK-listed stocks.

## Data Source

**Yahoo Finance via `yfinance`** (free, already a project dependency).

UK stocks return the following analyst endpoints:
- `ticker.recommendations` — monthly consensus counts (strongBuy, buy, hold, sell, strongSell) for current month and prior 3 months
- `ticker.analyst_price_targets` — aggregate price target: current, high, low, mean, median
- `ticker.earnings_estimate` — EPS estimates for current quarter, next quarter, current year, next year
- `ticker.revenue_estimate` — revenue estimates for current year and next year
- `ticker.eps_revisions` — count of upward/downward revisions in last 7 and 30 days
- `ticker.growth_estimates` — EPS growth estimates for current and next year

**Not available for UK stocks:** firm-level upgrade/downgrade history (returns 404 for `.L` tickers). Consensus aggregate only.

## Data Model

Single flat table — one row per stock per day. Derived fields computed at write time.

```sql
CREATE TABLE analyst_snapshots (
    id                       SERIAL PRIMARY KEY,
    symbol                   VARCHAR     NOT NULL,
    snapshot_date            DATE        NOT NULL,

    -- Consensus (from recommendations)
    strong_buy               INT,
    buy                      INT,
    hold                     INT,
    sell                     INT,
    strong_sell              INT,
    total_analysts           INT,
    consensus                VARCHAR,    -- 'Buy', 'Hold', 'Sell'
    buy_pct                  NUMERIC,    -- (strong_buy + buy) / total * 100

    -- Price targets (from analyst_price_targets)
    price_target_mean        NUMERIC,
    price_target_high        NUMERIC,
    price_target_low         NUMERIC,
    price_target_median      NUMERIC,
    current_price            NUMERIC,    -- price at snapshot time
    upside_pct               NUMERIC,    -- (mean_target - current) / current * 100

    -- EPS estimates (from earnings_estimate)
    eps_est_current_q        NUMERIC,
    eps_est_next_q           NUMERIC,
    eps_est_current_yr       NUMERIC,
    eps_est_next_yr          NUMERIC,

    -- Revenue estimates (from revenue_estimate)
    rev_est_current_yr       NUMERIC,
    rev_est_next_yr          NUMERIC,

    -- EPS revisions (from eps_revisions)
    revisions_up_7d          INT,
    revisions_down_7d        INT,
    revisions_up_30d         INT,
    revisions_down_30d       INT,
    revision_score           INT,        -- revisions_up_30d - revisions_down_30d

    -- Growth estimates (from growth_estimates)
    eps_growth_current_yr    NUMERIC,
    eps_growth_next_yr       NUMERIC,

    fetched_at               TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (symbol, snapshot_date)
);

CREATE INDEX ON analyst_snapshots (symbol, snapshot_date DESC);
```

**Consensus derivation:**
- `buy_pct >= 60%` → `'Buy'`
- `(strong_sell + sell) / total >= 40%` → `'Sell'`
- Otherwise → `'Hold'`
- If `total_analysts = 0` or data unavailable → `NULL`

**Data volume:** ~400 stocks × 365 days ≈ 146k rows/year. No partitioning needed.

## Backend

### New file: `backend/analysts.py`

FastAPI router (`/api/analysts`) with four endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/analysts/{symbol}` | Full snapshot history for one stock, ordered by date ASC. Used by stock detail view. |
| `GET /api/analysts/latest` | Latest snapshot per stock via `DISTINCT ON (symbol) ORDER BY snapshot_date DESC`. Used by screener and monitor page. |
| `GET /api/analysts/changes` | Stocks where `consensus` changed or `upside_pct` shifted >5 points between the two most recent snapshots. Used by the change feed. |
| `POST /api/analysts/refresh` | Triggers a full refresh in a background thread. Returns `{"status": "refresh started"}` immediately. |

Router registered in `main.py` alongside existing `market_router` and `prices_router`.

### New file: `backend/refresh_analysts.py`

Standalone script — can be run directly (`python refresh_analysts.py`) or called by the refresh endpoint.

**Steps:**
1. Load all symbols from `company_metadata`
2. Fetch in parallel: `ThreadPoolExecutor(max_workers=10)`, same pattern as `market.py`
3. Per stock: call 6 yfinance properties, parse, derive computed fields, build upsert row
4. Upsert into `analyst_snapshots` using `ON CONFLICT (symbol, snapshot_date) DO UPDATE`
5. Gracefully skip stocks that return no data or raise errors
6. Log summary: processed / skipped / errors

**Rate limiting:** 0.5s sleep between batches of 10 to avoid Yahoo rate limiting. Expected runtime: 5–8 minutes for ~400 stocks.

**Scheduling:** Configure Windows Task Scheduler to run `python refresh_analysts.py` nightly (e.g. 02:00). The script is self-contained and uses the same `.env` DB config as the rest of the backend.

### Screener changes (`main.py`)

`/api/screener` gains a `LEFT JOIN` to latest analyst snapshot:

```sql
LEFT JOIN (
    SELECT DISTINCT ON (symbol)
        symbol, consensus, buy_pct, upside_pct, total_analysts, revision_score
    FROM analyst_snapshots
    ORDER BY symbol, snapshot_date DESC
) a ON a.symbol = m.symbol
```

New response fields: `consensus`, `buy_pct`, `upside_pct`, `total_analysts`, `revision_score`

New optional query params: `consensus` (Buy/Hold/Sell), `min_upside_pct` (float)

## Frontend

### Screener table

Two new columns:
- **Consensus** — coloured badge: green `Buy`, amber `Hold`, red `Sell`. Hidden if NULL.
- **Upside** — `+18.4%` / `-3.2%` coloured green/red relative to mean analyst target.

New "Analyst" section in the advanced filter panel:
- Consensus dropdown: All / Buy / Hold / Sell
- Min Upside % input

### Stock Detail — "Analysts" tab

New tab added alongside Chart / Financials. Four panels:

1. **Consensus bar** — horizontal stacked bar (Strong Buy / Buy / Hold / Sell / Strong Sell), total analyst count, derived consensus label.
2. **Price target range** — linear visualisation: Low ··· [Current Price] ··· Mean ··· Median ··· High. Shows upside % to mean target.
3. **Consensus trend** — line chart of `buy_pct` over time from stored history. Reveals drift in analyst sentiment.
4. **Estimates & revisions** — grid: EPS and revenue estimates for current/next year; revision activity (e.g. ↑3 / ↓1 last 30 days).

### Analyst Monitor page

New top-level nav entry. Three sections:

**Signals board** (top)
- Top 5 Bullish: highest composite signal (high `buy_pct` + high `upside_pct` + positive `revision_score`)
- Top 5 Bearish: opposite composite signal
- Each card shows: symbol, company name, consensus badge, upside %, revision score

**Full table** (main body)
- All stocks with analyst data, columns: Symbol, Name, Consensus, Buy%, Upside%, Revision Score, # Analysts
- Sortable by all columns
- Text search to filter by name/symbol
- Same badge/colour treatment as screener

**Change feed** (right-side panel)
- Driven by `GET /api/analysts/changes`
- Shows stocks where consensus flipped or upside moved >5pts since previous snapshot
- Format: `AZN.L · Hold → Buy · Upside +22%` with date
- Empty state: "No significant changes since last refresh"

**Refresh button** in page header — calls `POST /api/analysts/refresh`, shows spinner, confirms when started.

## Error Handling

- yfinance fetch failures per stock are caught and logged; the stock is skipped for that day's snapshot
- Stocks with no analyst coverage (common for smaller FTSE stocks) are skipped gracefully — NULL analyst columns in screener are hidden, Analysts tab shows "No analyst data available"
- The refresh endpoint is fire-and-forget; errors during the background run are logged server-side only

## Out of Scope

- Firm-level upgrade/downgrade history (not available for UK stocks via yfinance)
- Individual named analyst predictions (not available via any free API for UK stocks)
- Email/push alerts on consensus changes (can be added later)
- EPS trend drift tracking (7/30/60/90 day estimate shifts) — available from `eps_trend` but deferred to keep first build focused
