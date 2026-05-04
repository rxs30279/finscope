"""Render web service — RNS pipeline trigger.

Exposes a single endpoint that cron-job.org calls on schedule. The pipeline
runs in a background thread with a concurrency lock to prevent overlapping runs.

cron-job.org schedules (all times UTC):
  */15 6-9 * * *   — every 15 min during RNS drop window
  0 10 * * *       — final morning slot
  0 16,17 * * *    — afternoon catch-up

Environment variables required:
  CRON_AUTH_TOKEN   — shared secret passed as ?token= query param
  DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT — Supabase connection
  DEEPSEEK_API_KEY  — for LLM ranking
  DEEPSEEK_MODEL    — (optional, default: deepseek-chat)
"""

import sys
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

# ── Imports from the existing codebase ────────────────────────────────────────
from rns import _run_ingest, _backfill_summaries, _prune_old
from rns_llm import _rank_pending
from refresh_rns import _compute_max_pages
from prices import refresh_prices

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="RNS Pipeline Worker")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CRON_TOKEN = os.environ.get("CRON_AUTH_TOKEN", "")
if not _CRON_TOKEN:
    print("[render] WARNING: CRON_AUTH_TOKEN not set — endpoint is unauthenticated!")

# ── Concurrency lock ──────────────────────────────────────────────────────────

_lock = threading.Lock()
_run_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "stage": None,
    "stages": {},
    "error": None,
    "run_id": 0,
}
_LOCK_TIMEOUT_S = 30 * 60  # 30-minute safety timeout


def _acquire_lock() -> bool:
    """Try to acquire the run lock. Returns True if acquired, False if busy."""
    global _run_state
    if not _lock.acquire(blocking=False):
        return False

    # Check safety timeout — if the previous run has been running for >30 min,
    # assume it crashed and allow a new run anyway.
    if _run_state["running"] and _run_state["started_at"] is not None:
        elapsed = time.time() - _run_state["started_at"]
        if elapsed > _LOCK_TIMEOUT_S:
            print(
                f"[render] previous run started {elapsed:.0f}s ago — "
                f"exceeded safety timeout, allowing new run"
            )
            _run_state["running"] = False
        else:
            _lock.release()
            return False

    _run_state["running"] = True
    _run_state["started_at"] = time.time()
    _run_state["finished_at"] = None
    _run_state["stage"] = None
    _run_state["stages"] = {}
    _run_state["error"] = None
    _run_state["run_id"] += 1
    _lock.release()
    return True


def _release_lock():
    global _run_state
    _lock.acquire()
    _run_state["running"] = False
    _run_state["finished_at"] = time.time()
    _lock.release()


def _set_stage(stage: str):
    _lock.acquire()
    _run_state["stage"] = stage
    _lock.release()


def _record_stage(name: str, result: dict):
    _lock.acquire()
    _run_state["stages"][name] = result
    _lock.release()


# ── Pipeline runner ───────────────────────────────────────────────────────────


def _run_pipeline():
    """Execute the full RNS pipeline: ingest → summaries → rank → prune."""
    run_id = _run_state["run_id"]
    print(
        f"[render] [{run_id}] pipeline starting at {datetime.now(timezone.utc).isoformat()}"
    )

    try:
        # Stage 1: Ingest
        _set_stage("ingest")
        max_pages, reason = _compute_max_pages()
        print(f"[render] [{run_id}] ingest: {reason}")
        ingest_result = _run_ingest(
            max_pages=max_pages, stop_on_known=True, sleep_s=1.5
        )
        _record_stage("ingest", {"ok": True, **ingest_result})
        print(f"[render] [{run_id}] ingest done — {ingest_result}")

        # Stage 2: Backfill summaries
        _set_stage("summaries")
        summary_result = _backfill_summaries(limit=50, sleep_s=1.0, tiers=("A", "B"))
        _record_stage("summaries", {"ok": True, **summary_result})
        print(f"[render] [{run_id}] summaries done — {summary_result}")

        # Stage 3: LLM rank
        _set_stage("rank")
        rank_result = _rank_pending(limit=50, tiers=("A", "B"), hours=48)
        _record_stage("rank", {"ok": True, **rank_result})
        print(f"[render] [{run_id}] ranking done — {rank_result}")

        # Stage 4: Prune old rows (keep 14 days)
        _set_stage("prune")
        prune_result = _prune_old(days=14)
        _record_stage("prune", {"ok": True, **prune_result})
        print(f"[render] [{run_id}] prune done — {prune_result}")

        print(f"[render] [{run_id}] pipeline completed successfully")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[render] [{run_id}] pipeline FAILED — {error_msg}")
        traceback.print_exc()
        _lock.acquire()
        _run_state["error"] = error_msg
        _lock.release()
        _record_stage("error", {"error": error_msg})

    finally:
        _release_lock()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Render uses this to check the service is alive."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/rns/run")
def run_pipeline(token: str = Query(...)):
    """Trigger the full RNS pipeline.

    Called by cron-job.org on schedule. Requires ?token=<CRON_AUTH_TOKEN>.
    Returns immediately with status "started" or "skipped" (if a run is already
    in progress). The pipeline runs in a background thread.
    """
    if _CRON_TOKEN and token != _CRON_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    if not _acquire_lock():
        return {
            "status": "skipped",
            "reason": "Run already in progress",
            "run_id": _run_state["run_id"],
        }

    # Start pipeline in background thread
    t = threading.Thread(target=_run_pipeline, daemon=True)
    t.start()

    return {
        "status": "started",
        "run_id": _run_state["run_id"],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/rns/status")
def pipeline_status():
    """Return the current/last run state."""
    _lock.acquire()
    state = dict(_run_state)
    _lock.release()

    # Convert timestamps to ISO strings for JSON serialisation
    if state.get("started_at"):
        state["started_at"] = datetime.fromtimestamp(
            state["started_at"], tz=timezone.utc
        ).isoformat()
    if state.get("finished_at"):
        state["finished_at"] = datetime.fromtimestamp(
            state["finished_at"], tz=timezone.utc
        ).isoformat()

    return state


@app.get("/api/rns/log")
def pipeline_log(lines: int = Query(50, ge=1, le=500)):
    """Return the last N lines of the Render log (captured from stdout).

    Note: Render captures stdout natively in its dashboard. This endpoint
    provides a convenience view for the most recent log lines.
    """
    # We can't easily capture stdout retroactively, so return a pointer
    # to the Render dashboard. The real logs are visible in Render's UI.
    return {
        "note": "Full logs are available in the Render dashboard → Logs tab",
        "dashboard_url": None,
        "last_run": _run_state.get("run_id"),
    }


@app.get("/api/prices/run")
def run_price_refresh(token: str = Query(...)):
    """Trigger a daily price refresh for all stocks.

    Called by cron-job.org once daily after market close.
    Requires ?token=<CRON_AUTH_TOKEN>.
    Runs synchronously — fetches missing OHLCV data from yfinance and upserts.
    """
    if _CRON_TOKEN and token != _CRON_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    print(
        f"[render] price refresh starting at {datetime.now(timezone.utc).isoformat()}"
    )
    try:
        result = refresh_prices()
        print(f"[render] price refresh done — {result}")
        return {"status": "ok", **result}
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[render] price refresh FAILED — {error_msg}")
        traceback.print_exc()
        return {"status": "error", "error": error_msg}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("render_app:app", host="0.0.0.0", port=port, reload=False)
