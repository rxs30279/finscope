import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import (
    _valuation_eligible, _peer_median, _fair_value_upside, _peer_group,
    MAX_NET_DEBT_TO_MKT_CAP,
)


def _f(x):
    return float(x) if x is not None else None


def _ok_row(**over):
    # Profitable, non-financial, low-leverage company — the eligible base case.
    row = {"sector": "Industrials", "net_income": 4e8, "ebitda": 9e8,
           "market_cap": 5e9, "net_debt": 1e9, "ev_to_ebitda": 8.5}
    row.update(over)
    return row


# ── _valuation_eligible (EV/EBITDA-only safe subset) ────────────────────────────

def test_eligible_profitable_nonfinancial_low_leverage():
    assert _valuation_eligible(_ok_row(), _f) == 8.5

def test_eligible_net_cash_is_fine():
    assert _valuation_eligible(_ok_row(net_debt=-2e8), _f) == 8.5

def test_excluded_financial_sector():
    assert _valuation_eligible(_ok_row(sector="Financial Services"), _f) is None

def test_excluded_real_estate():
    assert _valuation_eligible(_ok_row(sector="Real Estate"), _f) is None

def test_excluded_by_is_financial_naming():
    # _is_financial catches bank/insurance naming even if sector isn't the GICS one.
    assert _valuation_eligible(_ok_row(sector="Insurance - Diversified"), _f) is None

def test_excluded_loss_maker():
    assert _valuation_eligible(_ok_row(net_income=-1e7), _f) is None

def test_excluded_negative_ebitda():
    assert _valuation_eligible(_ok_row(ebitda=-5e7), _f) is None

def test_excluded_high_leverage():
    # net_debt just over the cap × market cap → excluded (equity bridge unstable).
    row = _ok_row(market_cap=1e9, net_debt=MAX_NET_DEBT_TO_MKT_CAP * 1e9 + 1)
    assert _valuation_eligible(row, _f) is None

def test_eligible_at_leverage_cap():
    # Exactly at the cap is allowed.
    row = _ok_row(market_cap=1e9, net_debt=MAX_NET_DEBT_TO_MKT_CAP * 1e9)
    assert _valuation_eligible(row, _f) == 8.5

def test_excluded_missing_ev_ebitda():
    assert _valuation_eligible(_ok_row(ev_to_ebitda=None), _f) is None


# ── _peer_group (industry merges + per-symbol overrides) ────────────────────────

def test_peer_group_merges_oversplit_industry():
    # AZN and GSK sit in different-but-related drug industries; both -> Pharmaceuticals.
    assert _peer_group("AZN.L", "Drug Manufacturers - General") == "Pharmaceuticals"
    assert _peer_group("XYZ.L", "Drug Manufacturers - Specialty & Generic") == "Pharmaceuticals"

def test_peer_group_passthrough_for_unmapped_industry():
    assert _peer_group("ABC.L", "Specialty Retail") == "Specialty Retail"

def test_peer_group_symbol_override_wins():
    # yfinance tags Bunzl "Food Distribution"; override routes it to its real group.
    assert _peer_group("BNZL.L", "Food Distribution") == "Industrial Distribution"

def test_peer_group_haleon_is_consumer_staples_not_pharma():
    # Haleon is consumer health (Sensodyne/Panadol) — comps are ULVR/RKT, not
    # AZN/GSK, despite its "Drug Manufacturers - Specialty & Generic" tag.
    assert _peer_group("HLN.L", "Drug Manufacturers - Specialty & Generic") == "Household & Personal Products"

def test_peer_group_none_industry():
    assert _peer_group("ABC.L", None) is None


# ── _peer_median ────────────────────────────────────────────────────────────────

def test_peer_median_odd():
    assert _peer_median([10, 20, 30]) == 20

def test_peer_median_resists_single_extreme():
    assert _peer_median([8, 9, 10, 11, 1000]) == 10


# ── _fair_value_upside (currency-safe EV/EBITDA bridge) ─────────────────────────

def test_upside_bridges_net_debt():
    # peer 12 × EBITDA 100 = fair EV 1200; less net debt 200 = fair equity 1000;
    # vs market cap 800 → +25%. All one reporting currency → dimensionless.
    row = {"ebitda": 100, "net_debt": 200, "market_cap": 800}
    assert _fair_value_upside(12.0, row, _f) == pytest.approx(0.25)

def test_upside_fairly_valued():
    row = {"ebitda": 100, "net_debt": 200, "market_cap": 800}
    assert _fair_value_upside(10.0, row, _f) == pytest.approx(0.0)

def test_upside_net_cash_adds_to_equity():
    row = {"ebitda": 100, "net_debt": -50, "market_cap": 1000}
    assert _fair_value_upside(10.0, row, _f) == pytest.approx(0.05)

def test_upside_none_when_market_cap_missing():
    row = {"ebitda": 100, "net_debt": 200, "market_cap": None}
    assert _fair_value_upside(12.0, row, _f) is None

def test_upside_below_minus_one_triggers_value_guard():
    # Net debt swamps a low peer multiple → implied equity negative, so
    # fair_value = price*(1+upside) would be negative; the compute step's fv>0
    # guard then suppresses the estimate.
    row = {"ebitda": 100, "net_debt": 900, "market_cap": 400}
    upside = _fair_value_upside(5.0, row, _f)  # (500-900)/400 - 1 = -2.0
    assert upside == pytest.approx(-2.0)
    assert 400 * (1 + upside) < 0
