"""GitHub Actions status client for the admin /status page.

Fetches the latest run of each CI/monitoring workflow so the admin page can
mirror the Actions tab in one place, alongside the live health panel. Called
server-side only from GET /api/status with a read-only token
(GITHUB_STATUS_TOKEN) so the token never reaches the browser.

Design notes:
  - The Dokploy refresh crons are NOT here — their health is covered by the
    data-freshness checks in healthcheck.py (panel 1). This lists only the
    GitHub-Actions-hosted workflows (panel 2).
  - Results are cached in-process (~5 min) to stay well under GitHub's rate
    limit and keep the admin page snappy; a manual page refresh inside the TTL
    is served from cache.
  - Fails soft: if the token is unset or any request errors, latest_runs()
    returns a sentinel {"available": False, ...} rather than raising, so the
    /status endpoint never 500s because GitHub is unreachable.

Env:
  GITHUB_STATUS_TOKEN — fine-grained PAT, read-only, Actions:read on the single
                        finscope repo. Unset → CI panel shows "unavailable".
"""
import os
import time

import httpx

_REPO = "rxs30279/finscope"

# Workflow files whose latest run we surface. Keep in sync with .github/workflows/.
WORKFLOWS = [
    "healthcheck.yml",
    "backend-tests.yml",
    "smoke.yml",
    "e2e.yml",
    "refresh-analysts.yml",
    "refresh-financials.yml",
]

_CACHE_TTL = 300  # seconds; a page refresh within this window is served cached
_cache: dict | None = None
_cache_at: float = 0.0


def _fetch_one(client: httpx.Client, workflow: str) -> dict:
    """Latest run for one workflow file. Raises on transport/HTTP error so the
    caller can mark the whole panel unavailable (all-or-nothing keeps the UI
    honest — a half-populated panel would look like some workflows never ran)."""
    r = client.get(
        f"https://api.github.com/repos/{_REPO}/actions/workflows/{workflow}/runs",
        params={"per_page": 1, "exclude_pull_requests": "true"},
    )
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return {
            "workflow": workflow,
            "status": None,
            "conclusion": None,
            "run_started_at": None,
            "html_url": None,
        }
    run = runs[0]
    return {
        "workflow": workflow,
        "status": run.get("status"),            # queued | in_progress | completed
        "conclusion": run.get("conclusion"),    # success | failure | cancelled | null
        "run_started_at": run.get("run_started_at"),
        "html_url": run.get("html_url"),
    }


def _load() -> dict:
    """Uncached fetch of every workflow's latest run. Returns the sentinel shape
    {"available": bool, ...} — never raises."""
    token = os.environ.get("GITHUB_STATUS_TOKEN", "").strip()
    if not token:
        return {"available": False, "error": "GITHUB_STATUS_TOKEN not set"}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(headers=headers, timeout=15.0) as client:
            workflows = [_fetch_one(client, wf) for wf in WORKFLOWS]
        return {"available": True, "workflows": workflows}
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}: {e}"}


def latest_runs(force: bool = False) -> dict:
    """Cached (~5 min) latest-run status per workflow.

    Returns {"available": True, "workflows": [...]} on success, or
    {"available": False, "error": "..."} if the token is unset or GitHub is
    unreachable. `force=True` bypasses the cache (used by nothing yet; handy
    for a future manual re-poll)."""
    global _cache, _cache_at
    now = time.time()
    if not force and _cache is not None and now - _cache_at < _CACHE_TTL:
        return _cache
    _cache = _load()
    _cache_at = now
    return _cache
