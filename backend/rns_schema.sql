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

    -- Full announcement body text (migration 024) — same fetch as the summary
    -- above. NULLed out 30 days after capture (see rns._prune_old); body_chars
    -- keeps the pre-truncation length for diagnostics after that.
    body                TEXT,
    body_chars          INT,
    body_fetched_at     TIMESTAMPTZ,
    body_is_stub        BOOLEAN,

    -- LLM ranking layer (DeepSeek). NULL until processed.
    llm_score           INT,                              -- 0-100
    llm_confidence      TEXT,                             -- 'high' | 'medium' | 'low'
    llm_thesis          TEXT,                             -- one-sentence rationale
    llm_action          TEXT,                             -- 'watch' | 'research' | 'ignore'
    llm_risks           TEXT,                             -- what would invalidate the thesis
    llm_sentiment       TEXT,                             -- 'positive' | 'negative' | 'neutral' (migration 012)
    llm_model           TEXT,                             -- e.g. 'deepseek-v4-flash:thinking'
    llm_processed_at    TIMESTAMPTZ,

    -- Stated forward guidance, extracted by the ranker LLM when present
    -- (migration 024) — free text, not a parsed number (units vary too much
    -- to normalise safely). Lets the NEXT announcement for this issuer tell a
    -- reiteration from a real upgrade (see rns_llm._load_prior_guidance).
    guidance_metric     TEXT,
    guidance_value      TEXT,
    guidance_period     TEXT,

    -- Every forward-looking guidance statement in the announcement, one object
    -- per statement (migration 025): {metric, period, guided_value,
    -- consensus_value, vs_prior, vs_consensus}. The showcase gate reads this
    -- rather than llm_score, because the ranker finds the disqualifying fact
    -- reliably but reflects it in the score unreliably.
    guidance_checks     JSONB
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
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_sentiment      TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_model          TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS llm_processed_at   TIMESTAMPTZ;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body               TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body_chars         INT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body_fetched_at    TIMESTAMPTZ;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS body_is_stub       BOOLEAN;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_metric    TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_value     TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_period    TEXT;
ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS guidance_checks    JSONB;

CREATE INDEX IF NOT EXISTS idx_rns_published_at ON rns_announcements (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_rns_symbol       ON rns_announcements (symbol);
CREATE INDEX IF NOT EXISTS idx_rns_tier_score   ON rns_announcements (tier, score DESC, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_rns_llm_score    ON rns_announcements (llm_score DESC NULLS LAST, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_rns_guidance
    ON rns_announcements (symbol, published_at DESC)
    WHERE guidance_metric IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rns_guidance_checks
    ON rns_announcements (published_at DESC)
    WHERE guidance_checks IS NOT NULL;
