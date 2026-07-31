"""Did dropping reasoning degrade the ranker's financial-value extraction?

The ranking prompt does two extractions besides scoring: `guidance_checks`
(every forward-looking guidance statement plus its prior/consensus comparator)
and `earnings_quality` (every material income or charge line with its printed
comparator). Both are copy-out-of-the-text fields, both are stored to their own
columns, and both feed /gates.

Until 91198a4 (2026-07-31) every row filled them WITH reasoning. Now no row
does. That mode change was never measured on these fields — the one extraction
eval in this directory (rns_period_extraction_eval.py) ran with _THINKING_ON,
so its 21/21 result says nothing about the fast path.

This prints the same profile per llm_model era so the two are directly
comparable. Run it now for the thinking-mode baseline and again after the first
fast-mode batch; what matters is the DELTA, not any single number.

What degradation would look like, in rough order of how likely it is to be the
first visible sign:

  * populate rate falls    — the model stops emitting the array at all, which
                             reads as "this announcement had no guidance" and
                             is indistinguishable downstream from a clean row
  * entries/row falls      — it finds 1 of the 3 charge lines instead of 3
  * unknown/no_consensus_stated or unclear rises — the whitelist fail-safe
                             buckets in _clean_*; these fail OPEN, so a rise
                             here silently stops gates matching
  * prior_value null rate rises — the comparator is the field the whole
                             low-base gate depends on

Read-only. No writes, no LLM calls, no cost.

Usage:
  python backend/analysis/rns_extraction_mode_baseline.py
  python backend/analysis/rns_extraction_mode_baseline.py --days 30
"""

import argparse
import os
import sys
from collections import Counter

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from dotenv import load_dotenv

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

import db


def _cutoff():
    """First date either column was ever populated.

    Without this the populate rate is nonsense: the :thinking era starts
    2026-07-15 but migrations 025/026 only added these fields to the prompt on
    2026-07-29, so a fortnight of rows are NULL because nothing asked — not
    because the model declined. Unbounded, guidance_checks reads 15.6% when the
    real figure is 43.5%. Derived rather than hardcoded so the window stays
    right as the table grows.
    """
    return db.query(
        """
        SELECT MIN(published_at)::date AS lo FROM rns_announcements
        WHERE guidance_checks IS NOT NULL OR earnings_quality IS NOT NULL
        """
    )[0]["lo"]


def _rows(days: int, cutoff):
    return db.query(
        """
        SELECT llm_model, category, llm_score, guidance_checks, earnings_quality
        FROM rns_announcements
        WHERE tier = ANY(ARRAY['A','B'])
          AND llm_processed_at IS NOT NULL
          AND published_at > NOW() - INTERVAL '%s days'
          AND published_at >= %%s
        """ % int(days),
        (cutoff,),
    )


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):5.1f}%" if d else "    —"


def _profile(rows: list, col: str, fields: tuple, enums: tuple) -> None:
    """One column's profile for one era."""
    total = len(rows)
    present = [r[col] for r in rows if r[col]]
    entries = [e for arr in present for e in arr if isinstance(e, dict)]

    print(f"    populate rate      {_pct(len(present), total)}  "
          f"({len(present)}/{total} rows)")
    if not entries:
        print("    no entries")
        return
    print(f"    entries            {len(entries)} total, "
          f"{len(entries)/len(present):.2f} per populated row")
    for f in fields:
        filled = sum(1 for e in entries if e.get(f) not in (None, ""))
        print(f"      {f:<16} {_pct(filled, len(entries))} non-null")
    for f, safe_value in enums:
        c = Counter(str(e.get(f)) for e in entries)
        parts = ", ".join(f"{k}={v}" for k, v in c.most_common())
        flag = " <-- FAIL-SAFE BUCKET" if c.get(safe_value, 0) else ""
        print(f"      {f:<16} {parts}")
        if c.get(safe_value, 0):
            print(f"      {'':<16} {safe_value} is {_pct(c[safe_value], len(entries))}"
                  f" of entries{flag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    cutoff = _cutoff()
    rows = _rows(args.days, cutoff)
    by_model = {}
    for r in rows:
        by_model.setdefault(r["llm_model"] or "(null)", []).append(r)

    print("=== ranker extraction profile ===")
    print(f"Window starts {cutoff} — the date migrations 025/026 put these "
          f"fields in the prompt.")
    print(f"{len(rows)} ranked tier A/B rows. Compare eras top to bottom; "
          f":thinking is the pre-91198a4 baseline.\n")

    for model in sorted(by_model, key=lambda m: -len(by_model[m])):
        era = by_model[model]
        print(f"── {model}  ({len(era)} rows) "
              + "─" * max(0, 46 - len(model)))
        print("  guidance_checks")
        _profile(
            era, "guidance_checks",
            fields=("metric", "period", "guided_value", "consensus_value"),
            enums=(("vs_prior", "unknown"),
                   ("vs_consensus", "no_consensus_stated")),
        )
        print("  earnings_quality")
        _profile(
            era, "earnings_quality",
            fields=("item", "period", "value", "prior_value", "one_off_named"),
            enums=(("kind", "unclear"),),
        )
        print()

    # The results categories are where these fields carry the gates, and where
    # the answer is longest — so a budget-driven regression shows here first.
    print("=== populate rate on results categories only ===")
    heavy = ("interim_results", "final_results", "trading_update", "quarterly")
    print(f"{'model':<32}{'n':>5}{'guidance':>10}{'earnings':>10}")
    for model in sorted(by_model, key=lambda m: -len(by_model[m])):
        era = [r for r in by_model[model] if r["category"] in heavy]
        if not era:
            continue
        g = sum(1 for r in era if r["guidance_checks"])
        e = sum(1 for r in era if r["earnings_quality"])
        print(f"{model:<32}{len(era):>5}{_pct(g, len(era)):>10}{_pct(e, len(era)):>10}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
