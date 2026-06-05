-- Precomputed per-symbol screener scores.
--
-- The /api/screener endpoint used to compute momentum, Piotroski and risk
-- scores on every (uncached) request, firing four extra DB round-trips — two
-- redundant scans of annual_financials and two of price_history (the heaviest
-- shipping ~250k price rows to Python just to compute volatility). Those inputs
-- only change once a day, so compute_and_store_scores() in main.py now fills
-- this table once daily (right after the price refresh) and the endpoint serves
-- the scores via a single LEFT JOIN instead.
--
-- quality_score and pegy are NOT stored here: they derive purely from columns
-- already present in the screener's main JOIN, so they add no extra query and
-- stay computed inline (avoids staleness).

CREATE TABLE IF NOT EXISTS screener_scores (
    symbol                TEXT PRIMARY KEY,
    momentum_score        integer,
    piotroski_score       integer,
    risk_score            integer,
    altman_z              double precision,
    volatility_annualised double precision,
    computed_at           timestamptz NOT NULL DEFAULT now()
);

-- Indexes the daily precompute job relies on. They are NOT defined elsewhere in
-- the repo (price_history / annual_financials were created directly in
-- Supabase), so create them here if missing — without them the per-symbol
-- ROW_NUMBER() scans degrade to sequential scans.
CREATE INDEX IF NOT EXISTS idx_price_history_symbol_date
    ON price_history (symbol, date DESC);

CREATE INDEX IF NOT EXISTS idx_annual_financials_symbol_date
    ON annual_financials (company_symbol, period_end_date DESC);
