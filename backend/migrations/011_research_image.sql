-- Research posts: optional hero/OG image.
--
-- A URL (usually a site-relative path like /research/<slug>/hero.png) used as
-- the article's Open Graph / Twitter card image and in the JSON-LD. Optional:
-- posts without one fall back to a text-only share card.
--
-- Idempotent: safe to re-run. Apply with:
--   python backend/run_migration.py migrations/011_research_image.sql

ALTER TABLE research_posts ADD COLUMN IF NOT EXISTS image TEXT;
