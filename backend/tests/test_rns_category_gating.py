"""Ranker reasoning mode (rns_llm._use_thinking) — the blanket switch and the
category gate underneath it.

Since 2026-07-31 the ranker runs with reasoning OFF for every row and the budget
moved to the showcase vet, which has a documented arithmetic failure to fix.
_THINKING_DEFAULT carries that; _FAST_CATEGORIES is the finer gate it sits on
top of, dormant but intact so RNS_THINKING=on restores the old shape exactly.

These tests pin the parts that fail silently if they regress: the blanket switch
really does reach NULL- and unknown-category rows (the env route it replaced
could not), the gate still works underneath it, the fast path sends thinking
disabled rather than just a smaller budget, and a fast row counts as ranked.
That last one matters because fast rows report False, so any truthiness test in
the accounting would book every one of them as a failure — and a row booked as
failed is indistinguishable in the DB from one never attempted.
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


@pytest.fixture
def thinking_on(monkeypatch):
    """Restore the pre-2026-07-31 shape (RNS_THINKING=on) so the category gate
    underneath the blanket switch stays under test while it is dormant."""
    monkeypatch.setattr(rns_llm, "_THINKING_DEFAULT", True)


# ── The blanket switch ────────────────────────────────────────────────────────


def test_no_row_reasons_by_default():
    """The shipped default. Includes the categories the gate deliberately left
    reasoning — the switch is above the gate, not another entry in it."""
    for cat in ("interim_results", "final_results", "trading_update",
                "drill_results", "board_change"):
        assert rns_llm._use_thinking(cat) is False


def test_blanket_switch_reaches_null_and_unknown_categories():
    """The reason this is a module flag and not RNS_FAST_CATEGORIES="a,b,c,...".
    That env parse strips empty entries, so no list value can express "NULL
    category too" — those rows would have gone on reasoning at full budget while
    the log said the ranker was fast."""
    assert rns_llm._use_thinking(None) is False
    assert rns_llm._use_thinking("") is False
    assert rns_llm._use_thinking("category_invented_next_quarter") is False


# ── Which rows reason with RNS_THINKING=on ────────────────────────────────────


def test_fast_categories_skip_reasoning(thinking_on):
    assert rns_llm._use_thinking("board_change") is False


def test_results_categories_still_reason(thinking_on):
    """The expensive categories were deliberately NOT gated, so that turning
    reasoning back on restores it where it was argued to be worth paying for."""
    for cat in ("interim_results", "final_results", "trading_update", "delisting"):
        assert rns_llm._use_thinking(cat) is True


def test_near_bar_categories_still_reason(thinking_on):
    """A 30-day window made these look inert (0 rows over the 76 bar) and they
    were briefly gated. The 90-day view shows they cluster at 65-75 just under
    it — drill_results alone was 16 of 20 rows marked watch/research. At ~20
    rows per 90 days, gating them saves nothing measurable and risks exactly the
    tradeable row this feed exists to catch."""
    for cat in ("drill_results", "product_launch", "update_statement"):
        assert rns_llm._use_thinking(cat) is True


def test_unknown_and_null_categories_reason(thinking_on):
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


# ── Reuse by callers outside the ranker (the showcase vet) ────────────────────


def test_explicit_budget_overrides_both_defaults(fake_client):
    client = fake_client([_resp("stop", json.dumps({"verdict": "include"}))])
    assert rns_llm._call_deepseek([], thinking=True, budget=8000) == {"verdict": "include"}
    assert client.calls == [(8000, rns_llm._THINKING_ON)]


def test_explicit_budget_still_retries_at_double(fake_client):
    """The whole reason a second call site shares this function: an overrun that
    is not retried lands as a NULL verdict indistinguishable from an outage."""
    client = fake_client([
        _resp("length", ""),
        _resp("stop", json.dumps({"verdict": "caution"})),
    ])
    assert rns_llm._call_deepseek([], budget=8000) == {"verdict": "caution"}
    assert [b for b, _ in client.calls] == [8000, 16000]


def test_exhausted_budget_raises_rather_than_returning_empty(fake_client):
    fake_client([_resp("length", ""), _resp("length", "")])
    with pytest.raises(rns_llm.TruncatedResponse):
        rns_llm._call_deepseek([], budget=8000)


def test_tag_labels_the_log_line(fake_client, capsys):
    """Without this the vet's truncations would be logged as [rns_llm], sending
    the next investigation to the wrong call site."""
    fake_client([_resp("length", ""), _resp("stop", json.dumps({}))])
    rns_llm._call_deepseek([], budget=8000, tag="showcase_vet")
    assert "[showcase_vet] !! response hit max_tokens at 8000" in capsys.readouterr().out


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


def test_results_row_is_labelled_fast_under_the_blanket_switch(rank_one_harness):
    """The label has to follow the mode actually used, not the category. It is
    the only record of which side of 2026-07-31 a row was scored on, and so the
    only way the switch itself can be read as an A/B in rns_score_perf.py."""
    saved = rank_one_harness("interim_results")
    assert rns_llm._rank_one(1)["thinking"] is False
    assert saved["model"].endswith(":fast")


def test_ungated_category_still_reasons(rank_one_harness, thinking_on):
    saved = rank_one_harness("interim_results")
    rns_llm._rank_one(1)
    assert saved["thinking"] is True
    assert saved["model"].endswith(":thinking")


def test_high_scoring_fast_row_warns(rank_one_harness, thinking_on, capsys):
    """The gate assumes these categories never approach the digest bar. If one
    does, the log has to say so — the alternative is discovering it through a
    story the feed under-scored."""
    rank_one_harness("board_change", score=rns_llm._FAST_REVIEW_SCORE)
    rns_llm._rank_one(77)
    out = capsys.readouterr().out
    assert "fast-path row scored" in out and "board_change" in out


def test_ordinary_fast_row_is_quiet(rank_one_harness, thinking_on, capsys):
    rank_one_harness("board_change", score=10)
    rns_llm._rank_one(1)
    assert "fast-path row scored" not in capsys.readouterr().out


def test_tripwire_silent_under_the_blanket_switch(rank_one_harness, capsys):
    """With every row fast, a high-scoring fast row is the expected case, not a
    surprise. Left unconditional this fires on every digest row — the one loud
    line that means something becomes several a morning that nobody reads."""
    rank_one_harness("interim_results", score=90)
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
