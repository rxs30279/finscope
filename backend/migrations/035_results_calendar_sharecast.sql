-- Correct the results_calendar column comments after the source change.
--
-- Migrations 030 and 031 describe the Digital Look diary, which was the source
-- at the time and is left standing as the historical record. This corrects the
-- comments that live in the DB, where they are read as a description of the
-- CURRENT data rather than as history.
--
-- Digital Look went into an open-ended maintenance mode on 2026-08-16 (every
-- host on its estate 302s to a maintenance page, no ETA given) and the scraper
-- moved to the Sharecast company diary on 2026-08-17. Same underlying data
-- product re-skinned: identical section labels, and dates that agreed with
-- Digital Look on 97 of 97 shared symbols across the two weeks both covered.
--
-- Rows are NOT backfilled or relabelled. Pre-08-17 rows carry source='diary'
-- and came from Digital Look; post-08-17 rows carry source='diary' and come
-- from Sharecast. The two are not distinguished because the distinction stopped
-- being actionable the moment Digital Look became unreachable.
--
-- Comments only — no data or schema change. Idempotent. Apply with:
--   python backend/run_migration.py migrations/035_results_calendar_sharecast.sql

COMMENT ON COLUMN results_calendar.source IS
    'diary = the company diary scrape (primary; Sharecast since 2026-08-17, '
    'Digital Look before that); yfinance = FTSE 100 cross-check';

COMMENT ON COLUMN results_calendar.source_id IS
    'The source''s own key for the company: a Sharecast name slug, or a Digital '
    'Look numeric csi id on rows written before 2026-08-17. Free text, used only '
    'for tracing a row back to what produced it.';

COMMENT ON COLUMN results_calendar.source_name IS
    'Company name exactly as the diary printed it, before any cleaning. The '
    'natural key, since the diary exposes no ticker, and the only clue for '
    'improving the name resolver on rows that failed to match.';
