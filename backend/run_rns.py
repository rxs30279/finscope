"""Render Cron Job entry point — full RNS pipeline.

Runs ingest -> summaries -> LLM rank -> prune synchronously, then exits. This
replaces the /api/rns/run endpoint + cron-job.org trigger: Render's own
scheduler invokes this script directly (see render.yaml), so there is no HTTP
server, no background thread, and no keep-warm pinging. The instance lives until
this process exits, so the work can never be spun down mid-run.

Exits non-zero on failure so the Render cron run is marked failed (visible in
the dashboard and alertable), rather than failing silently.

Only one run may be in flight at a time (see RNS_PIPELINE_LOCK_KEY): the
schedules deliberately overlap, so a run that arrives while another is working
exits 0 immediately rather than duplicating it.
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from db import advisory_lock
from rns import _run_ingest, _backfill_summaries, _prune_old, in_urgent_window
from rns_llm import _rank_pending
from refresh_rns import _compute_max_pages, CATCHUP_PAGE_CAP, RNS_PIPELINE_LOCK_KEY

# 80, not 50. Measured over 30 days the morning Tier A/B batch runs 8-57 rows,
# and every day above 50 left rows for a second run — which at 5-8 min/run
# lands well past the send and straddles it. The cap has to clear the
# observed peak with headroom, not sit inside it.
#
# This is not free: the summary stage is serial at ~2s/row (one fetch plus
# sleep_s), so 80 rows is ~160s against 50 rows' ~100s. The urgent-window
# deferral of stages 3.5/3.6/4 below pays for it by freeing 1-4 min that used
# to go to the showcase vet before the send.
_SUMMARY_LIMIT = int(os.environ.get("RNS_SUMMARY_LIMIT", "80"))
_RANK_LIMIT    = int(os.environ.get("RNS_RANK_LIMIT", "80"))


def _record_ingest(status: str, detail: dict) -> None:
    """Stamp pipeline_runs('rns_ingest') — migration-008 convention, mirrors
    run_email_events.record_run(). Carries the incomplete flag across runs,
    which is the only durable place to put it: a truncated ingest is
    invisible in the data (the rows it missed simply never arrive), so the
    next run cannot otherwise know to sweep deeper than stop_on_known allows.
    Best-effort: a marker failure must never fail an otherwise-good ingest."""
    import psycopg2.extras
    from db import connection

    try:
        with connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
                VALUES ('rns_ingest', NOW(), %s, %s)
                ON CONFLICT (pipeline) DO UPDATE SET
                    last_run_at = EXCLUDED.last_run_at,
                    status      = EXCLUDED.status,
                    detail      = EXCLUDED.detail
                """,
                (status, psycopg2.extras.Json(detail)),
            )
            conn.commit()
    except Exception as e:
        print(f"[rns] pipeline_runs stamp FAILED (non-fatal) — {type(e).__name__}: {e}")


def _last_ingest_incomplete() -> bool:
    from db import query

    try:
        rows = query(
            "SELECT status, detail FROM pipeline_runs WHERE pipeline = 'rns_ingest'"
        )
    except Exception:
        return False
    return bool(rows) and rows[0]["status"] != "ok"


def main() -> int:
    """Take the pipeline lock, then run. Losing the lock is a normal outcome,
    not a failure: two Dokploy schedules cover the morning drop (a burst every
    3 min from 07:01, plus a 15-min sweep from 07:00), while a full run takes
    ~5-8 minutes to rank the 07:00 batch. Without the lock those runs overlap,
    and because _rank_pending selects on `llm_processed_at IS NULL` with no row
    claim, each overlapping run re-ranks whatever the previous one hasn't
    written yet — duplicate DeepSeek calls for identical scores.
    """
    with advisory_lock(RNS_PIPELINE_LOCK_KEY) as acquired:
        if not acquired:
            print("[rns] another pipeline run is in flight — skipping this run")
            return 0
        return _run_pipeline()


def _run_pipeline() -> int:
    print(f"[rns] pipeline starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        # Stage 1: Ingest
        max_pages, reason = _compute_max_pages()
        print(f"[rns] ingest: {reason}")
        # A previous run that aborted mid-sweep (rate limit / fetch error) left
        # rows on pages it never read, and stop_on_known would break at page 2
        # again next time and never reach them — see _run_ingest's "stopped"
        # outcome. Sweep the full depth once to close the hole, then resume
        # normal behaviour.
        resume = _last_ingest_incomplete()
        if resume:
            max_pages = max(max_pages, CATCHUP_PAGE_CAP)
            print(f"[rns] previous ingest was incomplete — deep sweep to {max_pages} pages")
        ingest = _run_ingest(
            max_pages=max_pages, stop_on_known=not resume, sleep_s=1.5
        )
        print(f"[rns] ingest done — {ingest}")
        _record_ingest(
            "ok" if ingest.get("complete") else ingest.get("stopped", "error"),
            ingest,
        )

        # Stage 2: Backfill summaries
        summaries = _backfill_summaries(limit=_SUMMARY_LIMIT, sleep_s=1.0, tiers=("A", "B"))
        print(f"[rns] summaries done — {summaries}")

        # Stage 3: LLM rank
        ranked = _rank_pending(limit=_RANK_LIMIT, tiers=("A", "B"), hours=48)
        print(f"[rns] ranking done — {ranked}")

        # Stages 3.5-4 are deferred inside the pre-send window. None of them
        # changes what the digest sends — it reads llm_score, never
        # vet_score — but the vet is serial, thinking-mode and ~40s/candidate,
        # so it holds the pipeline lock for 1-4 min while late-breaking
        # stories wait for an ingest slot they cannot get. Post-send there is
        # no contention and the next sweep picks all three up unchanged.
        if in_urgent_window():
            print("[rns] pre-send window — deferring showcase/gates/prune")
            print("[rns] pipeline completed successfully (ranking only)")
            return 0

        # Stage 3.5: High Impact RNS showcase — flag new candidates and snapshot
        # follow-ups for tracked companies. Entries stay live until the admin
        # archives them manually (no auto-archive). Runs after ranking (needs
        # llm_* populated) and before the prune (needs the follow-ups copied out
        # before the source rows are deleted). Non-fatal: a showcase bug must
        # never block the prune stage that keeps the table from growing unbounded.
        try:
            from showcase import flag_high_impact_candidates, record_followups
            print(f"[rns] showcase flagging — {flag_high_impact_candidates(hours=48)}")
            print(f"[rns] showcase follow-ups — {record_followups()}")
        except Exception as e:
            print(f"[rns] showcase stage FAILED (non-fatal) — {type(e).__name__}: {e}")

        # Stage 3.6: gate recording (docs/rns-gate-block-plan.md) — evaluate
        # every gate over every ranked Tier A/B row (not just flag candidates;
        # see gates.py's "evaluate wide, block narrow"), so /gates has a real
        # calibration sample. Pure Python over rows already in memory-shape from
        # stage 3 — no LLM cost. Non-fatal for the same reason as showcase above.
        try:
            from gates import record_gate_evaluations
            print(f"[rns] gate recording — {record_gate_evaluations(hours=48)}")
        except Exception as e:
            print(f"[rns] gate recording FAILED (non-fatal) — {type(e).__name__}: {e}")

        # Stage 4: Prune old rows (Tier C only, keep 14 days; A/B retained indefinitely)
        pruned = _prune_old(days=14)
        print(f"[rns] prune done — {pruned}")

        print("[rns] pipeline completed successfully")
        return 0
    except Exception as e:
        print(f"[rns] pipeline FAILED — {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
