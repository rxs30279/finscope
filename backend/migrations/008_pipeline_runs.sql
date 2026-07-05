-- Run markers for pipelines whose success leaves no other DB trace.
--
-- The quarterly index-membership refresh (refresh_index_membership.py --apply,
-- Dokploy schedule `index-refresh`) can legitimately make ZERO row changes, so
-- healthcheck.py cannot infer "did it run" from data freshness the way it does
-- for the daily pipelines. Instead the script upserts one row here per apply
-- run and the health check alerts when the marker goes stale (> one quarter).
--
-- One row per pipeline, upserted in place. `detail` holds a small JSON summary
-- of the run (counts etc.) purely for the health-check report line.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    pipeline    text PRIMARY KEY,
    last_run_at timestamptz NOT NULL,
    status      text NOT NULL,
    detail      jsonb
);
