"""Concurrent ranking in _rank_pending.

The point of the pool is wall-clock: ranking is I/O-bound, and serialising it
pushed the morning batch up against the digest send. These tests pin the
behaviour that must survive the change — accurate counts, per-row error
isolation, every row attempted exactly once — plus the concurrency itself.
"""
import sys, os, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rns_llm


def _rows(n):
    return [{"id": i} for i in range(1, n + 1)]


def _patch(monkeypatch, rows, rank_one, workers=5):
    monkeypatch.setattr(rns_llm, "_query", lambda *a, **k: rows)
    monkeypatch.setattr(rns_llm, "_rank_one", rank_one)
    monkeypatch.setattr(rns_llm, "_get_client", lambda: object())
    monkeypatch.setattr(rns_llm, "_RANK_WORKERS", workers)


def test_ranks_every_row_exactly_once(monkeypatch):
    seen = []
    lock = threading.Lock()

    def _rank(row_id):
        with lock:
            seen.append(row_id)

    _patch(monkeypatch, _rows(12), _rank)
    out = rns_llm._rank_pending()

    assert out == {"candidates": 12, "ranked": 12, "errors": 0}
    assert sorted(seen) == list(range(1, 13)), "each row must be ranked once"


def test_one_failure_does_not_sink_the_batch(monkeypatch):
    def _rank(row_id):
        if row_id == 4:
            raise RuntimeError("deepseek said no")

    _patch(monkeypatch, _rows(10), _rank)
    out = rns_llm._rank_pending()

    assert out == {"candidates": 10, "ranked": 9, "errors": 1}


def test_counts_are_accurate_under_concurrent_failures(monkeypatch):
    """Counters are mutated from the main thread by design — if that ever moves
    into the workers, this catches the lost updates."""
    def _rank(row_id):
        if row_id % 3 == 0:
            raise RuntimeError("boom")

    _patch(monkeypatch, _rows(30), _rank)
    out = rns_llm._rank_pending()

    assert out["candidates"] == 30
    assert out["ranked"] + out["errors"] == 30
    assert out["errors"] == 10


def test_calls_actually_overlap(monkeypatch):
    """The whole point: a slow row must not block the next one."""
    peak = 0
    live = 0
    lock = threading.Lock()

    def _rank(row_id):
        nonlocal peak, live
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1

    _patch(monkeypatch, _rows(10), _rank, workers=5)
    rns_llm._rank_pending()

    assert peak > 1, "ranking ran serially — the pool is not doing anything"
    assert peak <= 5, f"exceeded the worker cap: {peak}"


def test_workers_capped_at_row_count(monkeypatch):
    """Two rows must not spin up five threads."""
    names = set()
    lock = threading.Lock()

    def _rank(row_id):
        time.sleep(0.02)
        with lock:
            names.add(threading.current_thread().name)

    _patch(monkeypatch, _rows(2), _rank, workers=5)
    rns_llm._rank_pending()

    assert len(names) <= 2


def test_serial_mode_still_works(monkeypatch):
    """RNS_RANK_WORKERS=1 is the escape hatch if DeepSeek ever rate-limits."""
    order = []

    def _rank(row_id):
        order.append(row_id)

    _patch(monkeypatch, _rows(5), _rank, workers=1)
    out = rns_llm._rank_pending()

    assert out == {"candidates": 5, "ranked": 5, "errors": 0}
    assert order == [1, 2, 3, 4, 5], "serial mode must preserve row order"


def test_empty_batch_is_a_no_op(monkeypatch):
    def _rank(row_id):
        raise AssertionError("should not be called")

    _patch(monkeypatch, [], _rank)
    assert rns_llm._rank_pending() == {"candidates": 0, "ranked": 0, "errors": 0}
