"""The gate registry (backend/gates.py). Pure — no DB, no network — since every
gate reads fields already present on the candidate dict.

Sentiment never returns n/a (showcase._sentiment always resolves to
positive/negative/neutral), so its coverage below is pass/block only; guidance
and earnings_quality each exercise all three states, and test_gate_error_*
covers the fail-open path shared by every gate via Gate.evaluate's try/except.
"""
from unittest.mock import patch

import gates
from gates import GATES, Gate, GateResult, blocking_reason, evaluate_all


def _gate(name):
    return next(g for g in GATES if g.name == name)


# ── sentiment ──────────────────────────────────────────────────────────────────
def test_sentiment_gate_pass_on_positive():
    r = _gate("sentiment").evaluate({"keyword_hits": ["pos:2"]})
    assert r.state == "pass"


def test_sentiment_gate_blocks_on_negative_with_reason():
    r = _gate("sentiment").evaluate({"category": "profit_warning"})
    assert r.state == "block"
    assert r.reason == "negative"


# ── guidance ───────────────────────────────────────────────────────────────────
_LUCE_CHECK = {
    "metric": "Adjusted Operating Profit", "period": "FY2026",
    "guided_value": "> £40m", "consensus_value": "£40.7m",
    "vs_prior": "reiterated", "vs_consensus": "below",
}


def test_guidance_gate_na_when_field_absent():
    for cand in ({}, {"guidance_checks": None}, {"guidance_checks": []},
                 {"guidance_checks": "not a list"}):
        r = _gate("guidance").evaluate(cand)
        assert r.state == "n/a"
        assert r.reason == "field_absent"


def test_guidance_gate_na_when_no_consensus_stated():
    # The common case — measured ~91% of guidance_checks entries on 2026-07-29.
    r = _gate("guidance").evaluate({"guidance_checks": [
        {"vs_prior": "raised", "vs_consensus": "no_consensus_stated"},
    ]})
    assert r.state == "n/a"
    assert r.reason == "no_consensus_stated"


def test_guidance_gate_pass_when_adjudicable_and_clean():
    r = _gate("guidance").evaluate({"guidance_checks": [
        {"vs_prior": "raised", "vs_consensus": "above"},
    ]})
    assert r.state == "pass"


def test_guidance_gate_blocks_the_luce_case():
    r = _gate("guidance").evaluate({"guidance_checks": [_LUCE_CHECK]})
    assert r.state == "block"
    assert r.reason == "reiterated_vs_consensus_below"
    assert r.evidence == _LUCE_CHECK


# ── earnings_quality (bank loan-loss rate) ──────────────────────────────────────
_BANK = {"sector": "Financial Services", "industry": "Banks - Diversified"}
_BARC_LLR = {
    "item": "Loan loss rate", "period": "H1 2026", "value": "62bps",
    "prior_value": "52bps", "kind": "cost_or_charge", "one_off_named": None,
}


def test_earnings_quality_gate_na_when_not_a_bank():
    r = _gate("earnings_quality").evaluate(
        {"sector": "Industrials", "industry": "x", "earnings_quality": [_BARC_LLR]}
    )
    assert r.state == "n/a"
    assert r.reason == "not_a_bank"


def test_earnings_quality_gate_na_when_field_absent():
    for entries in (None, [], "not a list"):
        r = _gate("earnings_quality").evaluate({**_BANK, "earnings_quality": entries})
        assert r.state == "n/a"
        assert r.reason == "field_absent"


def test_earnings_quality_gate_na_when_period_missing():
    r = _gate("earnings_quality").evaluate(
        {**_BANK, "earnings_quality": [{**_BARC_LLR, "period": None}]}
    )
    assert r.state == "n/a"
    assert r.reason == "missing_period"


def test_earnings_quality_gate_na_when_unparseable():
    r = _gate("earnings_quality").evaluate(
        {**_BANK, "earnings_quality": [{**_BARC_LLR, "value": "materially higher"}]}
    )
    assert r.state == "n/a"
    assert r.reason == "unparseable_value"


def test_earnings_quality_gate_pass_on_a_clean_rate():
    r = _gate("earnings_quality").evaluate(
        {**_BANK, "earnings_quality": [{**_BARC_LLR, "prior_value": "62bps"}]}
    )
    assert r.state == "pass"


