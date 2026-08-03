-- 029 — the vet becomes a scorer with publishing authority.
--
-- Until now the pipeline had ONE number (rns_announcements.llm_score, the
-- ranker's "price-impact likelihood x magnitude") and the vet was advisory
-- prose: showcase.flag_high_impact_candidates hardcoded status='approved', so
-- vet_verdict labelled a card it could never suppress. Three rows currently
-- live on the public page carry verdict='exclude'.
--
-- The new shape is two stages with two different questions:
--
--   ranker  llm_score  >= 60  -> worth a closer look   (cheap, every Tier A/B row)
--   vet     vet_score  >= 75  -> goes on the public page (expensive, ~107 rows/mo)
--
-- The scores deliberately measure different things. llm_score is short-term
-- catalyst strength; vet_score is conviction in a genuinely positive 1-3 month
-- investment case AFTER the sceptical read. A story can be a real catalyst and
-- a poor case (dilution, a guidance cut inside an upbeat headline) or a modest
-- catalyst and a sound case. Collapsing them into one number is what the old
-- single-threshold design did.
--
-- Two consequences this migration has to support:
--
--   1. The vet now sees rows it never saw before (llm_score 60-74, n=0 to date)
--      and most of them will NOT reach 75. Their vet output still has to be
--      stored -- that band is the whole evidence base for calibrating the new
--      threshold, and per 1fff51e rns_gate_evaluations returns early on every
--      n/a exit so it cannot serve as the record. Hence status='shadow'.
--   2. vet_score can DEMOTE, so a vet failure now silently drops a story rather
--      than mislabelling one. NULL vet_score is therefore meaningful and must
--      stay distinguishable from a real low score -- do not default it to 0.

ALTER TABLE high_impact_rns
    ADD COLUMN IF NOT EXISTS vet_score SMALLINT
        CHECK (vet_score IS NULL OR (vet_score >= 0 AND vet_score <= 100));

COMMENT ON COLUMN high_impact_rns.vet_score IS
    'Vet conviction 0-100 in a positive 1-3 month case, scored AFTER the '
    'sceptical read. Gates publication at HIGH_IMPACT_MIN_VET_SCORE. NULL '
    'means the vet call failed or has not run -- never treat as 0.';

-- 'shadow' = vetted but below the publish floor. Excluded from every public and
-- moderation query, which all filter on 'approved' or 'pending' explicitly.
-- Kept distinct from 'archived', which already carries real meaning: the two
-- pre-floor rows from 2026-07-05 use it.
ALTER TABLE high_impact_rns DROP CONSTRAINT IF EXISTS high_impact_rns_status_check;
ALTER TABLE high_impact_rns ADD CONSTRAINT high_impact_rns_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'archived', 'shadow'));

-- The public page reads (status, published_at DESC) and now never wants shadow
-- rows; the calibration queries want shadow rows by score. Existing
-- idx_hirns_status still serves the former.
CREATE INDEX IF NOT EXISTS idx_hirns_vet_score
    ON high_impact_rns (vet_score DESC NULLS LAST, flagged_at DESC);
