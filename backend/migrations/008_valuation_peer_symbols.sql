-- Store which symbols made up the peer group behind each fair-value estimate,
-- so the Valuation tab can name them instead of just showing a count. Filled
-- by compute_and_store_valuations() alongside peer_count/peer_median_multiple;
-- empty array when peer_basis is 'insufficient' with zero peers found.

ALTER TABLE valuation_estimates ADD COLUMN IF NOT EXISTS peer_symbols TEXT[] NOT NULL DEFAULT '{}';
