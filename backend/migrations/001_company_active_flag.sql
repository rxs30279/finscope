-- Adds activity tracking to company_metadata so the daily price refresh can
-- stop querying delisted/suspended tickers.
--
-- yfinance prints "$XXX.L: possibly delisted; no price data found" for tickers
-- that no longer trade (ADIG.L, AUGM.L, BBH.L, JUST.L, LABS.L, THRG.L, …).
-- refresh_prices() increments empty_fetch_count each time a symbol comes back
-- empty and resets it to 0 when data is found. After _DEACTIVATE_AFTER
-- consecutive empty refreshes, is_active flips to false and the symbol is
-- dropped from the fetch universe. Reactivate manually with:
--   UPDATE company_metadata SET is_active = true, empty_fetch_count = 0
--   WHERE symbol = 'XXX.L';

ALTER TABLE company_metadata
    ADD COLUMN IF NOT EXISTS is_active        boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS empty_fetch_count integer NOT NULL DEFAULT 0;

-- Partial index keeps the "active universe" scan cheap as dead tickers pile up.
CREATE INDEX IF NOT EXISTS idx_company_metadata_active
    ON company_metadata (symbol) WHERE is_active;
