-- High Impact RNS — curated showcase of high-impact, positive RNS stories.
--
-- Auto-flagged by rule (high llm_score + positive sentiment + performance-report
-- category), then manually approved. Each pick is tracked for ~31 days as a
-- showcase of whether the RNS signal actually worked out.
--
-- The story is SNAPSHOTTED here at flag time because rns_announcements is pruned
-- after 14 days (run_rns.py) and monitoring runs ~a month — so a live join back
-- to the source would lose the row mid-track. Same reason for the follow-ups
-- table below: subsequent announcements are copied in, not referenced.
--
-- Idempotent: safe to re-run. Apply with:
--   python backend/run_migration.py migrations/009_high_impact_rns.sql

CREATE TABLE IF NOT EXISTS high_impact_rns (
    id               BIGSERIAL PRIMARY KEY,
    rns_id           BIGINT NOT NULL UNIQUE,   -- rns_announcements.id at flag time (no FK: source prunes at 14d)
    symbol           TEXT NOT NULL,
    company_name     TEXT,
    headline         TEXT NOT NULL,
    url              TEXT,
    published_at     TIMESTAMPTZ NOT NULL,
    tier             CHAR(1),
    category         TEXT,
    rules_score      INT,
    keyword_hits     TEXT[] DEFAULT '{}',
    summary          TEXT,
    llm_score        INT,
    llm_confidence   TEXT,
    llm_thesis       TEXT,
    llm_risks        TEXT,
    story_close      NUMERIC,                  -- close (pence) on the story date; snapshot fallback for % since news
    -- Showcase-specific advisory LLM vet: flags positive-framed stories the
    -- market may still punish (secondary listings, dilution, one-off gains).
    -- Never auto-rejects — the human decides. NULL until/unless vetted.
    vet_verdict      TEXT,                     -- 'include' | 'caution' | 'exclude'
    vet_confidence   TEXT,                     -- 'high' | 'medium' | 'low'
    vet_rationale    TEXT,
    vet_model        TEXT,
    vet_processed_at TIMESTAMPTZ,
    track_until      TIMESTAMPTZ,              -- published_at + 31 days at flag time; Extend pushes +30d
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected','archived')),
    flagged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_hirns_status ON high_impact_rns (status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_hirns_symbol ON high_impact_rns (symbol, flagged_at DESC);

-- Idempotent column adds for deployments where the table already exists (the
-- CREATE TABLE above is a no-op then, so new columns must be added explicitly).
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS vet_verdict      TEXT;
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS vet_confidence   TEXT;
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS vet_rationale    TEXT;
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS vet_model        TEXT;
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS vet_processed_at TIMESTAMPTZ;
ALTER TABLE high_impact_rns ADD COLUMN IF NOT EXISTS track_until      TIMESTAMPTZ;

-- Subsequent announcements for a tracked company — records what happened AFTER
-- selection (e.g. a CEO retirement that tanks the price, Luceco-style). Snapshotted
-- because the source table prunes at 14d while monitoring runs ~30d.
CREATE TABLE IF NOT EXISTS high_impact_rns_followups (
    id           BIGSERIAL PRIMARY KEY,
    showcase_id  BIGINT NOT NULL REFERENCES high_impact_rns(id) ON DELETE CASCADE,
    rns_id       BIGINT NOT NULL,
    headline     TEXT NOT NULL,
    url          TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    tier         CHAR(1),
    category     TEXT,
    llm_score    INT,
    sentiment    TEXT,                         -- 'positive' | 'negative' | 'neutral' (server-side _sentiment)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (showcase_id, rns_id)
);

CREATE INDEX IF NOT EXISTS idx_hirns_fu ON high_impact_rns_followups (showcase_id, published_at DESC);
