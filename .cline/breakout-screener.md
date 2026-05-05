# Breakout Screener — Build Summary

## Date

2026-05-05

## What was built

### 1. Backend: `backend/breakout.py`

- **6 breakout algorithms** computed from daily OHLCV data:
  1. **Price Level** (`algo_price_level`) — Close above 20-day/52-day high
  2. **Consolidation** (`algo_consolidation`) — Bollinger squeeze, ATR compression, NR7/NR4
  3. **Volume** (`algo_volume`) — Volume ratio > 1.5x, declining volume during base, accumulation
  4. **MA Cross** (`algo_ma_cross`) — Price > 50/200 MA, golden cross
  5. **Volatility** (`algo_volatility`) — Donchian/Keltner channel breakouts
  6. **Z-Score** (`algo_zscore`) — Statistical outlier detection (2-3 sigma)
- **Composite score** — Weighted combination of 6 layers (trend_filter 15%, consolidation 20%, accumulation 20%, money_flow 20%, breakout_trigger 15%, volume_confirm 10%)
- **Backtesting engine** — Looks forward 5/10/20 trading days from each signal
- **API endpoints** (registered in `main.py` and `render_app.py`):
  - `POST /api/breakout/run` — Run computation for latest trading day
  - `POST /api/breakout/backfill` — Backfill historical data
  - `GET /api/breakout/signals` — Get today's signals with filters
  - `GET /api/breakout/history/{symbol}` — Historical scores for one stock
  - `GET /api/breakout/summary` — Aggregate stats
  - `GET /api/breakout/backtest` — Backtest results
  - `GET /api/breakout/backtest/stats` — Backtest stats by score range

### 2. Database: `backend/breakout_schema.sql`

- **`breakout_scores`** — Daily per-stock snapshot with all 6 algo scores + composite + supporting metrics (CMF, MFI, OBV trend, VPT trend, BB width percentile, ATR percentile)
- **`breakout_signals`** — Filtered view (only stocks with composite >= 50)
- **`breakout_backtest`** — Forward returns at 5/10/20 trading days

### 3. Frontend: `frontend/src/components/BreakoutTab.js`

- Dark-themed monitoring dashboard
- Sortable table with all 6 algo columns + composite score
- Color-coded scores (green >= 7, amber >= 4, red < 4)
- Click a stock to view breakout history chart
- History view shows composite score trend over time
- "Run Now" button to trigger on-demand computation
- Last-run timestamp display
- Wired into `App.js` navigation

### 4. Integration

- Routes registered in `backend/main.py` and `backend/render_app.py`
- Nav button "Breakouts" added in `App.js`
- Build compiles successfully (185 kB gzipped)

## Bugs fixed during testing

1. **Import path** — Changed `from prices import query` to `from backend.prices import query` (when running from project root)
2. **Numpy type conversion** — Added `_to_native()` helper to convert numpy float64/int64 to native Python types before passing to psycopg2

## Test results

- **631 stocks processed** in 16.5 seconds
- Data stored in Supabase (`breakout_scores` table)
- No signals triggered on May 5 (market closed — expected)
- Top score: SEE.L at 38.3 (2 layers passed)
- Average composite score across all stocks: 10.3

## How to run

```bash
# Run migration (one-time)
python _run_migration.py

# Run breakout computation
python -c "from backend.breakout import run_breakout; print(run_breakout())"

# Backfill historical data (60 days)
python -c "from backend.breakout import run_backfill; print(run_backfill(60))"

# Check results
python _check_breakout.py
```

## Files created/modified

- `backend/breakout.py` — NEW (main engine)
- `backend/breakout_schema.sql` — NEW (DB schema)
- `backend/main.py` — MODIFIED (added router include)
- `backend/render_app.py` — MODIFIED (added router include)
- `frontend/src/components/BreakoutTab.js` — NEW (UI)
- `frontend/src/App.js` — MODIFIED (added nav + route)
- `_run_migration.py` — NEW (migration script)
- `_check_breakout.py` — NEW (verification script)
- `.cline/breakout-screener.md` — THIS FILE
