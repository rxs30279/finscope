-- UK consumer indicators — one row per (series, period). Populated by
-- backend/consumer.py via run_consumer.py (daily cron). Sources: ONS timeseries
-- JSON, Bank of England IADB, OECD SDMX, and the GfK/NIQ press release.
--
-- Generic long format rather than a column per metric: the series differ in
-- frequency (monthly vs quarterly) and unit (%, £m, index level, count), and a
-- wide table would need a new migration for every series added. Display labels
-- and units live in consumer.py's SERIES dict, not here.
--
-- `date` is the PERIOD START (2026 Q1 -> 2026-01-01, 2026 JUL -> 2026-07-01) so
-- charts can plot monthly and quarterly series on one time axis. `period` keeps
-- the source's own label for display ("2026 Q1", "Jul 2026").
--
-- Upserts are idempotent and self-healing — the cron re-fetches full history
-- each run, so a revised ONS figure overwrites the stale one.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/036_consumer_series.sql

CREATE TABLE IF NOT EXISTS consumer_series (
    series      text NOT NULL,
    date        date NOT NULL,
    period      text NOT NULL,
    value       double precision NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series, date)
);

CREATE INDEX IF NOT EXISTS consumer_series_series_date_idx
    ON consumer_series (series, date DESC);

-- New tables default to RLS off; the Data API must not expose this one
-- (see migrations/016_enable_rls.sql).
ALTER TABLE consumer_series ENABLE ROW LEVEL SECURITY;
