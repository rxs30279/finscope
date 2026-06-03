-- Stores small binary app documents (e.g. the user manual) directly in Postgres
-- so they can be served by the API on Vercel's stateless Python runtime, where
-- there is no persistent local filesystem to drop a static file onto.
--
-- One row per logical document, keyed by a stable slug (e.g. 'user-manual').
-- The bytes live in a BYTEA column; the API streams them back with the stored
-- filename and content_type. Upserted by backend/upload_help_doc.py.

CREATE TABLE IF NOT EXISTS app_documents (
    slug         text PRIMARY KEY,
    filename     text NOT NULL,
    content_type text NOT NULL,
    data         bytea NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT NOW()
);
