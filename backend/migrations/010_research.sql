-- Research — an analysis blog for the site.
--
-- Posts are authored in-browser through an admin-gated editor (X-Admin-Token)
-- and stored here; there is no build step to publish. Readers can leave public
-- comments on a post, but every comment lands as 'pending' and only appears once
-- an admin approves it (spam control + tone control).
--
-- Idempotent: safe to re-run. Apply with:
--   python backend/run_migration.py migrations/010_research.sql

CREATE TABLE IF NOT EXISTS research_posts (
    id           BIGSERIAL PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,        -- URL segment: /research/<slug>
    title        TEXT NOT NULL,
    summary      TEXT,                        -- short dek: list card + meta description
    body         TEXT NOT NULL DEFAULT '',    -- Markdown (rendered client-side)
    tags         TEXT[] NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'draft'
                 CHECK (status IN ('draft', 'published')),
    published_at TIMESTAMPTZ,                 -- set when first published; drives ordering
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Public list / detail queries filter on status='published' and order by published_at.
CREATE INDEX IF NOT EXISTS idx_research_posts_pub
    ON research_posts (status, published_at DESC);

CREATE TABLE IF NOT EXISTS research_comments (
    id          BIGSERIAL PRIMARY KEY,
    post_id     BIGINT NOT NULL REFERENCES research_posts(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,               -- public display name
    email       TEXT,                        -- optional, NEVER shown publicly (owner reference only)
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ
);

-- Per-post public thread (status='approved') and the site-wide moderation queue.
CREATE INDEX IF NOT EXISTS idx_research_comments_post
    ON research_comments (post_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_comments_mod
    ON research_comments (status, created_at DESC);
