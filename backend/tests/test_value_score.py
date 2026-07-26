"""Value score: the lens floor, and the closed-end-fund branch.

Two defects, one function. Operating companies were scored off as few as two
lenses, which is not a thin average but a coin flip — universe-wide, two-lens
non-trust rows sat at a median 4.5 with 40% at >=8 and 45% at <=3. And every
lens a closed-end fund has left after the scrub is one calibrated for an
operating company, so a fund trading AT NAV scored 0.93/1.0 on price-to-book:
46 of the universe's 76 perfect-10 value scores were funds at roughly fair
value, each with quality n/a beside it.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import (
    _TRUST_PB_CHEAP,
    _TRUST_PB_RICH,
    _VALUE_MIN_LENSES,
    _value_score,
)
from quality import blank_model_fields, effective_model


def _operating(**overrides):
    """A general-model row with all six lenses available and mid-range."""
    base = {
        "name": "Test Industrials plc",
        "sector": "Industrials",
        "industry": "Specialty Business Services",
        "risk_model": "general",
        "price_to_earnings": 15.0,
        "price_to_book": 2.0,
        "price_to_sales": 2.5,
        "pegy": 1.5,
        "dividend_yield": 0.03,
        "fcf": 50_000_000,
        "market_cap": 1_000_000_000,
    }
    base.update(overrides)
    return base


def _trust(**overrides):
    """A closed-end fund as the screener sees it — TRUST_NA_FIELDS already
    blanked, so only price-to-book and a meaningless P/E survive."""
    base = {
        "name": "Test Investment Trust plc",
        "sector": "Financial Services",
        "industry": "Asset Management",
        "risk_model": "financial",   # what Yahoo/classify_risk_model says
        "price_to_book": 1.0,
        "price_to_earnings": 8.0,    # investment gains — must be ignored
        "price_to_sales": None,
        "pegy": None,
        "dividend_yield": None,
        "fcf": None,
        "market_cap": 500_000_000,
    }
    base.update(overrides)
    return base


# ── The lens floor (operating companies) ─────────────────────────────────────

def test_two_lenses_is_not_enough():
    r = _operating(price_to_sales=None, pegy=None, dividend_yield=None, fcf=None)
    assert _value_score(r) is None


def test_three_lenses_is_enough():
    r = _operating(pegy=None, dividend_yield=None, fcf=None)
    assert _value_score(r) is not None


def test_floor_is_three():
    """Guard the constant itself — the whole point is that two is below it."""
    assert _VALUE_MIN_LENSES == 3


def test_full_coverage_row_still_scored_and_ordered():
    """The floor must not disturb rows that were never thin. Cheaper inputs
    across every lens still have to score strictly higher."""
    cheap = _operating(price_to_earnings=8.0, price_to_book=0.7,
                       price_to_sales=0.4, pegy=0.7, dividend_yield=0.07,
                       fcf=150_000_000)
    dear = _operating(price_to_earnings=30.0, price_to_book=5.0,
                      price_to_sales=8.0, pegy=4.0, dividend_yield=0.0,
                      fcf=1_000_000)
    assert _value_score(cheap) == 10
    assert _value_score(dear) == 0


# ── The closed-end-fund branch ───────────────────────────────────────────────

def test_fund_at_nav_scores_mid_scale():
    """Par is neutral. This is the regression that matters: the old
    operating-company band (0.75-4.0) returned 9-10 here."""
    assert _value_score(_trust(price_to_book=1.0)) == 5


def test_fund_at_a_discount_is_cheap():
    assert _value_score(_trust(price_to_book=_TRUST_PB_CHEAP)) == 10
    assert _value_score(_trust(price_to_book=0.45)) == 10


def test_fund_at_a_premium_is_dear():
    assert _value_score(_trust(price_to_book=_TRUST_PB_RICH)) == 0
    assert _value_score(_trust(price_to_book=1.4)) == 0


def test_fund_discount_is_monotonic():
    scores = [_value_score(_trust(price_to_book=pb))
              for pb in (0.80, 0.90, 1.00, 1.10, 1.20)]
    assert scores == sorted(scores, reverse=True)
    assert len(set(scores)) > 1


def test_fund_ignores_its_earnings_and_yield():
    """A fund's "earnings" are investment gains and its yield follows its
    mandate, so neither may rescue a premium-to-NAV price."""
    rich = _trust(price_to_book=1.3, price_to_earnings=4.0,
                  dividend_yield=0.09)
    assert _value_score(rich) == 0


def test_fund_needs_no_second_lens():
    """Price/book alone IS the valuation for the form, so the operating-company
    floor must not apply — this row would be unscored under it."""
    r = _trust(price_to_book=0.9, price_to_earnings=None)
    assert _value_score(r) == 8  # a tenth below NAV, on a 0.80-1.20 band


def test_fund_without_price_to_book_is_unscored():
    assert _value_score(_trust(price_to_book=None)) is None


def test_fund_with_negative_book_is_unscored():
    assert _value_score(_trust(price_to_book=-0.5)) is None


# ── Which rows reach the fund branch ─────────────────────────────────────────

def test_name_matched_fund_takes_the_trust_branch():
    """Yahoo files most UK trusts under Asset Management, so risk_model says
    'financial' and only the name gives them away."""
    r = _trust(name="Scottish Mortgage Investment Trust Ord")
    assert effective_model(r) == "trust"
    assert _value_score(r) == 5


def test_stamped_trust_industry_takes_the_trust_branch():
    """Migration 022's own industry label, independent of the name."""
    r = _trust(name="Something Opaque plc", industry="Investment Trust",
               risk_model=None)
    assert effective_model(r) == "trust"


def test_real_asset_manager_is_not_a_fund():
    """An operating asset manager earns fees; it is scored as a company."""
    r = _operating(name="Liontrust Asset Management Plc",
                   sector="Financial Services", industry="Asset Management",
                   risk_model="financial")
    assert effective_model(r) == "financial"
    assert _value_score(r) == _value_score(_operating())


def test_effective_model_still_drives_blanking():
    """effective_model was extracted OUT of blank_model_fields so _value_score
    could share it — blanking must be unchanged by the move."""
    r = _trust(name="Test Investment Trust plc", revenue_growth=99.0,
               gross_margin=0.5, roic=0.4)
    blank_model_fields(r)
    assert r["revenue_growth"] is None
    assert r["gross_margin"] is None
    assert r["roic"] is None
