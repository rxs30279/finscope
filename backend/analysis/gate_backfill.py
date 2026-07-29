"""Replay the gate registry (backend/gates.py) over whatever rns_announcements
rows already carry a guidance_checks or earnings_quality extraction, and
upsert the result into rns_gate_evaluations. See docs/rns-gate-block-plan.md,
Phase 2.

Read-only against rns_announcements; writes ONLY rns_gate_evaluations. This is
NOT a way to generate a calibration sample — there is no backfill shortcut out
of the n=1 problem the plan measured: guidance_checks/earnings_quality only
exist on rows the body-context ranker has already scored (26 rows as of
2026-07-29, all one session), so replaying the registry over history finds
nothing to replay where the extraction doesn't exist and never will, once the
30-day body prune has run. Its real job is idempotent re-evaluation after a
threshold or gate-logic change — the morning cron (run_rns.py, via
gates.record_gate_evaluations) is what accrues the sample going forward, one
session at a time.

Usage:
    python backend/analysis/gate_backfill.py               # replay everything
    python backend/analysis/gate_backfill.py --days 30      # bound the window
    python backend/analysis/gate_backfill.py --dry-run       # print, don't write
"""

import argparse
import os
import sys
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _BACKEND_DIR)

from psycopg2.extras import Json

from db import query, connection
from gates import GATES, evaluate_all

_SELECT_SQL = """
    SELECT r.id, r.symbol, r.category, r.llm_score,
           r.llm_sentiment, r.llm_thesis, r.keyword_hits,
           r.guidance_checks, r.earnings_quality,
           m.sector, m.industry
    FROM rns_announcements r
    LEFT JOIN company_metadata m ON m.symbol = r.symbol
    WHERE r.symbol IS NOT NULL
      AND r.llm_processed_at IS NOT NULL
      AND r.tier IN ('A', 'B')
      AND (r.guidance_checks IS NOT NULL OR r.earnings_quality IS NOT NULL)
      AND (%s::int IS NULL OR r.published_at >= NOW() - (%s || ' days')::interval)
    ORDER BY r.published_at
"""

_UPSERT_SQL = """
    INSERT INTO rns_gate_evaluations
        (rns_id, gate, state, reason, evidence, mode, evaluated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (rns_id, gate) DO UPDATE SET
        state = EXCLUDED.state, reason = EXCLUDED.reason,
        evidence = EXCLUDED.evidence, mode = EXCLUDED.mode,
        evaluated_at = EXCLUDED.evaluated_at
"""


def _replay(rows, cur=None) -> tuple[dict, int]:
    """Evaluate every gate over every row, writing via `cur` if given (else a
    dry run). Returns (state_counts, rows_written)."""
    state_counts: dict[str, int] = {}
    written = 0
    for row in rows:
        for gate, result in evaluate_all(row):
            key = f"{gate.name}:{result.state}"
            state_counts[key] = state_counts.get(key, 0) + 1
            if cur is None:
                continue
            cur.execute(
                _UPSERT_SQL,
                (
                    row["id"], gate.name, result.state, result.reason,
                    Json(result.evidence) if result.evidence is not None else None,
                    gate.mode, datetime.now(timezone.utc),
                ),
            )
            written += 1
    return state_counts, written


def run(days: int | None = None, dry_run: bool = False) -> dict:
    rows = query(_SELECT_SQL, (days, days))

    if dry_run:
        state_counts, written = _replay(rows)
    else:
        with connection() as conn:
            conn.autocommit = True
            cur = conn.cursor()
            state_counts, written = _replay(rows, cur)

    return {"candidates": len(rows), "gate_rows_written": written, "state_counts": state_counts}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=None, help="only replay rows published in the last N days (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written without writing it")
    args = ap.parse_args()

    print(f"Replaying {[g.name for g in GATES]} over rows with a stored extraction"
          f"{f' from the last {args.days} days' if args.days else ''}"
          f"{' (dry run)' if args.dry_run else ''} ...")
    res = run(days=args.days, dry_run=args.dry_run)
    print(f"\n{res['candidates']} candidates, {res['gate_rows_written']} gate-rows written\n")
    print("State counts:")
    for key in sorted(res["state_counts"]):
        print(f"  {key:<32} {res['state_counts'][key]}")


if __name__ == "__main__":
    main()
