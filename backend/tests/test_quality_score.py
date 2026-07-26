"""Quality score: imputation of legs the scrub removed.

The scrub blanks metrics that are junk for a business model (bank FCF, trust
revenue) before _quality_score reads the row. Summing the surviving legs raw
scored those blanks as failures, hard-capping banks/insurers at 4/10 and trusts
at 2/10. _quality_score now credits a blanked leg at the universe base rate.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import (
    _QUALITY_LEG_BASE_RATES,
    _QUALITY_MIN_LEGS,
    _classify_risk_model,
    _quality_legs,
    _quality_score,
)


def _row(**overrides):
    """A row that passes every one of the ten legs (raw score 10/10)."""
    base = {
        "roic": 0.20, "roic_median": 0.10,
        "roe": 0.25, "roe_median": 0.15,
        "gross_margin": 0.45, "gross_margin_median": 0.40,
        "operating_margin": 0.18, "operating_margin_median": 0.12,
        "fcf_margin": 0.09,
        "net_income_margin": 0.11, "net_margin_median": 0.08,
    }
    base.update(overrides)
    return base


def _failing_row(**overrides):
    """A row where every available leg fails."""
    base = {
        "roic": 0.01, "roic_median": 0.10,
        "roe": 0.02, "roe_median": 0.15,
        "gross_margin": 0.05, "gross_margin_median": 0.40,
        "operating_margin": 0.01, "operating_margin_median": 0.12,
        "fcf_margin": 0.001,
        "net_income_margin": 0.01, "net_margin_median": 0.08,
    }
    base.update(overrides)
    return base


# Fields _BANK_INSURER_NA_FIELDS blanks that _quality_score reads.
_BANK_BLANKED = {"roic": None, "gross_margin": None, "fcf_margin": None}
# Ditto _TRUST_NA_FIELDS.
_TRUST_BLANKED = dict(_BANK_BLANKED, operating_margin=None, net_income_margin=None)


def test_full_coverage_is_unchanged():
    # Nothing to impute, so the score is exactly the legs earned.
    assert _quality_score(_row()) == 10
    assert _quality_score(_failing_row()) == 0


def test_full_coverage_partial_score():
    # roe 0.05 fails both roe legs (< 0.15 absolute, < its 0.15 median);
    # gross margin 0.10 likewise fails both gm legs. Four legs lost.
    r = _row(roe=0.05, gross_margin=0.10)
    assert _quality_score(r) == 6


def test_bank_is_not_capped_at_four():
    """The bug: a bank passing every leg it has used to top out at 4/10."""
    r = _row(**_BANK_BLANKED)
    earned = sum(1 for _, avail, won in _quality_legs(r) if avail and won)
    assert earned == 5  # five legs survive the blanking, all passed
    assert _quality_score(r) > earned
    assert _quality_score(r) == 8


def test_bank_failing_everything_stays_low():
    # Imputation must not launder a genuinely weak bank into mid-table.
    r = _failing_row(**_BANK_BLANKED)
    assert _quality_score(r) == 3


def test_perfect_thin_row_does_not_reach_ten():
    """Five-from-five is not the evidence ten-from-ten is.

    This is what plain earned/available renormalisation got wrong: it would
    score this row 10, ranking it level with a fully-covered company.
    """
    assert _quality_score(_row(**_BANK_BLANKED)) < _quality_score(_row())


def test_net_margin_leg_survives_blanked_fcf():
    """nm_med must not be collateral damage of blanking fcf_margin.

    It was nested inside the fcf_margin branch, so a bank silently lost a point
    about net margin vs its own history -- nothing to do with cash flow.
    """
    legs = dict((name, avail) for name, avail, _ in _quality_legs(_row(fcf_margin=None)))
    assert legs["nm_med"] is True
    assert legs["fcfm_abs"] is False


def test_trust_returns_none_below_min_legs():
    # A closed-end fund keeps only roe_abs + roe_med: too thin to score.
    r = _row(**_TRUST_BLANKED)
    available = sum(1 for _, avail, _ in _quality_legs(r) if avail)
    assert available == 2 < _QUALITY_MIN_LEGS
    assert _quality_score(r) is None


def test_empty_row_returns_none():
    assert _quality_score({}) is None


def test_score_stays_in_range():
    for r in (_row(), _failing_row(), _row(**_BANK_BLANKED),
              _failing_row(**_BANK_BLANKED)):
        assert 0 <= _quality_score(r) <= 10


def test_base_rates_cover_every_leg():
    """A leg missing from the table would raise KeyError on a blanked row."""
    names = {name for name, _, _ in _quality_legs(_row())}
    assert names == set(_QUALITY_LEG_BASE_RATES)


def test_backfilled_trusts_still_classify_as_trust():
    """Migration 022 gives trusts a sector; they must keep the trust model.

    Without the industry check they would fall through to the "financ" in
    sector catch-all and lose the trust metric blanking.
    """
    row = {"sector": "Financial Services", "industry": "Investment Trust"}
    assert _classify_risk_model(row) == "trust"


def test_unlabelled_trust_still_classifies_as_trust():
    # Fallback for a newly-added trust that arrives from Yahoo pre-backfill.
    assert _classify_risk_model({"sector": None, "industry": None}) == "trust"


def test_backfilled_trust_is_not_read_as_bank_or_insurer():
    for industry in ("Investment Trust",):
        row = {"sector": "Financial Services", "industry": industry}
        assert _classify_risk_model(row) not in ("bank", "insurer", "financial")
