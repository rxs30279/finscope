-- Enable Row Level Security on every table in the public schema.
--
-- Supabase auto-exposes public-schema tables through its PostgREST Data API,
-- and its linter warns on any table with RLS disabled. This app never uses
-- that API — the backend connects directly as the postgres role, which owns
-- the tables and has bypassrls, so enabling RLS with NO policies is a no-op
-- for the app while making the Data API deny everything for anon/authenticated.
--
-- New tables default to RLS off: future migrations that CREATE TABLE must add
-- their own ALTER TABLE ... ENABLE ROW LEVEL SECURITY, and this file's loop
-- can be re-run at any time to sweep up stragglers.
--
-- Idempotent (ENABLE on an already-enabled table is a no-op). Apply with:
--   python backend/run_migration.py migrations/016_enable_rls.sql

DO $$
DECLARE
    t RECORD;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.tablename);
    END LOOP;
END $$;
