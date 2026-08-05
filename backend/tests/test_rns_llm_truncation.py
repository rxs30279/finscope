"""Completion-budget exhaustion in the ranker call (rns_llm._call_deepseek).

In thinking mode the reasoning chain shares max_tokens with the JSON answer, so
a complex announcement can burn the whole budget and emit zero answer tokens.
That used to surface as a JSONDecodeError on an empty string, which _rank_pending
swallowed per-row — leaving llm_processed_at NULL and making a *failed* row look
identical to one that was never attempted. On 2026-07-31 that silently dropped 21
of 48 rows, every one a large-cap interim, out of the morning digest.

These tests pin the two behaviours that fix relies on: a truncated response is
retried at double the budget rather than parsed, and a response that truncates
twice raises TruncatedResponse (not JSONDecodeError) so the log names the cause.
"""

import sys, os, json
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rns_llm


def _resp(finish_reason: str, content: str, completion_tokens: int = 100):
    """Minimal stand-in for the OpenAI response shape _call_deepseek reads."""
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
    """Replays a scripted list of responses, recording the max_tokens asked for."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.budgets = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.budgets.append(kwargs["max_tokens"])
        return self._responses.pop(0)


@pytest.fixture
def fake_client(monkeypatch):
    def _install(responses):
        client = _FakeClient(responses)
        monkeypatch.setattr(rns_llm, "_get_client", lambda: client)
        return client
    return _install


def test_clean_response_parses_without_retry(fake_client):
    client = fake_client([_resp("stop", json.dumps({"score": 80}))])
    assert rns_llm._call_deepseek([]) == {"score": 80}
    # One call only: a finishing response must never pay for a second.
    assert client.budgets == [rns_llm._MAX_COMPLETION_TOKENS]


def test_truncated_response_retries_at_double_budget(fake_client):
    """The NWG/IAG/ITV case: first attempt exhausts the budget mid-reasoning,
    the retry finishes. Reasoning length is nondeterministic, so this is the
    common recovery path."""
    client = fake_client([
        _resp("length", "", completion_tokens=rns_llm._MAX_COMPLETION_TOKENS),
        _resp("stop", json.dumps({"score": 45})),
    ])
    assert rns_llm._call_deepseek([]) == {"score": 45}
    assert client.budgets == [
        rns_llm._MAX_COMPLETION_TOKENS,
        rns_llm._MAX_COMPLETION_TOKENS * 2,
    ]


def test_truncated_twice_raises_named_error(fake_client):
    """Must not surface as JSONDecodeError — that diagnosis sends the next
    investigation after bad model output instead of after the token budget."""
    client = fake_client([
        _resp("length", "", completion_tokens=rns_llm._MAX_COMPLETION_TOKENS),
        _resp("length", "", completion_tokens=rns_llm._MAX_COMPLETION_TOKENS * 2),
    ])
    with pytest.raises(rns_llm.TruncatedResponse):
        rns_llm._call_deepseek([])
    assert len(client.budgets) == 2


def test_truncation_never_parses_partial_json(fake_client):
    """A cut-off response can still be syntactically valid JSON with fields
    missing. Parsing it would store a half-scored row that looks legitimate,
    which is worse than failing — the sweep would never revisit it."""
    client = fake_client([
        _resp("length", '{"score": 80}'),
        _resp("stop", json.dumps({"score": 80, "thesis": "complete"})),
    ])
    assert rns_llm._call_deepseek([]) == {"score": 80, "thesis": "complete"}


# ── sampling temperature ──────────────────────────────────────────────────────
# Pinned because the failure is invisible: nothing errors if the ranker starts
# sampling at a different temperature, its scores just quietly stop being
# comparable to every llm_score already stored and to the digest's calibrated
# 76 bar. Note this only binds the fast path — deepseek-v4-flash ignores
# temperature in thinking mode, so the vet's score spread is not reachable from
# here (see the note above showcase._vet_candidate).
def test_ranker_keeps_its_calibrated_temperature(fake_client):
    client = fake_client([_resp("stop", json.dumps({"score": 80}))])
    captured = {}
    client._create = lambda **kw: (captured.update(kw), client._responses.pop(0))[1]
    client.chat.completions.create = client._create
    rns_llm._call_deepseek([])
    assert captured["temperature"] == 0.2
    assert rns_llm._DEFAULT_TEMPERATURE == 0.2
