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
    assert names == ["sentiment", "guidance", "earnings_quality", "low_base"]
    states = {g.name: r.state for g, r in results}
    assert states["sentiment"] == "block"
    assert states["earnings_quality"] == "block"
    assert states["low_base"] == "n/a"  # no low_base key on this cand -> not_vetted


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
    assert res == {"candidates": 1, "gate_rows_written": 4}  # one write per gate
    written_gates = [call.args[1][1] for call in ex.call_args_list]
    assert written_gates == ["sentiment", "guidance", "earnings_quality", "low_base"]
    # sentiment passed (llm_sentiment positive) -> state 'pass' in the params
    assert ex.call_args_list[0].args[1][2] == "pass"


def test_record_gate_evaluations_no_candidates_writes_nothing():
    with patch.object(gates, "_q", return_value=[]), \
         patch.object(gates, "_exec") as ex:
        res = gates.record_gate_evaluations(hours=48)
    assert res == {"candidates": 0, "gate_rows_written": 0}
    ex.assert_not_called()


# ── low_base (Phase 4, shadow) ───────────────────────────────────────────────
# See docs/rns-gate-block-plan.md §1/Phase 4. Route 1 (printed_preceding_period)
# is the CAPD.L fix: the announcement itself prints the immediately preceding
# same-length period, so no FY derivation or divisor choice is needed. Route 2
# (derived_from_fy_total) is the SRT/STAN/JNEO shape: FY total (we own it, from
# annual_financials) minus the prior-YEAR same half (the model copies it) gives
# the immediately preceding half, valid only for halves.
def test_low_base_gate_na_when_not_vetted():
    r = _gate("low_base").evaluate({})
    assert r.state == "n/a"
    assert r.reason == "not_vetted"


def test_low_base_gate_na_when_period_missing_or_unrecognised():
    for period in (None, "", "FY2026", "H3"):
        r = _gate("low_base").evaluate({"low_base": {"period": period}})
        assert r.state == "n/a"
        assert r.reason == "missing_period"


def test_low_base_gate_na_when_current_value_unparseable():
    r = _gate("low_base").evaluate(
        {"low_base": {"period": "H1", "current_value": "significantly higher"}}
    )
    assert r.state == "n/a"
    assert r.reason == "unparseable_value"


def test_low_base_gate_route1_pass_on_the_capd_shape():
    # CAPD.L 9671246 negative control — Q1'26 $101.7m -> Q2'26 $117.3m is
    # printed directly, +15.3% sequentially. The original vet instead divided
    # FY2025 by 2 and called it a "quarterly run-rate"; this route never does.
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$117.3m", "preceding_period_value": "$101.7m",
    }})
    assert r.state == "pass"
    assert r.evidence["basis"] == "printed_preceding_period"
    assert r.evidence["delta_pct"] > 0


def test_low_base_gate_route1_blocks_a_genuine_sequential_decline():
    # A sequential decline alone is no longer enough — it has to survive the
    # seasonality check, which here it does: $90m is also below the $95m the
    # same quarter made two years ago, so the level genuinely has not held.
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$90m", "preceding_period_value": "$101.7m",
        "prior_year_2_value": "$95m",
    }})
    assert r.state == "block"
    assert r.reason == "below_same_period_two_years_ago"
    assert r.evidence["two_year_lfl_pct"] < 0


def test_low_base_gate_na_when_sequential_shortfall_cannot_be_seasonally_adjudicated():
    # STEP 1, the stop-loss. Without the two-year comparator a negative
    # sequential step is ambiguous between deceleration and seasonality, and
    # over-blocking is the high-severity error — so it fails OPEN.
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$90m", "preceding_period_value": "$101.7m",
    }})
    assert r.state == "n/a"
    assert r.reason == "seasonality_unadjudicable"
    # The sequential figures are still recorded, so /gates shows why it abstained.
    assert r.evidence["delta_pct"] < 0


def test_low_base_gate_na_quarter_unsupported_with_no_printed_preceding_figure():
    # Deriving a quarter from an FY total needs the other three quarters,
    # which quarterly_financials cannot supply for ~95% of the universe — a
    # quarter with nothing printed directly must never fall back to a
    # divide-by-4 guess.
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$117.3m",
        "prior_year_value": "$80m",  # present, but irrelevant for a quarter
    }})
    assert r.state == "n/a"
    assert r.reason == "quarter_unsupported"


def test_low_base_gate_na_no_period_split_on_the_srt_shape():
    # SRT.L 9682985 negative control — the announcement publishes no half-year
    # split at all. Acceptance criterion 8 (the plan) requires specifically
    # no_period_split here, not merely "not blocked".
    r = _gate("low_base").evaluate({"low_base": {
        "period": "H1", "current_value": "£10m",
    }})
    assert r.state == "n/a"
    assert r.reason == "no_period_split"


