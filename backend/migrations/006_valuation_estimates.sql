-- Precomputed peer-relative fair value per symbol.
--
-- The company Valuation tab answers "is this stock above or below fair value?"
-- with a peer-multiple estimate: fair value = peer-median EV/EBITDA applied to the
-- company via the equity bridge. Deliberately EV/EBITDA-only and narrow — a dry
-- run showed a plain peer-median is only defensible for profitable, non-financial,
-- moderately-geared companies; financials/REITs (book/NAV-valued), unprofitable
-- and highly-levered names produce nonsense and so get no estimate. Peers are
-- true peers only — the same yfinance industry (with over-split industries merged
-- into analytical groups, e.g. AZN+GSK+Hikma -> Pharmaceuticals), no sector
-- fallback — and only when at least MIN_PEERS valid peers exist; otherwise no fair
-- value is stored (the UI shows "no comparable basis"). peer_basis is therefore
-- 'industry', 'excluded_sector' (financials/REITs — never eligible, so distinct
-- from a thin peer group) or 'insufficient'. See compute_and_store_valuations /
-- _peer_group.
--
-- It fills this once daily (right after the price refresh, alongside
-- screener_scores), and /api/valuation serves a single row per company. The upside
-- is computed currency-safely as a ratio; fair_value is mapped onto the GBp quote
-- price for display only. multiple_used is always 'EV/EBITDA' and caution always
-- false today, but both are kept so the model can broaden later without a migration.

CREATE TABLE IF NOT EXISTS valuation_estimates (
    symbol               TEXT PRIMARY KEY,
    fair_value           double precision,           -- GBp quote currency, NULL when not estimable
    current_price        double precision,           -- GBp quote currency
    upside_pct           double precision,           -- (fair_value/current_price - 1) * 100, NULL when not estimable
    multiple_used        TEXT,                        -- 'EV/EBITDA' | 'P/B' | 'P/S'
    peer_basis           TEXT NOT NULL,               -- 'industry' | 'sector' | 'insufficient'
    peer_count           integer NOT NULL DEFAULT 0,
    peer_median_multiple double precision,
    own_multiple         double precision,
    caution              boolean NOT NULL DEFAULT false,  -- true for the low-confidence P/S path
    computed_at          timestamptz NOT NULL DEFAULT now()
);
