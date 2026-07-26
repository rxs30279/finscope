-- 022: give investment trusts a real sector/industry.
--
-- Yahoo returns no sector and no industry for closed-end funds, so 59 of 748
-- companies carried NULL for both. Consequences:
--   * they render as sector "Unknown" and escape the screener's sector filter
--     and the /companies sector hubs entirely
--   * _valuation_excluded (main.py) keys off sector, so a trust's EV/EBITDA was
--     eligible for fair value AND could sit inside an operating peer group's
--     median -- the exact contamination that function's docstring warns against
--
-- The selector below is the same rule _classify_risk_model already used to
-- detect a trust (no sector AND no industry), so this relabels precisely the
-- rows that were already being routed to the trust risk model -- verified as
-- 59 rows, all closed-end funds, on 2026-07-26.
--
-- 'Financial Services' is the raw GICS value; sectors.py maps it to the ICB
-- label "Financials" the UI shows. 'Investment Trust' is ours -- Yahoo never
-- emits it -- and main.py's _classify_risk_model now keys the trust model off
-- it, so trusts keep their trust-specific risk model and metric blanking
-- instead of falling through to the broad "financial" branch.
--
-- Safe to re-run: the WHERE clause no longer matches once applied. updater.py
-- writes sector via COALESCE(%s, sector) (updater.py:243), so the NULL that
-- Yahoo keeps returning will not overwrite these values.

UPDATE company_metadata
SET sector = 'Financial Services',
    industry = 'Investment Trust'
WHERE sector IS NULL
  AND industry IS NULL;
