-- Persist the ranker's per-statement guidance enumeration so the High Impact
-- gate can act on it in Python. See docs/rns-body-context-plan.md, Phase 4.
--
-- Why this exists: with the body attached (migration 024) the ranker reliably
-- FINDS the disqualifying fact but unreliably reflects it in llm_score. Scored
-- 7 times at temperature 0.2, the LUCE 2026-07-28 announcement labelled FY2026
-- "> £40m vs consensus £40.7m" as reiterated in 7 of 7 runs — and then scored
-- 75/positive in 6 of 7, reasoning each time that a separate FY2027 upgrade
-- outweighed it. Across the same repeat sampling llm_score moved up to 30
-- points run to run, wider than the 75/80/85 band the showcase gates on. The
-- structured field is steady where the number is not, so
-- showcase.flag_high_impact_candidates gates on the field.
--
-- Shape: JSONB array, one object per forward-looking guidance statement in the
-- announcement:
--   {metric, period, guided_value, consensus_value, vs_prior, vs_consensus}
-- vs_prior     ∈ raised | reiterated | lowered | new | unknown
-- vs_consensus ∈ above | in_line | below | no_consensus_stated
-- The two axes are deliberately independent — a figure can be reiterated by the
-- company AND below a consensus that moved past it since, which is exactly the
-- LUCE failure. Do not collapse them back into one enum.
--
-- Stored as JSONB rather than normalised rows: it is read whole, per
-- announcement, and never joined or aggregated across issuers. Survives the
-- 30-day body prune (rns._prune_old) — it is small, and it is the audit trail
-- for why a row was or wasn't flagged.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/025_rns_guidance_checks.sql

ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_checks JSONB;

-- The showcase gate scans recent ranked rows for a disqualifying entry; the
-- partial index keeps that off a full scan as the table grows.
CREATE INDEX IF NOT EXISTS idx_rns_guidance_checks
    ON rns_announcements (published_at DESC)
    WHERE guidance_checks IS NOT NULL;
