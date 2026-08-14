-- Root-cause fix for the Hill & Smith "Sequential · derived by us" bug
-- reported 2026-08-14: annual_financials has no per-row currency, but a
-- company can switch its reporting currency. HILS.L moved GBP -> USD between
-- its FY2025 annual report (published ~March 2026, "revenue increasing by 2%
-- to £868.8 million") and its H1 2026 interim (published 2026-08-12, revenue
-- printed in dollars: "$606.7m").
--
-- gates.compute_sequential_base derives a preceding half as
--     latest_complete_fy_total - prior_year_half
-- where the FY total comes from annual_financials.revenue (still £868.8m,
-- never converted) and the half comes from the announcement's own
-- earnings_quality (now $561.1m). The subtraction silently mixed GBP and USD
-- and presented the $307.7m result as fact, both on the archive page and
-- inside the vet prompt (showcase._sequential_base_context).
--
-- annual_financials.currency lets gates._low_base_fy_series refuse to use a
-- row when it is POSITIVELY known to be in a different currency from the
-- announcement. NULL means "not yet known", not "matches" -- updater.py only
-- ever stamps a row's currency the first time that fiscal year is inserted
-- (never on UPDATE of an existing row), so a currency that changes after a
-- fiscal year has already been written can never silently overwrite it. This
-- keeps the fix "silence, never a guess": historical rows written before this
-- migration stay NULL (unknown) forever and are treated as before, rather
-- than guessed at.
--
-- HILS.L FY2025 is corrected by hand below -- a verified fact from the
-- company's own FY2025 announcement, not an inference -- so the one card that
-- prompted this fix stops showing a wrong number immediately rather than
-- waiting for FY2026 to close under the new schema.
--
-- Apply with:
--   python backend/run_migration.py migrations/034_annual_financials_currency.sql

ALTER TABLE annual_financials ADD COLUMN IF NOT EXISTS currency TEXT;

UPDATE annual_financials
SET currency = 'GBP'
WHERE company_symbol = 'HILS.L' AND fiscal_year = 2025 AND currency IS NULL;
