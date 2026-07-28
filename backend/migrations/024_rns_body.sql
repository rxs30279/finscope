-- Give the RNS ranker and vet access to the full announcement text, not just
-- the Investegate AI paraphrase, plus a per-issuer memory of stated forward
-- guidance. See docs/rns-body-context-plan.md for the incident and reasoning.
--
-- body / body_chars / body_fetched_at / body_is_stub: captured by
-- rns._backfill_summaries alongside the existing AI summary (same fetch, no
-- extra HTTP request). body_chars records the PRE-truncation length for
-- diagnostics even after body itself is NULLed out by the 30-day prune in
-- rns._prune_old — the full text is only needed at scoring time, and keeping
-- it indefinitely on every retained Tier A/B row would grow rns_announcements
-- against Supabase's free-tier storage cap.
--
-- guidance_metric / guidance_value / guidance_period: an optional field the
-- ranker LLM fills in when an announcement states an explicit forward
-- guidance figure (e.g. "FY2026 Adjusted Operating Profit" / "> £40m" /
-- "FY2026"). Kept as free text, not a parsed number — guidance spans too many
-- units (profit, revenue, EPS, margin, ranges) to normalise safely. The NEXT
-- announcement for the same issuer can then compare against this row's figure
-- to tell a reiteration from a real upgrade (see rns_llm._load_prior_guidance).
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/024_rns_body.sql

ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body               TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body_chars         INT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body_fetched_at    TIMESTAMPTZ;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body_is_stub       BOOLEAN;

ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_metric    TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_value     TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_period    TEXT;

-- Prior-guidance lookups (rns_llm._load_prior_guidance) scan for the most
-- recent non-null guidance_metric per symbol.
CREATE INDEX IF NOT EXISTS idx_rns_guidance
    ON rns_announcements (symbol, published_at DESC)
    WHERE guidance_metric IS NOT NULL;
