"""GET /api/gates — the matrix endpoint behind the /gates admin page.

DB access is mocked via gates._q (same pattern as test_showcase.py's use of
showcase._q), so these run without a database.
"""
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

import gates
from main import app


def _matrix_row(rns_id, symbol="ABC.L", category="final_results", market_cap=200_000_000):
    return {
        "rns_id": rns_id, "symbol": symbol, "company_name": "Abc plc",
        "headline": "H1 results", "url": f"https://example.com/rns/{rns_id}", "category": category,
        "published_at": datetime(2026, 7, 29, 7, 0, tzinfo=timezone.utc),
        "llm_score": 78, "llm_sentiment": "positive",
        "sector": "Industrials", "industry": "x", "ftse_index": "FTSE 250",
        "market_cap": market_cap,
    }


def _fake_q(matrix_rows, eval_rows):
    def q(sql, params=None):
        if "FROM rns_announcements r" in sql:
            return matrix_rows
        if "FROM rns_gate_evaluations" in sql:
            return eval_rows
        if "FROM price_history" in sql:
            return []  # no price history mocked -> returns stay open/terminated
        return []
    return q


def test_requires_admin_token():
    bare = TestClient(app)
    assert bare.get("/api/gates").status_code == 403


# ── population facet ──────────────────────────────────────────────────────────
# The 2026-08-04 audit found the header numbers were describing the SQL floors
# rather than the gates: the guidance gate showed 9 lifetime blocks and not one
# was load-bearing, because "evaluate wide, block narrow" records a verdict for
# every ranked row including those that die at a floor before any gate runs.
def _flaggable_row(rns_id, **over):
    """A row that clears every non-gate floor, so it really reached the gates."""
    row = _matrix_row(rns_id)
    row.update({"llm_action": "watch", "llm_score": 78, "category": "final_results"})
    row.update(over)
    return row


_BLOCKED = lambda i: [  # noqa: E731
    {"rns_id": i, "gate": "guidance", "state": "block", "reason": "reiterated_vs_consensus_below",
     "evidence": {"metric": "x"}, "mode": "armed"},
]


def test_population_all_counts_rows_no_gate_could_have_decided(client):
    # Row 2 never reached a gate (no llm_action -> fails the action floor), but
    # carries a stored block. The default view counts it, and says so.
    rows = [_flaggable_row(1), _flaggable_row(2, llm_action=None)]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, _BLOCKED(1) + _BLOCKED(2))):
        body = client.get("/api/gates").json()
    assert body["population"] == "all"
    assert body["cohort_n"] == 2
    assert body["population_n"] == 2
    assert body["reached_gates_n"] == 1       # always reported, even on "all"
    assert body["header"]["guidance"]["n"] == 2
    assert body["header"]["guidance"]["fire_rate"] == 1.0


def test_population_reached_gates_narrows_the_denominator(client):
    rows = [_flaggable_row(1), _flaggable_row(2, llm_action=None)]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, _BLOCKED(1) + _BLOCKED(2))):
        body = client.get("/api/gates?population=reached_gates").json()
    assert body["population"] == "reached_gates"
    assert body["population_n"] == 1
    assert body["header"]["guidance"]["n"] == 1
    # Both rows are still DISPLAYED — this facet moves the denominator only.
    assert len(body["rows"]) == 2


def test_population_reached_gates_can_empty_the_stats_without_erroring(client):
    # The real shape of the finding: every block on record died at a floor, so
    # the honest fire rate is over n=0. Must not ZeroDivisionError.
    rows = [_flaggable_row(1, llm_action=None)]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, _BLOCKED(1))):
        body = client.get("/api/gates?population=reached_gates").json()
    assert body["population_n"] == 0
    assert body["header"]["guidance"]["n"] == 0
    assert body["header"]["guidance"]["fire_rate"] is None
    assert len(body["rows"]) == 1


def test_unknown_population_falls_back_to_all(client):
    rows = [_flaggable_row(1, llm_action=None)]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, _BLOCKED(1))):
        body = client.get("/api/gates?population=nonsense").json()
    assert body["population"] == "all"
    assert body["header"]["guidance"]["n"] == 1


