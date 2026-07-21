-- Resend delivery-event log, fed by the /api/webhooks/resend endpoint.
--
-- Motivation (21 Jul 2026): the morning digest went out to 54 recipients and 6
-- of the 9 Microsoft addresses (hotmail/outlook) came back `delivery_delayed`
-- while all 45 non-Microsoft recipients delivered cleanly — Outlook.com soft-
-- deferring (4xx) mail from Resend's shared SES eu-west-1 IP pool. We only
-- found out because a recipient mentioned it; nothing in the app recorded it.
-- Resend's own API exposes only `last_event` on the current message list, so
-- once an event is superseded the history is gone. This table is the durable
-- record.
--
-- Keyed on the Svix delivery id, not the Resend email id: one email produces
-- many events (sent → delivered → opened → clicked), and Svix retries the same
-- delivery on any non-2xx, so svix_id is what makes ingestion idempotent.
--
-- occurred_at (when the event happened) and email_created_at (when the message
-- was accepted) are both kept so deferral lag is a subtraction rather than a
-- join back to an API that no longer holds the answer.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/018_email_events.sql

CREATE TABLE IF NOT EXISTS email_events (
    svix_id           TEXT PRIMARY KEY,        -- Svix delivery id; dedupes retries
    email_id          TEXT NOT NULL,           -- Resend email id (data.email_id)
    event_type        TEXT NOT NULL,           -- email.delivered, email.delivery_delayed, ...
    recipient         TEXT,                    -- data.to[0], lowercased
    recipient_domain  TEXT,                    -- split of the above; the Microsoft-vs-rest cut
    subject           TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL,    -- event time (payload top-level created_at)
    email_created_at  TIMESTAMPTZ,             -- when the message was accepted (data.created_at)
    received_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detail            JSONB                    -- bounce/failure sub-object when present
);

-- The /status panel reads "recent problem events", so lead with the time cut.
CREATE INDEX IF NOT EXISTS idx_email_events_occurred ON email_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_events_type ON email_events (event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_events_domain ON email_events (recipient_domain, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_events_email_id ON email_events (email_id);

-- New tables default to RLS off; migration 016 requires every public table to
-- have it enabled (backend connects as owner, so this is a no-op for the app
-- and denies everything for the Supabase Data API's anon/authenticated roles).
ALTER TABLE email_events ENABLE ROW LEVEL SECURITY;
