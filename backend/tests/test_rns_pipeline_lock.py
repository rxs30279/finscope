"""The RNS pipeline lock — the guard that keeps the deliberately-overlapping
Dokploy schedules (3-min burst + 15-min sweep) from re-ranking the same rows.
"""
import sys, os
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import run_rns
from refresh_rns import RNS_PIPELINE_LOCK_KEY


@contextmanager
def _lock_returning(acquired: bool, seen: list):
    """Stand in for db.advisory_lock, recording the key it was asked for."""
    def _fake(key):
        seen.append(key)
        @contextmanager
        def _cm():
            yield acquired
        return _cm()
    original = run_rns.advisory_lock
    run_rns.advisory_lock = _fake
    try:
        yield
    finally:
        run_rns.advisory_lock = original


def test_skips_pipeline_when_lock_is_held(monkeypatch):
    """A run arriving mid-flight must not touch the pipeline at all."""
    ran = []
    monkeypatch.setattr(run_rns, "_run_pipeline", lambda: ran.append(True) or 0)

    seen = []
    with _lock_returning(False, seen):
        rc = run_rns.main()

    assert rc == 0, "a skipped run is a normal outcome, not a cron failure"
    assert ran == [], "pipeline body ran despite another run holding the lock"


def test_runs_pipeline_when_lock_is_free(monkeypatch):
    ran = []
    monkeypatch.setattr(run_rns, "_run_pipeline", lambda: ran.append(True) or 0)

    seen = []
    with _lock_returning(True, seen):
        rc = run_rns.main()

    assert rc == 0
    assert ran == [True]


def test_uses_the_shared_lock_key(monkeypatch):
    """Both entry points must ask for the same key or there is no mutual
    exclusion — a drift here would silently disable the guard."""
    monkeypatch.setattr(run_rns, "_run_pipeline", lambda: 0)

    seen = []
    with _lock_returning(True, seen):
        run_rns.main()

    assert seen == [RNS_PIPELINE_LOCK_KEY]


def test_propagates_pipeline_failure_exit_code(monkeypatch):
    """Holding the lock must not mask a real failure — the cron still needs to
    go red so Dokploy surfaces it."""
    monkeypatch.setattr(run_rns, "_run_pipeline", lambda: 1)

    seen = []
    with _lock_returning(True, seen):
        assert run_rns.main() == 1


# ── db.advisory_lock ──────────────────────────────────────────────────────────

def test_lock_connects_on_the_session_port_not_the_pool_port(monkeypatch):
    """Regression guard for the bug this whole lock nearly shipped with: taken
    over the transaction pooler (6543) the lock excludes nobody *and* leaks
    permanently onto a pooler backend."""
    captured = {}

    class _Cur:
        def execute(self, *a): pass
        def fetchone(self): return (True,)

    class _Conn:
        autocommit = False
        def cursor(self): return _Cur()
        def close(self): pass

    def _fake_connect(**cfg):
        captured.update(cfg)
        return _Conn()

    monkeypatch.setattr(db.psycopg2, "connect", _fake_connect)
    # Pin both ports to known, *different* values. Reading them from the ambient
    # config instead made this test pass only where a .env set DB_PORT=6543 — on
    # CI both defaulted to 5432 and it failed on `'5432' != '5432'`, which said
    # nothing about the code under test.
    monkeypatch.setitem(db.DB_CONFIG, "port", "6543")
    monkeypatch.setattr(db, "_LOCK_PORT", "5432")

    with db.advisory_lock(123):
        pass

    assert captured["port"] == "5432", (
        "advisory lock must connect on the session port, not the pooled one"
    )


def test_lock_fails_open_when_unreachable(monkeypatch):
    """An unreachable session pooler must not stop the pipeline running —
    duplicated work is cheaper than no ingest at all."""
    def _boom(**cfg):
        raise OSError("no route to host")

    monkeypatch.setattr(db.psycopg2, "connect", _boom)
    with db.advisory_lock(123) as acquired:
        assert acquired is True


# ── The HTTP route ────────────────────────────────────────────────────────────
# POST /api/rns/rank used to call _rank_pending directly, outside the lock the
# crons take — so a manual rank during the 07:00 batch hit exactly the case the
# lock exists to prevent, and paid DeepSeek twice for identical scores.

def _patch_lock(monkeypatch, acquired: bool, seen: list):
    """_rank_pending_locked imports advisory_lock lazily, so patch it on db."""
    def _fake(key):
        seen.append(key)
        @contextmanager
        def _cm():
            yield acquired
        return _cm()
    monkeypatch.setattr(db, "advisory_lock", _fake)


def test_http_rank_skips_when_lock_is_held(monkeypatch):
    import rns_llm

    ranked = []
    monkeypatch.setattr(rns_llm, "_rank_pending", lambda *a, **k: ranked.append(a))

    seen = []
    _patch_lock(monkeypatch, False, seen)
    result = rns_llm._rank_pending_locked(limit=5, hours=12)

    assert ranked == [], "manual rank ran while a cron pipeline held the lock"
    assert result["ranked"] == 0
    assert result["skipped"] == "locked"


def test_http_rank_runs_when_lock_is_free(monkeypatch):
    import rns_llm

    calls = []
    monkeypatch.setattr(
        rns_llm, "_rank_pending",
        lambda limit, tiers, hours: calls.append((limit, tiers, hours)) or {"ranked": 1},
    )

    seen = []
    _patch_lock(monkeypatch, True, seen)
    result = rns_llm._rank_pending_locked(limit=7, hours=12)

    assert calls == [(7, ("A", "B"), 12)], "args must reach _rank_pending unchanged"
    assert result == {"ranked": 1}


def test_http_rank_shares_the_cron_lock_key(monkeypatch):
    """Same drift hazard as test_uses_the_shared_lock_key: a separate key here
    would mean the route and the crons lock against nothing."""
    import rns_llm

    monkeypatch.setattr(rns_llm, "_rank_pending", lambda *a, **k: {})
    seen = []
    _patch_lock(monkeypatch, True, seen)
    rns_llm._rank_pending_locked()

    assert seen == [RNS_PIPELINE_LOCK_KEY]


def test_http_rank_route_is_wired_to_the_locked_wrapper(monkeypatch):
    """The bug was a one-word call-site difference, so pin the call site: the
    background task must be the locked wrapper, not _rank_pending itself."""
    import rns_llm

    class _BG:
        def __init__(self): self.tasks = []
        def add_task(self, fn, *args): self.tasks.append((fn, args))

    bg = _BG()
    rns_llm.rank(background_tasks=bg, limit=50, hours=72)

    assert [fn for fn, _ in bg.tasks] == [rns_llm._rank_pending_locked]
