-- Recording table for the gate registry (backend/gates.py). See
-- docs/rns-gate-block-plan.md, Phase 2.
--
-- Why this exists: a blocked candidate is never inserted into high_impact_rns
-- — it leaves a print in the cron log and nothing else. There is no record of
-- what was blocked, by which rule, or what the stock subsequently did, so
-- every threshold in the system is calibrated on the sample that motivated it
-- and can never be revisited on evidence. This table is that record.
--
-- One row per (rns_id, gate): evaluate_all() runs every gate on every ranked
-- Tier A/B row (not just the ~2-3/day that clear the flag floors — "evaluate
-- wide, block narrow", plan section 2.4), so the /gates page can measure a
-- gate's fire rate and amber rate over the population it could actually see,
-- not just the rows it happened to block.
--
-- mode is stamped AT EVALUATION TIME (armed | shadow), not read live from the
-- registry, so a later promotion doesn't rewrite the meaning of old rows —
-- history stays interpretable after a gate is armed.
--
-- Upsert on re-evaluation (UNIQUE (rns_id, gate)): a backfill re-run after a
-- threshold change is idempotent, and a re-armed gate's shadow-era rows
-- refresh cleanly instead of duplicating.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/027_rns_gate_evaluations.sql

CREATE TABLE IF NOT EXISTS rns_gate_evaluations (
    id           BIGSERIAL PRIMARY KEY,
    rns_id       BIGINT NOT NULL REFERENCES rns_announcements(id) ON DELETE CASCADE,
    gate         TEXT NOT NULL,             -- Gate.name
    state        TEXT NOT NULL,             -- pass | block | n/a
    reason       TEXT,
    evidence     JSONB,
    mode         TEXT NOT NULL,             -- armed | shadow, AT EVALUATION TIME
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (rns_id, gate)
);

CREATE INDEX IF NOT EXISTS idx_rns_gate_evaluations_evaluated_at
    ON rns_gate_evaluations (evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_rns_gate_evaluations_gate_state
    ON rns_gate_evaluations (gate, state);

ALTER TABLE rns_gate_evaluations ENABLE ROW LEVEL SECURITY;
