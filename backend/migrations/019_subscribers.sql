-- Digest subscriber list, moved out of Resend Segments into our own table.
--
-- Motivation: the subscriber list was the last piece of application state owned
-- by the email vendor. Every signup, unsubscribe and digest send made a network
-- call to Resend's Contacts API, so the list was unqueryable from SQL, invisible
-- to /status, and the thing that would break first when MAX_SUBSCRIBERS is
-- raised (the digest paginates the segment 100 contacts at a time on every
-- send). It also blocked the move to SES: SESv2 Contact Lists allow exactly one
-- list per AWS account and have no usable dashboard, so "swap vendor" would
-- otherwise have meant "swap one vendor lock-in for a worse one".
--
-- email is the primary key, always stored lowercased — subscribers.py already
-- lowercases at every boundary (signup, unsubscribe, HMAC token signing), so
-- case-folding here would be a second, divergent normalisation.
--
-- Unsubscribes are a flag, never a DELETE: a removed row is indistinguishable
-- from a never-subscribed one, and re-signup after unsubscribe must not look
-- like a fresh opt-in when a complaint is investigated.
--
-- bounced_at / bounce_reason are written by the events pipeline, NOT by the
-- digest sender. They record what the provider told us.
--
-- AMENDED 2026-07-28 (comment only, schema unchanged): bounced_at now DOES
-- stop a send. subscribers._MAILABLE excludes any row with it set, so a
-- permanent bounce drops the address from the send list rather than relying
-- on the provider's suppression list to swallow each attempt. Only an
-- explicit re-signup from the address owner clears it.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/019_subscribers.sql

CREATE TABLE IF NOT EXISTS subscribers (
    email            TEXT PRIMARY KEY,        -- lowercased at every boundary
    unsubscribed     BOOLEAN NOT NULL DEFAULT FALSE,
    source           TEXT,                    -- 'resend_migration', 'signup', ...
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unsubscribed_at  TIMESTAMPTZ,
    bounced_at       TIMESTAMPTZ,             -- set from delivery events
    bounce_reason    TEXT
);

-- The only hot read is "active recipients, oldest first" (the digest send list
-- and the scarcity counter), so index exactly that shape.
CREATE INDEX IF NOT EXISTS idx_subscribers_active
    ON subscribers (unsubscribed, created_at);

-- New tables default to RLS off; migration 016 requires every public table to
-- have it enabled (backend connects as owner, so this is a no-op for the app
-- and denies everything for the Supabase Data API's anon/authenticated roles).
ALTER TABLE subscribers ENABLE ROW LEVEL SECURITY;
