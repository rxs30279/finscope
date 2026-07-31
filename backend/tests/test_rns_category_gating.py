"""Category-gated reasoning in the ranker (rns_llm._use_thinking).

Thinking mode took ranking calls from ~6.5s to 85-172s and made reasoning ~90%
of output tokens, all of it inside the 07:01 -> 07:30 digest window. Categories
whose score is decided by the fact itself rather than by reconciling reported
figures — board changes, drill results, product launches, update statements —
rank without it, on a budget sized for the answer alone.

These tests pin the parts that fail silently if they regress: the opt-out is a
list (so an unrecognised category still reasons), the fast path really does send
thinking disabled rather than just a smaller budget, and a fast row counts as
ranked. That last one matters because fast rows report False, so any truthiness
test in the accounting would book every one of them as a failure — and a row
booked as failed is indistinguishable in the DB from one never attempted.
"""

import sys, os, json
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rns_llm


def _resp(finish_reason: str, content: str, completion_tokens: int = 100):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content),
        )],
        usage=SimpleNamespace(
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=0,
            completion_tokens=completion_tokens,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=completion_tokens),
        ),
    )


class _FakeClient:
    """Records the budget AND the thinking flag of every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append((kwargs["max_tokens"], kwargs["extra_body"]))
        return self._responses.pop(0)


@pytest.fixture
def fake_client(monkeypatch):
    def _install(responses):
        client = _FakeClient(responses)
        monkeypatch.setattr(rns_llm, "_get_client", lambda: client)
        return client
    return _install


# ── Which rows reason ─────────────────────────────────────────────────────────


def test_fast_categories_skip_reasoning():
    assert rns_llm._use_thinking("board_change") is False


def test_results_categories_still_reason():
    """The expensive categories are deliberately NOT gated — whether reasoning
    earns its keep on results is an open question for a thinking on/off A/B,
    and this list must not pre-empt it."""
    for cat in ("interim_results", "final_results", "trading_update", "delisting"):
        assert rns_llm._use_thinking(cat) is True


def test_near_bar_categories_still_reason():
    """A 30-day window made these look inert (0 rows over the 76 bar) and they
    were briefly gated. The 90-day view shows they cluster at 65-75 just under
    it — drill_results alone was 16 of 20 rows marked watch/research. At ~20
    rows per 90 days, gating them saves nothing measurable and risks exactly the
    tradeable row this feed exists to catch."""
    for cat in ("drill_results", "product_launch", "update_statement"):
        assert rns_llm._use_thinking(cat) is True


def test_unknown_and_null_categories_reason():
    """The gate is an opt-out list, so a category added to rns._CATEGORIES later
    keeps the safe default until someone measures it."""
    assert rns_llm._use_thinking("category_invented_next_quarter") is True
    assert rns_llm._use_thinking(None) is True
    assert rns_llm._use_thinking("") is True


# ── What the fast path actually sends ─────────────────────────────────────────


def test_fast_path_disables_thinking_and_uses_small_budget(fake_client):
    client = fake_client([_resp("stop", json.dumps({"score": 10}))])
    assert rns_llm._call_deepseek([], thinking=False) == {"score": 10}
    assert client.calls == [(rns_llm._FAST_MAX_COMPLETION_TOKENS, rns_llm._THINKING_OFF)]


def test_thinking_is_the_default(fake_client):
    """A caller that hasn't considered the mode must get the thorough one."""
    client = fake_client([_resp("stop", json.dumps({"score": 90}))])
    rns_llm._call_deepseek([])
    assert client.calls == [(rns_llm._MAX_COMPLETION_TOKENS, rns_llm._THINKING_ON)]


def test_fast_path_retry_doubles_the_fast_budget(fake_client):
    """The retry must scale off the budget actually in use — retrying a fast row
    at 2x the *thinking* budget would hand back the cost the gate just saved."""
    client = fake_client([
        _resp("length", ""),
        _resp("stop", json.dumps({"score": 20})),
    ])
    assert rns_llm._call_deepseek([], thinking=False) == {"score": 20}
    assert [b for b, _ in client.calls] == [
        rns_llm._FAST_MAX_COMPLETION_TOKENS,
        rns_llm._FAST_MAX_COMPLETION_TOKENS * 2,
    ]
    assert [e for _, e in client.calls] == [rns_llm._THINKING_OFF] * 2


