-- Forward valuation multiple on High Impact RNS showcase entries.
--
-- Feasibility study (2026-07-08): ~60% of showcased trading updates state a
-- concrete full-year profit figure (guidance, or a consensus footnote in the
-- full RNS text). The LLM does EXTRACTION ONLY — metric, value, currency,
-- period, verbatim quote — and Python computes the multiple from our own
-- market_cap/net_debt (ttm_financials), so no LLM arithmetic is ever shown.
-- All columns NULLable: entries with no stated figure simply show nothing.
--
-- Idempotent: safe to re-run. Apply with:
--   python backend/run_migration.py migrations/013_fwd_multiple.sql

ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_metric       TEXT;        -- 'ebitda' | 'ebit' | 'pbt'
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_value        NUMERIC;     -- stated figure, absolute £ (low end of a range)
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_currency     TEXT;        -- as stated in the RNS; only GBP figures produce a multiple
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_period       TEXT;        -- e.g. 'FY2026'
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_basis        TEXT;        -- 'guidance' | 'consensus' | 'actual'
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_is_bound     BOOLEAN;     -- TRUE when "ahead of consensus X" → multiple is an upper bound
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_quote        TEXT;        -- verbatim sentence the figure came from (audit/tooltip)
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_ev           NUMERIC;     -- numerator used, absolute £ (EV for ebitda/ebit, mkt cap for pbt)
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_multiple     NUMERIC;     -- fwd_ev / fwd_value; NULL when any gate failed
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_model        TEXT;        -- extraction model id
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS fwd_processed_at TIMESTAMPTZ; -- when extraction last ran (set even when nothing was found)
