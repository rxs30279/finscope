"""What code is this process actually running?

Every internals-only backend change so far has been deploy-verified by SSHing
into the Dokploy host, or by hunting for some incidental side effect of the
change in a public response (a new gate name on /api/gates, a new symbol in the
vet prompt). Both are indirect, and both have cost a false "it's broken"
investigation when the answer was "the build wasn't live yet".

This module answers the question directly, and GET /api/version publishes it.

Two independent identifiers, because in this deployment neither alone is enough:

  * ``sha`` — the git commit, read from the environment. Only present if the
    image was built with the GIT_SHA build arg (see the Dockerfile); Dokploy
    does not inject one on its own, so treat this as best-effort.
  * ``source_fingerprint`` — a sha256 over the .py files that shipped inside the
    container, computed at runtime. Always present, needs no build wiring, and
    changes whenever any backend source file changes. This is the field to
    compare before and after a redeploy.

The fingerprint is not a git hash: it covers the deployed tree, not history, so
it cannot tell you *which* commit is live — only whether the bytes changed. That
is exactly what the deploy probe needs.
"""
import hashlib
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent

# Directories whose contents are irrelevant to what the API serves, or which
# differ between the repo and the image for reasons that aren't code changes.
_SKIP_DIRS = {"__pycache__", ".pytest_cache", "logs", "research_images"}

# Set by the Dockerfile from the GIT_SHA build arg. SOURCE_COMMIT / COMMIT_SHA
# are the names other PaaS builders use, accepted so a future host that injects
# one for free just works.
_SHA_ENV_VARS = ("GIT_SHA", "SOURCE_COMMIT", "COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA")

# Process start, captured at import. A changed source_fingerprint proves new
# code; started_at distinguishes "redeployed" from "restarted on the same image".
STARTED_AT = time.time()

_cache: dict | None = None


def _source_files() -> list[Path]:
    """Every .py file shipped alongside this module, sorted for a stable hash."""
    files = []
    for path in _BACKEND_DIR.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.relative_to(_BACKEND_DIR).parts):
            continue
        files.append(path)
    return sorted(files)


def _fingerprint() -> tuple[str, int]:
    """(sha256 hex, file count) over the deployed source tree.

    Hashes the relative path as well as the bytes, so adding, deleting or
    renaming a file moves the digest even when no file's contents change.
    """
    h = hashlib.sha256()
    files = _source_files()
    for path in files:
        rel = path.relative_to(_BACKEND_DIR).as_posix()
        h.update(rel.encode())
        h.update(b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            # A file that vanished mid-walk still has to affect the digest, or
            # two different trees could hash the same.
            h.update(b"<unreadable>")
        h.update(b"\n")
    return h.hexdigest(), len(files)


def _git_sha() -> tuple[str | None, str]:
    """(sha, source) — the env var if the build baked one in, else a local
    `git rev-parse` for dev runs outside the container, else (None, "unknown").

    The subprocess is a dev-machine convenience: inside the image there is no
    git binary and no .git dir, so it fails immediately and we fall through.
    """
    for var in _SHA_ENV_VARS:
        val = (os.environ.get(var) or "").strip()
        if val:
            return val, f"env:{var}"
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_BACKEND_DIR, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip(), "git"
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "unknown"


def collect(refresh: bool = False) -> dict:
    """Build identity for this process. Computed once and cached — the file walk
    is a few MB of reads, cheap but not free, and the answer cannot change
    without a restart (the source is baked into the image).

    `refresh=True` recomputes; only useful in dev, where the files on disk do
    change under a running --reload server.
    """
    global _cache
    if _cache is None or refresh:
        sha, sha_source = _git_sha()
        digest, count = _fingerprint()
        _cache = {
            "sha": sha,
            "sha_source": sha_source,
            "source_fingerprint": digest[:16],
            "source_files": count,
            "started_at": datetime.fromtimestamp(STARTED_AT, timezone.utc).isoformat(),
        }
    out = dict(_cache)
    out["uptime_seconds"] = round(time.time() - STARTED_AT, 1)
    return out
