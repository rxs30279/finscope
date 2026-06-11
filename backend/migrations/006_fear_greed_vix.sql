-- Add raw VIX close to the daily Fear & Greed history so the markets-page chart
-- can overlay the VIX alongside the UK and US Fear & Greed series. The VIX is
-- already fetched to compute the UK index's implied-vol component; this just
-- persists the raw level (not the inverted 0–100 sub-score) for plotting.
--
-- Backfilled the same way as the rest of the table: market._rebuild_fear_greed_history()
-- upserts a full trailing year, so re-running the daily cron (or run_fg_history.py)
-- populates this column for every existing row. Idempotent and self-healing.

ALTER TABLE fear_greed_history
    ADD COLUMN IF NOT EXISTS vix double precision;
