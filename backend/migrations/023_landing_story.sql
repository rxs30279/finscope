-- "Story of the week" — the self-refreshing RNS proof block on the landing page.
--
-- One row per weekly pick: the best scored-before-the-open announcement from the
-- trailing 7 days, together with the price reaction it called. The public page
-- reads the newest row (ORDER BY picked_at DESC LIMIT 1); older rows are kept as
-- the pick history and as the dedupe source (rns_id UNIQUE), so the same story
-- can never headline two weeks running.
--
-- Deliberately a SNAPSHOT, not a live join: the page then renders from one cheap
-- read, and the numbers a visitor sees on Friday are the same ones it showed on
-- Monday even though price_history has moved underneath.
--
-- Price convention (load-bearing — see backend/analysis/rns_score_perf.py): RNS
-- drops ~07:00, before the 08:00 LSE open, so the news is priced into THAT day's
-- session. gap_pct is previous close -> announcement-day open. It is NEVER the
-- next day's open (showcase.py _next_open is the wrong helper here; that
-- off-by-one flattened the whole signal in the score-performance work).
--
-- Prices are in pence throughout, matching price_history.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/023_landing_story.sql

CREATE TABLE IF NOT EXISTS landing_story (
    id             SERIAL PRIMARY KEY,
    rns_id         INTEGER NOT NULL UNIQUE,   -- rns_announcements.id; dedupes re-picks
    symbol         TEXT NOT NULL,
    company_name   TEXT,
    headline       TEXT,
    url            TEXT,
    published_at   TIMESTAMPTZ NOT NULL,
    llm_score      INTEGER,
    llm_sentiment  TEXT,                      -- resolved direction (showcase._sentiment)
    llm_thesis     TEXT,
    sector         TEXT,
    ftse_index     TEXT,

    -- The move the story called, in pence.
    prev_close     NUMERIC NOT NULL,          -- close the session BEFORE the announcement
    event_open     NUMERIC NOT NULL,          -- open on the announcement day itself
    event_close    NUMERIC,                   -- close that same session
    gap_pct        NUMERIC NOT NULL,          -- (event_open / prev_close - 1) * 100

    -- +/-3 sessions around the event for the candle chart: a JSON array of
    -- [label, open, high, low, close], oldest first, with event_idx pointing at
    -- the announcement day's bar.
    ohlc           JSONB NOT NULL,
    event_idx      INTEGER NOT NULL,

    -- The morning this story landed in, for the funnel the page opens with:
    -- everything that hit the wire before the open, what survived the rules
    -- filter, and what the ranker scored 80+. Real 22 Jul 2026: 122 -> 31 -> 4.
    wire_total     INTEGER,
    wire_survived  INTEGER,
    wire_top       INTEGER,
    -- A slice of that morning's wire for the scrolling ticker: [time, ticker,
    -- headline]. Deliberately unfiltered — the routine "Transaction in Own
    -- Shares" noise IS the point being made.
    wire_sample    JSONB,

    picked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent column adds, so this file can be re-run over an earlier version of
-- the table (same convention as rns_schema.sql).
ALTER TABLE landing_story ADD COLUMN IF NOT EXISTS wire_total    INTEGER;
ALTER TABLE landing_story ADD COLUMN IF NOT EXISTS wire_survived INTEGER;
ALTER TABLE landing_story ADD COLUMN IF NOT EXISTS wire_top      INTEGER;
ALTER TABLE landing_story ADD COLUMN IF NOT EXISTS wire_sample   JSONB;

CREATE INDEX IF NOT EXISTS idx_landing_story_picked ON landing_story (picked_at DESC);

-- New tables default to RLS off; the Data API must not expose this one
-- (see migrations/016_enable_rls.sql).
ALTER TABLE landing_story ENABLE ROW LEVEL SECURITY;
