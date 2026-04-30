"""Inngest functions for the RNS pipeline.

Replaces the GitHub Actions cron schedule in .github/workflows/refresh-rns.yml.
Runs the same 3-stage pipeline (ingest → summaries → LLM rank) on the same
schedule, but as an Inngest function served by the FastAPI app on Vercel.

Cron schedule (matching the GitHub Actions schedule):
  - */15 6-9 * * *   — every 15 min 06:00-09:45 UTC (covers RNS drop window)
  - 0 10 * * *       — 10:00 UTC (final GMT-season slot)
  - 0 16,17 * * *    — 16:00, 17:00 UTC (afternoon catch-up)
"""

import sys
import os
import time
import traceback

# Ensure backend/ is on sys.path so we can import sibling modules
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

import inngest
from inngest import Context

from inngest_client import get_client
from refresh_rns import _compute_max_pages
from rns import _run_ingest, _backfill_summaries
from rns_llm import _rank_pending

_client = get_client()


@_client.create_function(
    fn_id="refresh-rns-pipeline",
    name="Refresh RNS Pipeline",
    trigger=inngest.TriggerCron(cron="*/15 6-9 * * *"),
    retries=2,
)
@_client.create_function(
    fn_id="refresh-rns-pipeline-10am",
    name="Refresh RNS Pipeline (10am)",
    trigger=inngest.TriggerCron(cron="0 10 * * *"),
    retries=2,
)
@_client.create_function(
    fn_id="refresh-rns-pipeline-afternoon",
    name="Refresh RNS Pipeline (afternoon)",
    trigger=inngest.TriggerCron(cron="0 16,17 * * *"),
    retries=2,
)
async def refresh_rns_pipeline(
    ctx: Context,
) -> dict:
    """Run the full RNS pipeline: ingest → AI summaries → LLM rank.

    Mirrors the logic in refresh_rns.py's __main__ block.
    Each stage is wrapped in step.run() so Inngest can retry individual
    steps on failure.
    """
    step = ctx.step
    logger = ctx.logger
    t_start = time.time()
    logger.info("rns-pipeline starting")

    # ── Stage 0: compute max pages ────────────────────────────────────────
    max_pages, reason = await step.run("compute-max-pages", _compute_max_pages)
    logger.info("max_pages=%s reason=%s", max_pages, reason)

    # ── Stage 1: ingest ───────────────────────────────────────────────────
    ingest_result = await step.run(
        "ingest",
        lambda: _run_ingest(max_pages=max_pages, stop_on_known=True, sleep_s=1.5),
    )
    logger.info("ingest done: %s", ingest_result)

    # ── Stage 2: backfill summaries ───────────────────────────────────────
    summary_result = await step.run(
        "summaries",
        lambda: _backfill_summaries(limit=50, sleep_s=1.0, tiers=("A", "B")),
    )
    logger.info("summaries done: %s", summary_result)

    # ── Stage 3: LLM rank ─────────────────────────────────────────────────
    ranking_result = await step.run(
        "rank",
        lambda: _rank_pending(limit=50, tiers=("A", "B"), hours=48),
    )
    logger.info("ranking done: %s", ranking_result)

    total = round(time.time() - t_start, 1)
    logger.info("rns-pipeline complete in %ss", total)

    return {
        "ok": True,
        "total_seconds": total,
        "max_pages": max_pages,
        "max_pages_reason": reason,
        "ingest": ingest_result,
        "summaries": summary_result,
        "ranking": ranking_result,
    }


# ── Event-triggered variant (for manual /api/rns/pipeline trigger) ────────────


@_client.create_function(
    fn_id="refresh-rns-pipeline-manual",
    name="Refresh RNS Pipeline (manual)",
    trigger=inngest.TriggerEvent(event="rns/pipeline.run"),
    retries=2,
)
async def refresh_rns_pipeline_manual(
    ctx: Context,
) -> dict:
    """Same pipeline but triggered by an event (e.g. from the API endpoint).

    Accepts optional max_pages override from the event data.
    """
    step = ctx.step
    logger = ctx.logger
    t_start = time.time()
    logger.info("rns-pipeline (manual) starting")

    event_max_pages = (ctx.event.data or {}).get("max_pages")

    max_pages, reason = await step.run("compute-max-pages", _compute_max_pages)
    if event_max_pages is not None:
        max_pages = min(event_max_pages, 24)
        reason = f"overridden by event data: max_pages={max_pages}"
    logger.info("max_pages=%s reason=%s", max_pages, reason)

    ingest_result = await step.run(
        "ingest",
        lambda: _run_ingest(max_pages=max_pages, stop_on_known=True, sleep_s=1.5),
    )
    logger.info("ingest done: %s", ingest_result)

    summary_result = await step.run(
        "summaries",
        lambda: _backfill_summaries(limit=50, sleep_s=1.0, tiers=("A", "B")),
    )
    logger.info("summaries done: %s", summary_result)

    ranking_result = await step.run(
        "rank",
        lambda: _rank_pending(limit=50, tiers=("A", "B"), hours=48),
    )
    logger.info("ranking done: %s", ranking_result)

    total = round(time.time() - t_start, 1)
    logger.info("rns-pipeline (manual) complete in %ss", total)

    return {
        "ok": True,
        "total_seconds": total,
        "max_pages": max_pages,
        "max_pages_reason": reason,
        "ingest": ingest_result,
        "summaries": summary_result,
        "ranking": ranking_result,
    }


# ── Exported list for the FastAPI serve call ──────────────────────────────────

functions = [
    refresh_rns_pipeline,
    refresh_rns_pipeline_manual,
]