def test_fast_budget_is_well_under_the_thinking_budget():
    """Sizing guard: the fast path exists to cap what a no-reasoning row can
    cost. If someone raises it to thinking scale the gate stops paying."""
    assert rns_llm._FAST_MAX_COMPLETION_TOKENS * 2 < rns_llm._MAX_COMPLETION_TOKENS


# ── Row-level wiring ──────────────────────────────────────────────────────────


@pytest.fixture
def rank_one_harness(monkeypatch):
    """Drives _rank_one with everything below the DeepSeek call stubbed out.
    Returns the recorder so tests can assert on the mode and the stored label."""
    saved = {}

    def _install(category: str, score: int = 10):
        monkeypatch.setattr(rns_llm, "_load_candidate",
                            lambda i: {"id": i, "symbol": "TEST.L", "category": category})
        monkeypatch.setattr(rns_llm, "_load_history", lambda s: [])
        monkeypatch.setattr(rns_llm, "_load_price_change", lambda s: None)
        monkeypatch.setattr(rns_llm, "_load_prior_guidance", lambda s, exclude_id=None: [])
        monkeypatch.setattr(rns_llm, "_build_messages", lambda *a, **k: [])
        monkeypatch.setattr(rns_llm, "_call_deepseek",
                            lambda msgs, thinking=True: saved.update(thinking=thinking)
                            or {"score": score})
        monkeypatch.setattr(rns_llm, "_save_ranking",
                            lambda i, r, model: saved.update(model=model))
        return saved
    return _install


def test_gated_category_ranks_fast_and_is_labelled(rank_one_harness):
    saved = rank_one_harness("board_change")
    out = rns_llm._rank_one(1)
    assert saved["thinking"] is False
    assert out["thinking"] is False
    # The label is what lets a later analysis separate the two populations.
    assert saved["model"].endswith(":fast")


def test_ungated_category_still_reasons(rank_one_harness):
    saved = rank_one_harness("interim_results")
    rns_llm._rank_one(1)
    assert saved["thinking"] is True
    assert saved["model"].endswith(":thinking")


def test_high_scoring_fast_row_warns(rank_one_harness, capsys):
    """The gate assumes these categories never approach the digest bar. If one
    does, the log has to say so — the alternative is discovering it through a
    story the feed under-scored."""
    rank_one_harness("board_change", score=rns_llm._FAST_REVIEW_SCORE)
    rns_llm._rank_one(77)
    out = capsys.readouterr().out
    assert "fast-path row scored" in out and "board_change" in out


def test_ordinary_fast_row_is_quiet(rank_one_harness, capsys):
    rank_one_harness("board_change", score=10)
    rns_llm._rank_one(1)
    assert "fast-path row scored" not in capsys.readouterr().out


def test_review_threshold_leaves_warning_room(rank_one_harness):
    """A threshold at or above 76 would only ever fire once the row had already
    been mis-served to the digest."""
    assert rns_llm._FAST_REVIEW_SCORE < 76


# ── Batch accounting ──────────────────────────────────────────────────────────


def test_fast_rows_count_as_ranked_not_errors(monkeypatch):
    ranked_ids = []

    def _fake_rank_one(row_id: int) -> dict:
        if row_id == 3:
            raise RuntimeError("boom")
        ranked_ids.append(row_id)
        # row 1 reasons, row 2 takes the fast path
        return {"id": row_id, "thinking": row_id == 1}

    monkeypatch.setattr(rns_llm, "_query", lambda *a, **k: [{"id": 1}, {"id": 2}, {"id": 3}])
    monkeypatch.setattr(rns_llm, "_rank_one", _fake_rank_one)
    monkeypatch.setattr(rns_llm, "_RANK_WORKERS", 1)

    result = rns_llm._rank_pending()
    assert result == {"candidates": 3, "ranked": 2, "fast": 1, "errors": 1}
    assert ranked_ids == [1, 2]


def test_accounting_matches_under_concurrency(monkeypatch):
    """Same accounting through the thread pool, which is the path the cron takes."""
    monkeypatch.setattr(rns_llm, "_query", lambda *a, **k: [{"id": i} for i in range(10)])
    monkeypatch.setattr(rns_llm, "_rank_one", lambda i: {"id": i, "thinking": i % 2 == 0})
    monkeypatch.setattr(rns_llm, "_RANK_WORKERS", 4)
    monkeypatch.setattr(rns_llm, "_get_client", lambda: None)

    assert rns_llm._rank_pending() == {
        "candidates": 10, "ranked": 10, "fast": 5, "errors": 0,
    }