def test_earnings_quality_gate_blocks_the_barc_case():
    r = _gate("earnings_quality").evaluate({**_BANK, "earnings_quality": [_BARC_LLR]})
    assert r.state == "block"
    assert r.reason == "loan_loss_rate_rise"
    assert r.evidence == _BARC_LLR


# ── fail-open on a raising gate ─────────────────────────────────────────────────
def test_gate_error_fails_open_rather_than_propagating():
    def _boom(cand):
        raise RuntimeError("boom")

    broken = Gate("broken", "always raises", "armed", _boom)
    r = broken.evaluate({})
    assert r.state == "n/a"
    assert r.reason == "gate_error"
    assert "boom" in r.evidence["error"]


# ── evaluate_all / blocking_reason ──────────────────────────────────────────────
def test_evaluate_all_runs_every_gate_regardless_of_outcome():
    # A row that blocks on sentiment must still show guidance/earnings_quality
    # verdicts — the page needs the full row, not just the first failure.
    cand = {"category": "profit_warning", **_BANK, "earnings_quality": [_BARC_LLR]}
    results = evaluate_all(cand)
    names = [g.name for g, _ in results]
    assert names == ["sentiment", "guidance", "earnings_quality"]
    states = {g.name: r.state for g, r in results}
    assert states["sentiment"] == "block"
    assert states["earnings_quality"] == "block"


def test_blocking_reason_stops_at_first_armed_block():
    cand = {"category": "profit_warning", **_BANK, "earnings_quality": [_BARC_LLR]}
    gate, result = blocking_reason(cand)
    assert gate.name == "sentiment"  # first in registry order, not earnings_quality


def test_blocking_reason_none_when_nothing_blocks():
    assert blocking_reason({"keyword_hits": ["pos:1"]}) is None


def test_blocking_reason_skips_shadow_gates():
    shadow_blocks = Gate(
        "shadow_test", "always blocks, shadow", "shadow",
        lambda c: GateResult(state="block", reason="test"),
    )
    with patch.object(gates, "GATES", (shadow_blocks,)):
        assert blocking_reason({}) is None


def test_blocking_reason_reproduces_luce_case():
    # LUCE 9689898 — the case the whole plan started from.
    cand = {"keyword_hits": ["pos:1"], "guidance_checks": [_LUCE_CHECK]}
    gate, result = blocking_reason(cand)
    assert gate.name == "guidance"
    assert result.evidence == _LUCE_CHECK


def test_blocking_reason_reproduces_barc_case():
    # BARC 9689888 — guidance genuinely raised, so only the bank gate can catch it.
    cand = {"keyword_hits": ["pos:1"], **_BANK, "earnings_quality": [_BARC_LLR]}
    gate, result = blocking_reason(cand)
    assert gate.name == "earnings_quality"
    assert result.evidence == _BARC_LLR


# ── record_gate_evaluations ──────────────────────────────────────────────────────
def test_record_gate_evaluations_writes_one_row_per_gate_per_candidate():
    rows = [
        {"id": 1, "symbol": "ABC.L", "category": "final_results",
         "llm_score": 60, "llm_sentiment": "positive", "llm_thesis": None,
         "keyword_hits": [], "guidance_checks": None, "earnings_quality": None,
         "sector": "Industrials", "industry": "x"},
    ]
    with patch.object(gates, "_q", return_value=rows), \
         patch.object(gates, "_exec", return_value=1) as ex:
        res = gates.record_gate_evaluations(hours=48)
    assert res == {"candidates": 1, "gate_rows_written": 3}  # one write per gate
    written_gates = [call.args[1][1] for call in ex.call_args_list]
    assert written_gates == ["sentiment", "guidance", "earnings_quality"]
    # sentiment passed (llm_sentiment positive) -> state 'pass' in the params
    assert ex.call_args_list[0].args[1][2] == "pass"


def test_record_gate_evaluations_no_candidates_writes_nothing():
    with patch.object(gates, "_q", return_value=[]), \
         patch.object(gates, "_exec") as ex:
        res = gates.record_gate_evaluations(hours=48)
    assert res == {"candidates": 0, "gate_rows_written": 0}
    ex.assert_not_called()
