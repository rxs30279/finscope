"""Smoke-test harness — hits the LIVE production API over HTTP.

Standalone by design: imports nothing from the backend app, needs only
pytest + httpx (backend/requirements-dev.txt), and never touches the DB. These
tests assert response *shape*, not values — data freshness stays the job of
backend/healthcheck.py. Point elsewhere with SMOKE_BASE_URL, e.g.
    SMOKE_BASE_URL=http://localhost:8000 python -m pytest smoke
"""
import os

import httpx
import pytest

BASE_URL = os.environ.get("SMOKE_BASE_URL", "https://api.alphamoveai.co.uk").rstrip("/")


@pytest.fixture(scope="session")
def client():
    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
        headers={"User-Agent": "alphamove-smoke/1.0"},
        follow_redirects=True,
    ) as c:
        yield c


@pytest.fixture
def get_json(client):
    """GET a path, assert 200 + JSON, return the parsed body."""
    def _get(path, **params):
        r = client.get(path, params=params or None)
        assert r.status_code == 200, f"GET {path} -> {r.status_code}: {r.text[:300]}"
        ctype = r.headers.get("content-type", "")
        assert "application/json" in ctype, f"GET {path} not JSON (content-type={ctype!r})"
        return r.json()
    return _get
