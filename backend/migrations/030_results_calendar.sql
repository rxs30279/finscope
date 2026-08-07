-- Forward results calendar — which companies report in a given week.
--
-- Rows are scraped from the Digital Look UK Company Diary (see
-- backend/results_calendar.py for the source evaluation: 96.8% date agreement
-- against our own RNS over 5 back-tested weeks, vs yfinance's `calendar` which
-- carries a forward date for only ~18% of our universe and 0% of plain AIM).
--
-- One row per (day, event type, diary company). The diary is re-scraped daily
-- rather than once per week because companies MOVE their reporting dates —
-- Currys, Capita and ITV all shifted inside the back-test window — and a stale
-- row would leave a logo sitting on a day nothing happens.
--
-- `symbol` is NULL for the ~30% of diary rows that are not in our universe
-- (bonds, GDRs, micro-cap AIM). Those are stored rather than dropped so the
-- page can honestly say "+N others" and so a name-matching regression is
-- visible in the data instead of silently shrinking the page.
--
-- Idempotent. Apply with:
--   python backend/run_migration.py migrations/030_results_calendar.sql

CREATE TABLE IF NOT EXISTS results_calendar (
    id           SERIAL PRIMARY KEY,

    event_date   DATE NOT NULL,          -- the day the company reports
    week_start   DATE NOT NULL,          -- Monday of the diary week it came from
    event_type   TEXT NOT NULL,          -- finals | interims | q1 | q2 | q3 | trading_update

    -- As printed by the diary, before any cleaning. Kept verbatim because it is
    -- the natural key (the diary exposes no ticker) and because an unmatched
    -- name is the only clue for improving the resolver later.
    source_name  TEXT NOT NULL,
    source_id    TEXT,                   -- Digital Look's internal csi= id

    symbol       TEXT,                   -- resolved .L ticker; NULL if out of universe
    company_name TEXT,                   -- our company_metadata name when resolved

    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A company can legitimately appear twice in a week (e.g. a trading update
    -- and interims), but not twice for the same event on the same day — the
    -- diary itself emits exact duplicate <li>s (Convatec appeared twice in the
    -- 3 Aug week), and this is what collapses them.
    UNIQUE (event_date, event_type, source_name)
);

CREATE INDEX IF NOT EXISTS idx_results_calendar_week
    ON results_calendar (week_start, event_date);
CREATE INDEX IF NOT EXISTS idx_results_calendar_symbol
    ON results_calendar (symbol) WHERE symbol IS NOT NULL;

-- New tables default to RLS off; the Data API must not expose this one
-- (see migrations/016_enable_rls.sql).
ALTER TABLE results_calendar ENABLE ROW LEVEL SECURITY;
