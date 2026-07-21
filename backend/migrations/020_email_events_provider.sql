-- Generalise email_events from "Resend webhook log" to "delivery event log".
--
-- Migration 018 keyed the table on svix_id because Resend delivers events
-- through Svix and the Svix delivery id is what makes retries idempotent. SES
-- delivers through SNS→SQS instead, where the equivalent stable id is the SNS
-- MessageId. Same role, same uniqueness guarantee, different vendor — so the
-- column is renamed to event_id rather than a second one being added.
--
-- provider records which pipeline wrote the row. Existing rows are all Resend
-- by definition (nothing else could have written them), hence the DEFAULT.
-- During the parallel run both providers write here at once, and without this
-- column a per-provider delivery comparison — the entire acceptance gate for
-- the cutover — is not expressible.
--
-- ORDERING: this rename is NOT backwards compatible with the running backend.
-- email_events.py's INSERT names svix_id, so apply this in the SAME window as
-- the redeploy that ships the new code, not before. A brief mismatch is
-- self-healing (Svix retries any non-2xx for hours) but it is still a window
-- where the /status deliverability card goes stale.
--
-- Idempotent: guarded so re-running after a partial apply is safe.
--   python backend/run_migration.py migrations/020_email_events_provider.sql

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_events' AND column_name = 'svix_id'
    ) THEN
        ALTER TABLE email_events RENAME COLUMN svix_id TO event_id;
    END IF;
END $$;

ALTER TABLE email_events
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'resend';

-- The parallel run reads "how did each provider do over the last N days", so
-- the provider cut needs to be cheap alongside the existing time cut.
CREATE INDEX IF NOT EXISTS idx_email_events_provider
    ON email_events (provider, occurred_at DESC);
