-- Dated history of the four headline screener scores, one row per (symbol, day).
--
-- WHY THIS EXISTS
-- screener_scores is keyed on symbol alone and is overwritten by every run of
-- compute_and_store_scores(), so the moment a score changes the old value is
-- gone. That makes a forward test impossible: you cannot ask "how did the names
-- scoring 8 on quality a year ago actually do since?" because the scores as
-- they stood a year ago no longer exist anywhere. This table is the record.
--
-- WHY IT IS NOT JUST A MIRROR OF screener_scores
-- Only momentum, piotroski and risk live in that table. quality_score and
-- value_score are computed inline in the /api/screener handler (main.py, after
-- _scrub_screener_metrics and _attach_pegy) because they read columns already
-- present in the main JOIN. Two of the four scores anyone would want to test
-- are therefore NOT in screener_scores, so the snapshot has to be taken from
-- the endpoint's own output rather than from that table.
--
-- POINT-IN-TIME COLUMNS
-- market_cap, sector and ftse_index are stored per snapshot on purpose, not
-- looked up later. Index membership is a look-ahead variable — the AIM 100
-- turns over ~25% a year, and bucketing history by today's constituents
-- invents effects that were never available to trade. Same for market cap:
-- ranking 2025 rows by 2026 caps sorts on information that did not exist.
-- sector is the ICB label as served (to_icb applied), so a later remap of the
-- underlying GICS value does not silently rewrite past cross-sections.
--
-- close is stored for audit — "what was the price when we said this" — and is
-- the RAW close, not adjusted. Do NOT compute multi-month returns from it:
-- price_history is never re-adjusted for splits, which is the same fault that
-- forces return studies to re-download from source. Returns belong in the
-- analysis, computed from freshly adjusted prices.
--
-- Idempotent, and safe to re-run within a day: (symbol, as_of) upserts, so the
-- last write of a day wins.
--
-- Apply with:
--   python backend/run_migration.py migrations/037_screener_score_history.sql

CREATE TABLE IF NOT EXISTS screener_score_history (
    symbol                TEXT NOT NULL,
    -- The TRADING date the scores describe, not the wall-clock date the job
    -- ran. The cron fires after the price refresh and can cross midnight UTC;
    -- keying on the latest price date keeps the series on trading days and
    -- makes a re-run idempotent.
    as_of                 date NOT NULL,

    -- the four headline scores
    value_score           integer,
    quality_score         integer,
    momentum_score        integer,
    risk_score            integer,

    -- supporting scores, same source, free to carry
    piotroski_score       integer,
    risk_model            text,
    altman_z              double precision,
    volatility_annualised double precision,

    -- point-in-time context (see note above)
    market_cap            double precision,
    sector                text,
    ftse_index            text,
    close                 double precision,

    snapshotted_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, as_of)
);

-- The PK serves per-symbol time series. The analysis query is the other shape —
-- "every score on date X" — which needs as_of leading.
CREATE INDEX IF NOT EXISTS screener_score_history_as_of_idx
    ON screener_score_history (as_of, symbol);

-- New tables default to RLS off; the Data API must not expose this one
-- (see migrations/016_enable_rls.sql).
ALTER TABLE screener_score_history ENABLE ROW LEVEL SECURITY;
