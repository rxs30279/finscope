-- Daily Fear & Greed history — one row per calendar day holding the UK index
-- (computed in market.py from our own price-derived components) alongside the
-- US CNN Fear & Greed value (pulled from CNN's graphdata endpoint).
--
-- Why this table exists: the UK index was previously computed in-memory on every
-- request (only the last 4 readings were retained) and the CNN value was fetched
-- live as a single current number. Neither was persisted, so a rolling-year
-- chart had no history to draw. This table is (re)built daily by the
-- finscope-prices Render cron via market._rebuild_fear_greed_history(), which
-- upserts a full trailing year for both series — so re-runs are idempotent and
-- self-healing, and a row once written is never dropped (history only extends).

CREATE TABLE IF NOT EXISTS fear_greed_history (
    date        date PRIMARY KEY,
    uk_score    integer,
    us_score    double precision,
    computed_at timestamptz NOT NULL DEFAULT now()
);
