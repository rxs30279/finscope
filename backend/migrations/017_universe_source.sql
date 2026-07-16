-- 017: universe_source — who owns each company_metadata row's lifecycle.
--
-- The universe is growing beyond the four HL-scraped FTSE tiers (see
-- refresh_lse_universe.py): LSE-screened AIM/non-index names and hand-added
-- symbols must not be purged by the quarterly HL index refresh, which
-- hard-deletes anything absent from its four lists. Each refresh job now only
-- purges rows it owns:
--
--   hl_index   — from the HL FTSE 100/250/SmallCap/AIM 100 scrape
--                (refresh_index_membership.py owns inserts + purges)
--   lse_screen — from the LSE price-explorer screen, >=£50M non-fund UK names
--                (refresh_lse_universe.py owns inserts + purges, with
--                cap hysteresis: in at >=£50M, out below £40M)
--   manual     — added by hand; never auto-purged
--
-- No new table, so no RLS work (company_metadata is covered by migration 016).

ALTER TABLE company_metadata
    ADD COLUMN IF NOT EXISTS universe_source TEXT NOT NULL DEFAULT 'hl_index';

-- Every pre-existing row came from the HL index scrape, so the default is
-- already correct; the CHECK just keeps future writers honest.
-- (DROP first: ADD CONSTRAINT has no IF NOT EXISTS, and migrations must be
-- safe to re-run.)
ALTER TABLE company_metadata
    DROP CONSTRAINT IF EXISTS company_metadata_universe_source_check;
ALTER TABLE company_metadata
    ADD CONSTRAINT company_metadata_universe_source_check
    CHECK (universe_source IN ('hl_index', 'lse_screen', 'manual'));
