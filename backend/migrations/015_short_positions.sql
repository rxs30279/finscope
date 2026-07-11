-- Short-interest data fed by the FCA's public short-position disclosures.
--
-- The UK short-selling disclosure regime changed on 13 July 2026: individual
-- named disclosures (>=0.5%) were replaced by anonymised Aggregate Net Short
-- Positions (ANSPs, sum of all positions >=0.2%) published daily. The two
-- series use different thresholds and must never be merged into one chart —
-- short_position_holders is a frozen one-time archive of the old regime,
-- short_positions_agg is the ongoing daily series under the new regime.
--
-- Keyed on ISIN (not ticker) because that's what the FCA data keys on and
-- because it lets out-of-universe issuers be kept (company_symbol nullable,
-- resolved best-effort). company_metadata has no ISIN column previously —
-- added here and learned opportunistically from FCA disclosure rows
-- themselves via normalised-name matching (backend/shorts.py _resolve_symbol);
-- yfinance's isin lookup was tried and abandoned as unreliable (returned the
-- same bogus value for multiple unrelated companies).
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/015_short_positions.sql

ALTER TABLE company_metadata ADD COLUMN IF NOT EXISTS isin TEXT;

-- Daily ANSP series (new regime, from 13 July 2026).
CREATE TABLE IF NOT EXISTS short_positions_agg (
    isin            TEXT NOT NULL,
    disclosure_date DATE NOT NULL,          -- working day the ANSP relates to
    issuer_name     TEXT NOT NULL,
    ansp_pct        NUMERIC NOT NULL,       -- aggregate net short %, e.g. 6.32
    position_date   DATE,                   -- latest position date in the ANSP
    company_symbol  TEXT,                   -- resolved ticker or NULL
    PRIMARY KEY (isin, disclosure_date)
);
CREATE INDEX IF NOT EXISTS idx_spa_symbol ON short_positions_agg (company_symbol, disclosure_date);

-- Frozen one-time archive of pre-13-July individual disclosures (old regime).
CREATE TABLE IF NOT EXISTS short_position_holders (
    isin            TEXT NOT NULL,
    holder_name     TEXT NOT NULL,
    position_date   DATE NOT NULL,
    net_short_pct   NUMERIC NOT NULL,
    issuer_name     TEXT NOT NULL,
    is_current      BOOLEAN NOT NULL,       -- true = "current" tab of the archived XLSX
    company_symbol  TEXT,
    PRIMARY KEY (isin, holder_name, position_date)
);
CREATE INDEX IF NOT EXISTS idx_sph_symbol ON short_position_holders (company_symbol);
