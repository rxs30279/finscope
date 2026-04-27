"""GitHub Actions REST helpers — workflow_dispatch + run status.

Used by /api/rns/pipeline and /api/analysts/refresh to trigger the same
workflow that runs on cron. Vercel serverless functions can't host the
underlying multi-minute jobs (function timeouts kill them and module-level
status state isn't shared across cold-started instances), so user-triggered
refreshes hand off to GitHub Actions runners and the UI polls the run state
back via the REST API.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional


GH_REPO = os.environ.get("GH_REPO", "rxs30279/finscope")
GH_REF  = os.environ.get("GH_REF", "main")
GH_API  = "https://api.github.com"

# GitHub run statuses that mean "still working".
ACTIVE_STATUSES = ("queued", "in_progress", "waiting", "requested", "pending")


def _request(method: str, path: str, body: Optional[dict] = None) -> Optional[dict]:
    token = os.environ.get("GH_DISPATCH_TOKEN")
    if not token:
        raise RuntimeError("GH_DISPATCH_TOKEN env var not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{GH_API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization":        f"Bearer {token}",
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent":           "alpha-move-ai",
            "Content-Type":         "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        if not raw:
            return None
        return json.loads(raw.decode())


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def dispatch(workflow: str) -> str:
    """Fire workflow_dispatch on the named workflow (e.g. 'refresh-rns.yml').

    Returns a `dispatched_at` ISO timestamp; the caller hands it to the UI,
    which echoes it back via pipeline_status(since=...) so older completed
    runs aren't mistaken for the run we just kicked off.
    """
    dispatched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _request("POST",
             f"/repos/{GH_REPO}/actions/workflows/{workflow}/dispatches",
             body={"ref": GH_REF})
    return dispatched_at


def pipeline_status(workflow: str, since: Optional[str]) -> dict:
    """UI-friendly status for the latest workflow_dispatch run of `workflow`.

    Shape mirrors the legacy in-process pipeline status: running, stage,
    started_at, finished_at, stages. Returns dormant on transient API errors
    so the polling UI doesn't crash.
    """
    empty = {"running": False, "stage": None, "started_at": None,
             "finished_at": None, "stages": {}}
    try:
        data = _request(
            "GET",
            f"/repos/{GH_REPO}/actions/workflows/{workflow}/runs"
            "?event=workflow_dispatch&per_page=1",
        )
    except Exception:
        return empty

    runs = (data or {}).get("workflow_runs") or []
    run  = runs[0] if runs else None

    since_dt    = _parse_iso(since)
    started_iso = (run.get("run_started_at") or run.get("created_at")) if run else None
    started_dt  = _parse_iso(started_iso)

    is_ours = (run is not None and started_dt is not None
               and (since_dt is None or started_dt >= since_dt))

    if not is_ours:
        # Hold the UI in "queueing" for the first 90s after dispatch instead of
        # false-firing "complete" when GitHub hasn't created the run record yet.
        if since_dt is not None:
            age = (datetime.now(timezone.utc) - since_dt).total_seconds()
            if age < 90:
                return {"running": True, "stage": "queueing", "started_at": since,
                        "finished_at": None, "stages": {}}
        return empty

    status  = run.get("status") or ""
    running = status in ACTIVE_STATUSES
    return {
        "running":     running,
        "stage":       status if running else None,
        "started_at":  started_iso,
        "finished_at": run.get("updated_at") if not running else None,
        "stages":      {},
        "conclusion":  run.get("conclusion"),
        "html_url":    run.get("html_url"),
    }
