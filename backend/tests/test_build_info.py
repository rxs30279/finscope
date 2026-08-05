"""Tests for build identity (backend/build_info.py) and GET /api/version.

Hermetic: the fingerprint walks a temp directory, and the endpoint touches no
DB or network. The point of these is that the deploy probe stays trustworthy —
a fingerprint that fails to move after a source change would be worse than no
probe at all, because it would read as "the deploy didn't land".
"""
import pytest
from fastapi.testclient import TestClient

import build_info
from main import app


@pytest.fixture(autouse=True)
def _clear_cache():
    """collect() memoises for the process lifetime; tests mutate the env and
    the source dir, so each starts from cold."""
    build_info._cache = None
    yield
    build_info._cache = None


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Point the fingerprint at a throwaway source tree."""
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text("y = 2\n")
    monkeypatch.setattr(build_info, "_BACKEND_DIR", tmp_path)
    return tmp_path


def test_fingerprint_is_stable_across_calls(tree):
    assert build_info._fingerprint() == build_info._fingerprint()


def test_fingerprint_moves_when_a_file_changes(tree):
    before, count = build_info._fingerprint()
    (tree / "pkg" / "b.py").write_text("y = 3\n")
    after, count_after = build_info._fingerprint()
    assert after != before
    assert (count, count_after) == (2, 2)


def test_fingerprint_moves_when_a_file_is_added_or_renamed(tree):
    before, _ = build_info._fingerprint()
    (tree / "c.py").write_text("z = 3\n")
    added, _ = build_info._fingerprint()
    assert added != before
    # A rename keeps every byte of content but must still move the digest —
    # that's why the path is hashed alongside the bytes.
    (tree / "c.py").rename(tree / "d.py")
    assert build_info._fingerprint()[0] != added


def test_fingerprint_ignores_pycache_and_non_python(tree):
    before, count = build_info._fingerprint()
    (tree / "__pycache__").mkdir()
    (tree / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\x00compiled")
    (tree / "notes.md").write_text("not code\n")
    after, count_after = build_info._fingerprint()
    assert (after, count_after) == (before, count)


def test_sha_prefers_env_over_git(tree, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "deadbeef" * 5)
    assert build_info._git_sha() == ("deadbeef" * 5, "env:GIT_SHA")


def test_sha_is_none_when_unavailable(tree, monkeypatch):
    for var in build_info._SHA_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # No git repo under the temp tree, and _git_sha runs git there.
    monkeypatch.setattr(build_info.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    assert build_info._git_sha() == (None, "unknown")


def test_blank_env_sha_falls_through(tree, monkeypatch):
    """An unset Dockerfile build arg lands as an empty string, not an absent
    var — that must not be reported as the commit."""
    monkeypatch.setenv("GIT_SHA", "  ")
    monkeypatch.setenv("COMMIT_SHA", "abc123")
    assert build_info._git_sha() == ("abc123", "env:COMMIT_SHA")


def test_version_endpoint_is_public_and_hermetic():
    """No admin token, no DB: a bare client must get the payload."""
    r = TestClient(app).get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"sha", "sha_source", "source_fingerprint",
                         "source_files", "started_at", "uptime_seconds"}
    assert len(body["source_fingerprint"]) == 16
    assert body["source_files"] > 0