def test_low_base_gate_na_metric_unmapped():
    r = _gate("low_base").evaluate({"low_base": {
        "period": "H1", "current_value": "£10m", "prior_year_value": "£8m",
        "metric": "adjusted_ebitda",  # not one of the three annual_financials lines
    }})
    assert r.state == "n/a"
    assert r.reason == "metric_unmapped"


def test_low_base_gate_na_no_annual_history():
    with patch("showcase._annual_history", return_value=[]):
        r = _gate("low_base").evaluate({"low_base": {
            "period": "H1", "current_value": "£10m", "prior_year_value": "£8m",
            "metric": "revenue",
        }})
    assert r.state == "n/a"
    assert r.reason == "no_annual_history"


def test_low_base_gate_route2_pass_on_the_stan_shape():
    # STAN.L 9692325 negative control — real H2'25 is $9.65bn (FY'25 $20.55bn
    # minus H1'25 $10.91bn), so H1'26's $11.6bn is +20.3%, not "flat" as the
    # vet's prose wrongly claimed.
    with patch("showcase._annual_history", return_value=[{"operating_income": 20.55e9}]):
        r = _gate("low_base").evaluate({"low_base": {
            "period": "H1", "metric": "operating_income",
            "current_value": "$11.6bn", "prior_year_value": "$10.91bn",
        }})
    assert r.state == "pass"
    assert r.evidence["basis"] == "derived_from_fy_total"
    assert 19 < r.evidence["delta_pct"] < 21


def test_low_base_gate_route2_pass_on_the_jneo_shape():
    # JNEO.L 9689848 negative control — derived H2'25 = FY £60.5m minus H1'25
    # £30.0m = £30.5m; H1'26's £37.6m is +23.3% above it, not "below" as the
    # vet's prose wrongly claimed (the real reported figure was +23.2%).
    with patch("showcase._annual_history", return_value=[{"revenue": 60.5e6}]):
        r = _gate("low_base").evaluate({"low_base": {
            "period": "H1", "metric": "revenue",
            "current_value": "£37.6m", "prior_year_value": "£30.0m",
        }})
    assert r.state == "pass"
    assert abs(r.evidence["preceding_value"] - 30.5e6) < 1
    assert 22 < r.evidence["delta_pct"] < 24


def test_low_base_gate_route2_uses_growth_pct_when_prior_value_absent():
    with patch("showcase._annual_history", return_value=[{"revenue": 150.0}]):
        r = _gate("low_base").evaluate({"low_base": {
            "period": "H1", "metric": "revenue", "current_value": "£110",
            "prior_year_growth_pct": 10,  # implies prior_year_value = 110/1.10 = 100
        }})
    assert r.state == "pass"
    assert r.evidence["basis"] == "derived_from_fy_total"
    assert abs(r.evidence["preceding_value"] - 50.0) < 0.1  # 150 - 100


# ── Seasonality (GRG.L 9692273) ──────────────────────────────────────────────
# The gate's first ever real adjudication, and a false positive: Greggs' H1
# operating profit of £86.5m sits 26.1% below the derived H2 2025 of £117.1m
# (FY2025 £187.5m - H1 2025 £70.4m) purely because the business earns ~62% of
# its profit in H2. It blocked; the stock rose 18.5% that session. The
# announcement prints a three-year H1 table, which is what rescues it.
_GRG_ANNUALS = [{"operating_income": 195.3e6}, {"operating_income": 187.5e6}]  # oldest first


def test_low_base_gate_does_not_block_greggs_seasonal_h1():
    with patch("showcase._annual_history", return_value=_GRG_ANNUALS):
        r = _gate("low_base").evaluate({"symbol": "GRG.L", "low_base": {
            "period": "H1", "metric": "operating_income",
            "current_value": "£86.5m", "prior_year_value": "£70.4m",
            "prior_year_2_value": "£75.8m",
        }})
    assert r.state == "pass"
    # Sequentially down 26.1%, but up 14.1% on the same half two years ago...
    assert r.evidence["delta_pct"] < 0
    assert 13 < r.evidence["two_year_lfl_pct"] < 15
    # ...and the seasonal step is 15pp BETTER than the company's own norm
    # (-26.1% this year against -41.1% last year).
    assert 14 < r.evidence["vs_seasonal_norm_pp"] < 16


def test_low_base_gate_blocks_a_level_collapse_behind_a_normal_seasonal_step():
    # Test B's job: the seasonal step looks ordinary, but H1 is below where it
    # was two years ago — the low base is flattering a level that never
    # recovered. Test A sleeps through this one, which is why B is primary.
    with patch("showcase._annual_history", return_value=_GRG_ANNUALS):
        r = _gate("low_base").evaluate({"symbol": "GRG.L", "low_base": {
            "period": "H1", "metric": "operating_income",
            "current_value": "£70.0m", "prior_year_value": "£70.4m",
            "prior_year_2_value": "£75.8m",
        }})
    assert r.state == "block"
    assert r.reason == "below_same_period_two_years_ago"


