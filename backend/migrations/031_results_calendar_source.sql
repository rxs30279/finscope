-- Provenance for results_calendar rows.
--
-- Until now every row came from the Digital Look diary. That source is accurate
-- about DATES (96.8% over a five-week back-test) but silently omits companies
-- outright — Aviva's 14 Aug 2026 interims were absent from every diary week from
-- 20 Jul to 31 Aug, despite the same source carrying Aviva's Aug 2025 interims
-- and Mar 2026 finals. A missing row is indistinguishable from a quiet day, so
-- the omission only surfaced when a user noticed a FTSE 100 blue chip reporting
-- off-calendar.
--
-- yfinance's `Ticker.calendar` now backfills the FTSE 100 (see
-- results_calendar.fetch_index_earnings_dates). Measured 2026-08-14: 84/100
-- carry a date, and back-testing the 59 already-elapsed ones against the results
-- RNS gave 35 exact-day / 2 within-a-day / 0 wrong-by-more out of 37 judgeable.
--
-- This column exists so a row's origin is answerable after the fact. The two
-- sources have different failure modes and will need telling apart when the next
-- one drifts.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/031_results_calendar_source.sql

ALTER TABLE results_calendar
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'diary';

COMMENT ON COLUMN results_calendar.source IS
    'diary = Digital Look company diary (primary); yfinance = FTSE 100 cross-check';

-- Existing rows predate the cross-check and are all diary-sourced, which the
-- DEFAULT already gave them. No backfill needed.
