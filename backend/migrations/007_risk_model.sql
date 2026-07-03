-- Risk score v2: sector-aware models (see
-- docs/superpowers/specs/2026-07-03-risk-score-v2-design.md).
--
-- Each company now routes to one of six risk models (general / asset_heavy /
-- bank / insurer / financial / trust). The score itself stays 1-10 in
-- risk_score; this column records WHICH model produced it so the UI can label
-- the sub-metrics honestly — altman_z holds classic Z for "general" rows but
-- Z'' (different safe/distress bands) for "asset_heavy" rows, and is NULL for
-- the financial models and trusts.

ALTER TABLE screener_scores ADD COLUMN IF NOT EXISTS risk_model TEXT;
