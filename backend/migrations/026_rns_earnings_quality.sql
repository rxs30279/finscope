-- Persist the ranker's per-line enumeration of what the reported result is
-- MADE OF, so the High Impact gate can adjudicate composition in Python.
-- See docs/rns-earnings-quality-plan.md, Phase 1. Sibling of migration 025.
--
-- Why this exists: the guidance gate (025) can only fire on an announcement
-- that prints its own consensus figure, and large caps mostly don't — on the
-- first full day of body-context ranking (2026-07-29) 68 of 75 guidance_checks
-- entries batch-wide were "no_consensus_stated" and skipped_guidance was 0.
-- The BARC 2026-07-28 interims are the failure mode it cannot reach: guidance
-- genuinely WAS raised (FY2026 group income to c.£31.5bn), so no tightening of
-- the guidance labels touches the row, while the reported numbers underneath
-- were partly non-repeating (a c.£225m gain on the AA co-branded card
-- portfolio inside "USCB income increased 38%") against a loan loss rate that
-- had gone 52 -> 62bps. The stock fell 5.5% on the day; scored 7 times at
-- temperature 0.2 the announcement came back [55, 60, 65, 75, 80, 80, 80],
-- positive 7/7, and named the £225m gain in 0 of 7 runs. An enumerated field
-- gets filled in where a free sentence gets improvised — the same lesson as
-- guidance_checks.
--
-- Shape: JSONB array, one object per material income or charge line the
-- announcement itself quantifies:
--   {item, period, value, prior_value, kind, one_off_named}
-- kind ∈ income | cost_or_charge | unclear
--
-- Two deliberate design choices, both load-bearing:
--   * value/prior_value are stored AS PRINTED ("£1.4bn", "62bps",
--     "increased 38%"), not parsed to numbers. Parsing is showcase's job so a
--     parse failure is visible against the stored quote instead of hidden
--     behind a guess made at write time.
--   * one_off_named is the company's own quoted clause, not a
--     recurring yes/no boolean. The boolean is defensible either way on
--     structural hedge income and on IB income, so the model flips run to run
--     — exactly the instability that splitting verdict into vs_prior /
--     vs_consensus fixed for guidance. Copying a clause the company already
--     wrote is the same stable operation as guided_value. It is also
--     direction-neutral: a one-off CHARGE that flatters the underlying trend
--     is recorded exactly as a one-off gain is, and Python decides what it
--     means from `kind`.
--
-- Stored as JSONB rather than normalised rows, for the same reasons as 025: it
-- is read whole, per announcement, never joined or aggregated across issuers.
-- Survives the 30-day body prune (rns._prune_old) — it is small, and it is the
-- audit trail for why a row was or wasn't blocked.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/026_rns_earnings_quality.sql

ALTER TABLE rns_announcements ADD COLUMN IF NOT EXISTS earnings_quality JSONB;

-- The showcase gate scans recent ranked rows for a disqualifying entry; the
-- partial index keeps that off a full scan as the table grows.
CREATE INDEX IF NOT EXISTS idx_rns_earnings_quality
    ON rns_announcements (published_at DESC)
    WHERE earnings_quality IS NOT NULL;