def test_matrix_shape_and_default_adjudicated_filter(client):
    rows = [_matrix_row(1), _matrix_row(2)]
    evals = [
        {"rns_id": 1, "gate": "sentiment", "state": "pass", "reason": None, "evidence": None, "mode": "armed"},
        {"rns_id": 1, "gate": "guidance", "state": "block", "reason": "reiterated_vs_consensus_below",
         "evidence": {"metric": "x"}, "mode": "armed"},
        {"rns_id": 1, "gate": "earnings_quality", "state": "n/a", "reason": "not_a_bank", "evidence": None, "mode": "armed"},
        # row 2: every gate n/a -> filtered out by the default show_all=False
        {"rns_id": 2, "gate": "sentiment", "state": "n/a", "reason": "gate_error", "evidence": None, "mode": "armed"},
        {"rns_id": 2, "gate": "guidance", "state": "n/a", "reason": "field_absent", "evidence": None, "mode": "armed"},
        {"rns_id": 2, "gate": "earnings_quality", "state": "n/a", "reason": "not_a_bank", "evidence": None, "mode": "armed"},
    ]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, evals)):
        r = client.get("/api/gates")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"generated_at", "window", "cohort", "show_all", "gates", "header", "rows"}
    assert [g["name"] for g in body["gates"]] == [
        "sentiment", "guidance", "guidance_wide", "earnings_quality", "low_base",
    ]
    # row 2 (all-n/a) dropped by the default adjudicated-only filter
    assert [row["rns_id"] for row in body["rows"]] == [1]
    assert body["rows"][0]["gates"]["guidance"]["state"] == "block"
    assert body["rows"][0]["gates"]["guidance"]["evidence"] == {"metric": "x"}
    # header counted over the FULL cohort (both rows), not the filtered display
    assert body["header"]["guidance"]["n"] == 2
    assert body["header"]["guidance"]["fire_rate"] == 0.5


def test_show_all_includes_fully_amber_rows(client):
    rows = [_matrix_row(2)]
    evals = [
        {"rns_id": 2, "gate": "sentiment", "state": "n/a", "reason": "gate_error", "evidence": None, "mode": "armed"},
    ]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, evals)):
        r = client.get("/api/gates?show_all=true")
    assert [row["rns_id"] for row in r.json()["rows"]] == [2]


def test_cohort_category_filters_out_non_category_and_out_of_universe(client):
    rows = [
        _matrix_row(1, category="final_results", market_cap=200_000_000),  # keeps
        _matrix_row(2, category="board_change", market_cap=200_000_000),   # wrong category
        _matrix_row(3, category="final_results", market_cap=None),         # out of universe
    ]
    evals = [
        {"rns_id": i, "gate": "sentiment", "state": "pass", "reason": None, "evidence": None, "mode": "armed"}
        for i in (1, 2, 3)
    ]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, evals)):
        r = client.get("/api/gates?cohort=category&show_all=true")
    assert [row["rns_id"] for row in r.json()["rows"]] == [1]


def test_cohort_all_keeps_everything(client):
    rows = [_matrix_row(1, category="board_change", market_cap=None)]
    evals = [
        {"rns_id": 1, "gate": "sentiment", "state": "pass", "reason": None, "evidence": None, "mode": "armed"},
    ]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, evals)):
        r = client.get("/api/gates?cohort=all&show_all=true")
    body = r.json()
    assert [row["rns_id"] for row in body["rows"]] == [1]
    assert body["rows"][0]["in_universe"] is False


def test_vet_verdict_passed_through_when_present_null_otherwise(client):
    # Display-only: row 1 already went through the vet (LEFT JOIN high_impact_rns
    # hit); row 2 never cleared the public flag's floors, so it's null.
    rows = [
        {**_matrix_row(1), "vet_verdict": "caution", "vet_rationale": "Guidance reiterated, not raised."},
        _matrix_row(2),
    ]
    evals = [
        {"rns_id": i, "gate": "sentiment", "state": "pass", "reason": None, "evidence": None, "mode": "armed"}
        for i in (1, 2)
    ]
    with patch.object(gates, "_q", side_effect=_fake_q(rows, evals)):
        r = client.get("/api/gates?show_all=true")
    by_id = {row["rns_id"]: row for row in r.json()["rows"]}
    assert by_id[1]["vet_verdict"] == "caution"
    assert by_id[1]["vet_rationale"] == "Guidance reiterated, not raised."
    assert by_id[2]["vet_verdict"] is None
    assert by_id[2]["vet_rationale"] is None
