"""Dokploy cron entry point -- drain SES delivery events from SQS.

Pulls SES send/delivery/bounce/complaint events off the SQS queue and writes
them to email_events, which is what the /status deliverability card reads.

Unlike the Resend webhook this replaces, nothing pushes to us -- so if this
cron stops running, delivery history simply stops existing and everything
looks healthy. The pipeline_runs stamp below is the guard: healthcheck.py
reads it, so a silent drain failure surfaces as a failed check rather than an
empty card nobody questions. Queue retention is 14 days, so a drain that is
down for a weekend loses nothing once it resumes.

Schedule: */15 7-18 * * 1-5 (UTC) -- the digest goes out at 07:30 and
deferral events trickle in for hours afterwards.

Usage:
    python run_email_events.py
"""

import os
import sys
import traceback
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from ses_events import drain_queue


def record_run(status: str, detail: dict) -> None:
    """Stamp pipeline_runs('ses_events') -- migration-008 convention, mirrors
    shorts.record_run(). Best-effort: a marker failure must never fail an
    otherwise-good drain."""
    import psycopg2.extras
    from db import connection

    with connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
            VALUES ('ses_events', NOW(), %s, %s)
            ON CONFLICT (pipeline) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                status      = EXCLUDED.status,
                detail      = EXCLUDED.detail
            """,
            (status, psycopg2.extras.Json(detail)),
        )
        conn.commit()


def main() -> int:
    print(f"[ses-events] drain starting at {datetime.now(timezone.utc).isoformat()}")
    try:
        result = drain_queue()
    except Exception as e:
        # Couldn't even start (SES_EVENT_QUEUE_URL missing, client init
        # failure) -- nothing was drained, so there's no partial stats to keep.
        print(f"[ses-events] drain FAILED to start -- {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            record_run("error", {"error": str(e)})
        except Exception:
            pass
        return 1

    if "error" in result:
        # Crashed mid-loop -- `result` still carries whatever was drained
        # before the failure, unlike discarding it for a bare {"error": ...}.
        print(f"[ses-events] drain FAILED -- {result['error']}")
        try:
            record_run("error", result)
        except Exception as e:
            print(f"[ses-events] pipeline_runs stamp FAILED (non-fatal) -- {type(e).__name__}: {e}")
        return 1

    print(f"[ses-events] drain done -- {result}")
    try:
        record_run("ok", result)
    except Exception as e:
        print(f"[ses-events] pipeline_runs stamp FAILED (non-fatal) -- {type(e).__name__}: {e}")

    print("[ses-events] completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
