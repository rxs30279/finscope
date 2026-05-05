-- Breakout screener schema
-- Run this once against the Supabase database.

-- ── Daily breakout scores per stock ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS breakout_scores (
    symbol              TEXT NOT NULL,
    date                DATE NOT NULL,

    -- Individual algorithm scores (0-100, higher = stronger signal)
    algo_price_level    NUMERIC(5,1),   -- New N-day high breakout
    algo_consolidation  NUMERIC(5,1),   -- Bollinger squeeze / ATR compression
    algo_volume         NUMERIC(5,1),   -- Volume ratio confirmation
    algo_ma_cross       NUMERIC(5,1),   -- MA crossover / golden cross
    algo_volatility     NUMERIC(5,1),   -- Donchian/Keltner breakout
    algo_zscore         NUMERIC(5,1),   -- Statistical z-score breakout

    -- Composite
    breakout_score      NUMERIC(5,1),   -- Weighted composite 0-100
    layers_passed       INTEGER,        -- How many of the 6 layers met threshold

    -- Supporting metrics (for display & debugging)
    close               NUMERIC(10,4),
    volume              BIGINT,
    volume_ratio        NUMERIC(6,2),
    bb_width_pctile     NUMERIC(5,2),
    atr_pctile          NUMERIC(5,2),
    cmf_20d             NUMERIC(6,3),
    mfi_14d             NUMERIC(5,1),
    obv_trend           TEXT,           -- 'rising', 'flat', 'falling'
    vpt_trend           TEXT,
    ma_50d              NUMERIC(10,4),
    ma_200d             NUMERIC(10,4),
    n_day_high_20       NUMERIC(10,4),
    z_score             NUMERIC(6,3),

    PRIMARY KEY (symbol, date)
);

-- ── Filtered breakout signals (only stocks that triggered) ────────────────────
CREATE TABLE IF NOT EXISTS breakout_signals (
    symbol          TEXT NOT NULL,
    date            DATE NOT NULL,
    breakout_score  NUMERIC(5,1),
    layers_passed   INTEGER,
    PRIMARY KEY (symbol, date)
);

-- ── Backtest results ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS breakout_backtest (
    id              SERIAL PRIMARY KEY,
    signal_date     DATE NOT NULL,
    symbol          TEXT NOT NULL,
    breakout_score  NUMERIC(5,1),
    layers_passed   INTEGER,
    forward_5d      NUMERIC(6,3),   -- return after 5 trading days
    forward_10d     NUMERIC(6,3),   -- return after 10 trading days
    forward_20d     NUMERIC(6,3),   -- return after 20 trading days
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_breakout_scores_date ON breakout_scores (date DESC);
CREATE INDEX IF NOT EXISTS idx_breakout_scores_score ON breakout_scores (breakout_score DESC);
CREATE INDEX IF NOT EXISTS idx_breakout_scores_symbol ON breakout_scores (symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_breakout_signals_date ON breakout_signals (date DESC, breakout_score DESC);
CREATE INDEX IF NOT EXISTS idx_breakout_backtest_date ON breakout_backtest (signal_date DESC);
