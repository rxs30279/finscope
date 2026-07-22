-- Track re-subscription separately from the original unsubscribe timestamp.
--
-- Motivation: migration 019's own rationale is that "re-signup after
-- unsubscribe must not look like a fresh opt-in when a complaint is
-- investigated" -- but the signup() upsert cleared unsubscribed_at back to
-- NULL on reactivation, which erased exactly that history. unsubscribed_at
-- now means "last time this address opted out" and survives re-signup;
-- resubscribed_at is the audit trail for when it opted back in.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/021_subscribers_resubscribed.sql
--
-- Apply BEFORE deploying the code that references this column (subscribers.py
-- signup()) -- additive, so applying early is harmless.

ALTER TABLE subscribers
    ADD COLUMN IF NOT EXISTS resubscribed_at TIMESTAMPTZ;
