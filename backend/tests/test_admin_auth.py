"""The expensive refresh/LLM POST endpoints must reject callers without the
admin token (see admin_auth.py). The authenticated happy paths are covered by
the existing endpoint tests, whose client fixture sends the header.
"""
import pytest
from fastapi.testclient import TestClient

from main import app

GUARDED = [
    "/api/prices/refresh",
    "/api/prices/refresh/SHEL.L",
    "/api/analysts/refresh",
    "/api/rns/refresh",
    "/api/rns/backfill-summaries",
    "/api/rns/rank",
    "/api/rns/rank/1",
    "/api/news/SHEL.L/summary",
]


@pytest.mark.parametrize("path", GUARDED)
def test_rejects_missing_token(path):
    bare = TestClient(app)
    r = bare.post(path)
    assert r.status_code == 403


@pytest.mark.parametrize("path", GUARDED)
def test_rejects_wrong_token(path):
    bare = TestClient(app)
    r = bare.post(path, headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 403


def test_fails_closed_when_token_unconfigured(monkeypatch):
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    bare = TestClient(app)
    r = bare.post("/api/rns/refresh", headers={"X-Admin-Token": "anything"})
    assert r.status_code == 503
