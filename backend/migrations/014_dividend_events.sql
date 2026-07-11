-- Per-payment dividend history from yfinance Ticker(sym).dividends.
--
-- One row per (symbol, ex-dividend date). Amounts are stored EXACTLY as Yahoo
-- returns them: denominated in the QUOTE currency (company_metadata.currency —
-- GBp for most .L lines, USD for dollar-quoted ones), split-adjusted, and
-- subject to revision. The weekly sweep (run_dividends.py) re-fetches the full
-- series per symbol and replaces it wholesale, so revisions and shifted/
-- cancelled ex-dates self-heal rather than leaving stale ghost rows.
--
-- Display-only: powers the company-page Dividends tab. The screener /
-- valuation / PEGY paths keep using annual_financials.dividend_yield untouched.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/014_dividend_events.sql

CREATE TABLE IF NOT EXISTS dividend_events (
    company_symbol TEXT        NOT NULL,
    ex_date        DATE        NOT NULL,
    amount         NUMERIC     NOT NULL,  -- per-share, quote-currency units (GBp pence / USD dollars)
    currency       TEXT,                  -- quote currency snapshot at fetch time (audit)
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_symbol, ex_date)
);
