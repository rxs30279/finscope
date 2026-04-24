-- RNS announcements table for the news screener.
-- Run this once against the Supabase database.

CREATE TABLE IF NOT EXISTS rns_announcements (
    id                  BIGINT PRIMARY KEY,               -- numeric id from investegate URL
    published_at        TIMESTAMPTZ NOT NULL,
    wire                TEXT NOT NULL,                    -- RNS, MFN, GNW, EQS, PRN
    ticker              TEXT,                             -- uppercase ticker (e.g. KIE, JD.)
    symbol              TEXT,                             -- resolved yfinance symbol (e.g. KIE.L) — NULL if unknown
    company_name        TEXT,
    headline            TEXT NOT NULL,
    headline_slug       TEXT NOT NULL,                    -- lower-case slug from URL
    url                 TEXT NOT NULL,
    tier                CHAR(1) NOT NULL,                 -- A / B / C
    category            TEXT,                             -- profit_warning, trading_update, ...
    keyword_hits        TEXT[] DEFAULT '{}',              -- e.g. {'profit_warning_neg', 'ahead_pos'}
    score               INT NOT NULL DEFAULT 0,           -- 0-100 (rules-only)
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Investegate AI summary (scraped from #collapseSummary on the announcement page)
    summary             TEXT,
    summary_fetched_at  TIMESTAMPTZ,

    -- LLM ranking layer (DeepSeek). NULL until processed.
    llm_score           INT,                              -- 0-100
    llm_confidence      TEXT,                             -- 'high' | 'medium' | 'low'
    llm_thesis          TEXT,                             -- one-sentence rationale
    llm_action          TEXT,                             -- 'watch' | 'research' | 'ignore'
    llm_risks           TEXT,                             -- what would invalidate the thesis
    llm_model           TEXT,                             -- e.g. 'deepseek-chat'
    llm_processed_at    TIMESTAMPTZ
);

-- Idempotent column adds for existing deployments. MUST run before any index
-- referencing the new columns, because CREATE TABLE IF NOT EXISTS above is a
-- no-op when the table already exists.
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS summary            TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS summary_fetched_at TIMESTAMPTZ;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_score          INT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_confidence     TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_thesis         TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_action         TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_risks          TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_model          TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_processed_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_rns_published_at ON rns_announcements (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_rns_symbol       ON rns_announcements (symbol);
CREATE INDEX IF NOT EXISTS idx_rns_tier_score   ON rns_announcements (tier, score DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_rns_llm_score    ON rns_announcements (llm_score DESC NULLS LAST, published_at DESC);
