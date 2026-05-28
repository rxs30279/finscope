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
from breakout import (
    _compute_breakout_scores,
    _upsert_scores,
    _upsert_signals,
    _compute_backtest,
)
from _mem import snapshot as _mem

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

# _run_mutex is held for the *entire* duration of a pipeline run — acquired in
# the HTTP handler, released in the worker thread's finally. This prevents the
# back-to-back race observed on 2026-05-22 where two cron-job.org pings landed
# <1ms apart and both passed the "running" check because the previous run had
# just cleared it.
_run_mutex = threading.Lock()
# _state_lock guards mutations to _run_state (short critical sections only).
_state_lock = threading.Lock()
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
    """Try to claim the right to start a pipeline run.

    On success, _run_mutex is held; caller must ensure _release_lock() runs
    (the worker thread's finally block does this).
    """
    if not _run_mutex.acquire(blocking=False):
        # Mutex held by an in-flight run. Check for a stale lock from a
        # previous run that crashed without releasing (e.g. SIGKILL from OOM).
        with _state_lock:
            started_at = _run_state.get("started_at")
            running = _run_state.get("running")
        if running and started_at is not None:
            elapsed = time.time() - started_at
            if elapsed > _LOCK_TIMEOUT_S:
                print(
                    f"[render] previous run started {elapsed:.0f}s ago — "
                    f"exceeded safety timeout, forcing release"
                )
                try:
                    _run_mutex.release()
                except RuntimeError:
                    pass
                if not _run_mutex.acquire(blocking=False):
                    return False
            else:
                return False
        else:
            return False

    with _state_lock:
        _run_state["running"] = True
        _run_state["started_at"] = time.time()
        _run_state["finished_at"] = None
        _run_state["stage"] = None
        _run_state["stages"] = {}
        _run_state["error"] = None
        _run_state["run_id"] += 1
    return True


def _release_lock():
    with _state_lock:
        _run_state["running"] = False
        _run_state["finished_at"] = time.time()
    try:
        _run_mutex.release()
    except RuntimeError:
        pass


def _set_stage(stage: str):
    with _state_lock:
        _run_state["stage"] = stage


def _record_stage(name: str, result: dict):
    with _state_lock:
        _run_state["stages"][name] = result


# ── Pipeline runner ───────────────────────────────────────────────────────────


def _run_pipeline():
    """Execute the full RNS pipeline: ingest → summaries → rank → prune."""
    run_id = _run_state["run_id"]
    print(
        f"[render] [{run_id}] pipeline starting at {datetime.now(timezone.utc).isoformat()}"
    )
    _mem("pipeline", "start", run_id=run_id)

    try:
        # Stage 1: Ingest
        _set_stage("ingest")
        _mem("ingest", "start", run_id=run_id)
        max_pages, reason = _compute_max_pages()
        print(f"[render] [{run_id}] ingest: {reason}")
        ingest_result = _run_ingest(
            max_pages=max_pages, stop_on_known=True, sleep_s=1.5
        )
        _record_stage("ingest", {"ok": True, **ingest_result})
        print(f"[render] [{run_id}] ingest done — {ingest_result}")
        _mem("ingest", "end", run_id=run_id, max_pages=max_pages,
             inserted=ingest_result.get("inserted"))

        # Stage 2: Backfill summaries
        _set_stage("summaries")
        _mem("summaries", "start", run_id=run_id)
        summary_result = _backfill_summaries(limit=50, sleep_s=1.0, tiers=("A", "B"))
        _record_stage("summaries", {"ok": True, **summary_result})
        print(f"[render] [{run_id}] summaries done — {summary_result}")
        _mem("summaries", "end", run_id=run_id,
             fetched=summary_result.get("fetched"))

        # Stage 3: LLM rank
        _set_stage("rank")
        _mem("rank", "start", run_id=run_id)
        rank_result = _rank_pending(limit=50, tiers=("A", "B"), hours=48)
        _record_stage("rank", {"ok": True, **rank_result})
        print(f"[render] [{run_id}] ranking done — {rank_result}")
        _mem("rank", "end", run_id=run_id, ranked=rank_result.get("ranked"))

        # Stage 4: Prune old rows (keep 14 days)
        _set_stage("prune")
        _mem("prune", "start", run_id=run_id)
        prune_result = _prune_old(days=14)
        _record_stage("prune", {"ok": True, **prune_result})
        print(f"[render] [{run_id}] prune done — {prune_result}")
        _mem("prune", "end", run_id=run_id, deleted=prune_result.get("deleted"))

        print(f"[render] [{run_id}] pipeline completed successfully")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[render] [{run_id}] pipeline FAILED — {error_msg}")
        traceback.print_exc()
        with _state_lock:
            _run_state["error"] = error_msg
        _record_stage("error", {"error": error_msg})

    finally:
        _mem("pipeline", "end", run_id=run_id)
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
    with _state_lock:
        state = dict(_run_state)

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
    _mem("price_refresh", "start")
    try:
        result = refresh_prices()
        print(f"[render] price refresh done — {result}")
        _mem("price_refresh", "end", rows_added=result.get("rows_added"))
        return {"status": "ok", **result}
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[render] price refresh FAILED — {error_msg}")
        traceback.print_exc()
        _mem("price_refresh", "error")
        return {"status": "error", "error": error_msg}


@app.get("/api/breakout/run")
def run_breakout(token: str = Query(...)):
    """Compute breakout scores for all stocks.

    Called by cron-job.org ~30 min after the daily price refresh.
    Requires ?token=<CRON_AUTH_TOKEN>.
    Runs synchronously — fetches price history, computes indicators, upserts.
    """
    if _CRON_TOKEN and token != _CRON_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    t0 = time.time()
    print(
        f"[render] breakout computation starting at {datetime.now(timezone.utc).isoformat()}"
    )
    _mem("breakout", "start")
    try:
        results = _compute_breakout_scores()
        _mem("breakout", "scores_computed", n=len(results))
        if not results:
            return {
                "status": "ok",
                "stocks_processed": 0,
                "signals": 0,
                "duration_seconds": round(time.time() - t0, 1),
                "message": "No stocks processed",
            }

        scores_count = _upsert_scores(results)
        signals_count = _upsert_signals(results)
        _mem("breakout", "upserted", signals=signals_count)

        # Run backtest for today's signals
        backtest_result = _compute_backtest()
        _mem("breakout", "end", signals=signals_count)

        print(
            f"[render] breakout done — {len(results)} stocks, {signals_count} signals"
        )
        return {
            "status": "ok",
            "stocks_processed": len(results),
            "signals": signals_count,
            "duration_seconds": round(time.time() - t0, 1),
            "backtest": backtest_result,
        }
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"[render] breakout FAILED — {error_msg}")
        traceback.print_exc()
        _mem("breakout", "error")
        return {"status": "error", "error": error_msg}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("render_app:app", host="0.0.0.0", port=port, reload=False)