def test_low_base_gate_blocks_a_seasonal_step_much_worse_than_the_norm():
    # Test A's job: grew over two years, so B passes it, but this year's step
    # is 5.4pp worse than the company's own — a real change in the pattern.
    # FY(n-1) 220.0 -> derived preceding H2 = 220.0 - 70.4 = 149.6.
    with patch("showcase._annual_history",
               return_value=[{"operating_income": 195.3e6}, {"operating_income": 220.0e6}]):
        r = _gate("low_base").evaluate({"symbol": "GRG.L", "low_base": {
            "period": "H1", "metric": "operating_income",
            "current_value": "£80.0m", "prior_year_value": "£70.4m",
            "prior_year_2_value": "£75.8m",
        }})
    assert r.state == "block"
    assert r.reason == "worse_than_seasonal_norm"
    assert r.evidence["two_year_lfl_pct"] > 0  # B alone would have passed it
    assert r.evidence["vs_seasonal_norm_pp"] < -5


def test_low_base_gate_ignores_a_preceding_figure_copied_from_the_prior_year():
    # Observed on GRG.L 9692273 with v4-flash:thinking — it put the prior-year
    # H1 (£70.4m) into preceding_period_value as well, which would have read as
    # a +22.9% sequential GAIN off the wrong base. Route 1 must decline it and
    # fall through to the FY-derived route, reaching the same verdict honestly.
    with patch("showcase._annual_history", return_value=_GRG_ANNUALS):
        r = _gate("low_base").evaluate({"symbol": "GRG.L", "low_base": {
            "period": "H1", "metric": "operating_income",
            "current_value": "£86.5m",
            "preceding_period_value": "£70.4m",   # the mis-copy
            "prior_year_value": "£70.4m",
            "prior_year_2_value": "£75.8m",
        }})
    assert r.state == "pass"
    assert r.evidence["basis"] == "derived_from_fy_total"
    assert r.evidence["delta_pct"] == -26.1  # the true sequential step, not +22.9


def test_low_base_gate_positive_sequential_step_needs_no_seasonality_evidence():
    # The CAPD/STAN/JNEO shape: above the preceding period, so no seasonal
    # pattern can explain it away and the two-year figure is never consulted.
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$117.3m", "preceding_period_value": "$101.7m",
    }})
    assert r.state == "pass"
    assert "two_year_lfl_pct" not in r.evidence


def test_low_base_gate_seasonal_norm_skipped_without_a_second_fiscal_year():
    # Only one FY on file — test A cannot be derived, so B decides alone and
    # the norm fields are simply absent rather than guessed.
    with patch("showcase._annual_history", return_value=[{"operating_income": 187.5e6}]):
        r = _gate("low_base").evaluate({"symbol": "GRG.L", "low_base": {
            "period": "H1", "metric": "operating_income",
            "current_value": "£86.5m", "prior_year_value": "£70.4m",
            "prior_year_2_value": "£75.8m",
        }})
    assert r.state == "pass"
    assert "vs_seasonal_norm_pp" not in r.evidence


def test_low_base_gate_records_model_direction_mismatch_without_changing_state():
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$117.3m", "preceding_period_value": "$101.7m",
        "direction": "below",  # the model guessed wrong; Python's figure still wins
    }})
    assert r.state == "pass"  # unaffected by the mismatch
    assert r.evidence["model_direction_mismatch"] == {"model": "below", "computed": "above"}


def test_low_base_gate_no_mismatch_recorded_when_model_direction_agrees():
    r = _gate("low_base").evaluate({"low_base": {
        "period": "Q2", "current_value": "$117.3m", "preceding_period_value": "$101.7m",
        "direction": "above",
    }})
    assert "model_direction_mismatch" not in r.evidence


# ── record_low_base_evaluation ───────────────────────────────────────────────
def test_record_low_base_evaluation_writes_the_shadow_gate_row():
    cand = {"symbol": "ABC.L", "low_base": {
        "period": "Q2", "current_value": "$117.3m", "preceding_period_value": "$101.7m",
    }}
    with patch.object(gates, "_exec", return_value=1) as ex:
        n = gates.record_low_base_evaluation(42, cand)
    assert n == 1
    args = ex.call_args[0][1]
    assert args[0] == 42
    assert args[1] == "low_base"
    assert args[2] == "pass"
    assert args[5] == "shadow"  # mode


def test_record_low_base_evaluation_not_vetted_when_no_low_base_key():
    with patch.object(gates, "_exec", return_value=1) as ex:
        gates.record_low_base_evaluation(7, {"symbol": "ABC.L"})
    args = ex.call_args[0][1]
    assert args[2] == "n/a"
    assert args[3] == "not_vetted"
