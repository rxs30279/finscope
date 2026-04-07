import sys, os, math, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import _altman_z, _z_to_risk, _annualised_vol, _vol_to_score, _blend_risk


# ── _altman_z ─────────────────────────────────────────────────────────────────

def test_altman_z_returns_none_when_total_assets_none():
    row = {'market_cap': 1e9, 'revenue': 5e8, 'operating_margin': 0.2, 'price_to_book': 2.0}
    assert _altman_z(row, None) is None

def test_altman_z_returns_none_when_total_assets_zero():
    row = {'market_cap': 1e9, 'revenue': 5e8, 'operating_margin': 0.2, 'price_to_book': 2.0}
    assert _altman_z(row, 0) is None

def test_altman_z_computes_correctly():
    # market_cap=5B, revenue=3B, op_margin=0.25, p2b=3.0, total_assets=4B
    # book_equity = 5B/3 = 1.6667B
    # X1 = 0 (skipped)
    # X2 = 1.6667B / 4B = 0.4167
    # X3 = (0.25 * 3B) / 4B = 0.1875
    # X4 = 5B / (4B - 1.6667B) = 5B / 2.3333B = 2.1429
    # X5 = 3B / 4B = 0.75
    # Z = 0 + 1.4*0.4167 + 3.3*0.1875 + 0.6*2.1429 + 1.0*0.75
    # Z = 0.5833 + 0.6188 + 1.2857 + 0.75 = 3.2378
    row = {'market_cap': 5e9, 'revenue': 3e9, 'operating_margin': 0.25, 'price_to_book': 3.0}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(3.238, abs=0.01)

def test_altman_z_skips_x2_x4_when_price_to_book_none():
    # Only X3 + X5 contribute
    # X3 = (0.20 * 2B) / 4B = 0.10
    # X5 = 2B / 4B = 0.50
    # Z = 3.3*0.10 + 1.0*0.50 = 0.33 + 0.50 = 0.83
    row = {'market_cap': 1e9, 'revenue': 2e9, 'operating_margin': 0.20, 'price_to_book': None}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(0.83, abs=0.01)

def test_altman_z_skips_x3_when_operating_margin_none():
    # market_cap=4B, p2b=2.0, revenue=2B, total_assets=4B
    # book_equity = 4B/2 = 2B
    # X2 = 2B/4B = 0.5
    # X3 skipped (operating_margin=None)
    # X4 = 4B / (4B - 2B) = 4B/2B = 2.0
    # X5 = 2B/4B = 0.5
    # Z = 1.4*0.5 + 0 + 0.6*2.0 + 1.0*0.5 = 0.7 + 1.2 + 0.5 = 2.4
    row = {'market_cap': 4e9, 'revenue': 2e9, 'operating_margin': None, 'price_to_book': 2.0}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(2.4, abs=0.01)

def test_altman_z_returns_none_when_total_liabilities_not_positive():
    # book_equity >= total_assets → total_liabilities <= 0 → skip X4
    # market_cap=10B, p2b=1.0 → book_equity=10B > total_assets=4B
    # X2 = 10B/4B = 2.5 (still computed)
    # X4 skipped (total_liabilities <= 0)
    # X3 = (0.20*2B)/4B = 0.10
    # X5 = 2B/4B = 0.50
    # Z = 1.4*2.5 + 3.3*0.10 + 0 + 1.0*0.50 = 3.5 + 0.33 + 0.5 = 4.33
    row = {'market_cap': 10e9, 'revenue': 2e9, 'operating_margin': 0.20, 'price_to_book': 1.0}
    result = _altman_z(row, 4e9)
    assert result == pytest.approx(4.33, abs=0.01)


# ── _z_to_risk ────────────────────────────────────────────────────────────────

def test_z_to_risk_safe_zone():
    assert _z_to_risk(3.0) == 1
    assert _z_to_risk(5.0) == 1

def test_z_to_risk_distress_zone():
    assert _z_to_risk(1.0) == 10
    assert _z_to_risk(-1.0) == 10

def test_z_to_risk_midpoint():
    # z=2.0 → 1 + (3.0-2.0)*4.5 = 1 + 4.5 = 5.5 → round → 6
    assert _z_to_risk(2.0) == 6

def test_z_to_risk_grey_zone_interpolation():
    # z=2.5 → 1 + (3.0-2.5)*4.5 = 1 + 2.25 = 3.25 → round → 3
    assert _z_to_risk(2.5) == 3

def test_z_to_risk_none_input():
    assert _z_to_risk(None) is None


# ── _annualised_vol ───────────────────────────────────────────────────────────

def test_annualised_vol_empty():
    assert _annualised_vol([]) is None

def test_annualised_vol_single_price():
    assert _annualised_vol([100.0]) is None

def test_annualised_vol_flat_prices():
    # All same price → zero returns → vol = 0
    closes = [100.0] * 252
    result = _annualised_vol(closes)
    assert result == pytest.approx(0.0, abs=1e-10)

def test_annualised_vol_positive():
    # 10% daily vol annualises to ~10% * sqrt(252) ≈ 158.7%
    import random
    random.seed(42)
    closes = [100.0]
    for _ in range(251):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.01)))
    result = _annualised_vol(closes)
    assert result > 0
    assert result < 2.0  # sanity bound — well under 200%


# ── _vol_to_score ─────────────────────────────────────────────────────────────

def test_vol_to_score_none():
    assert _vol_to_score(None) is None

def test_vol_to_score_very_low():
    assert _vol_to_score(0.08) == 1   # < 10%

def test_vol_to_score_boundaries():
    assert _vol_to_score(0.10) == 2   # 10-15%
    assert _vol_to_score(0.20) == 4   # 20-25%
    assert _vol_to_score(0.30) == 6   # 30-35%
    assert _vol_to_score(0.50) == 9   # 50-60%
    assert _vol_to_score(0.70) == 10  # > 60%


# ── _blend_risk ───────────────────────────────────────────────────────────────

def test_blend_risk_both_components():
    # 0.6 * 4 + 0.4 * 6 = 2.4 + 2.4 = 4.8 → round → 5
    assert _blend_risk(4, 6) == 5

def test_blend_risk_altman_only():
    assert _blend_risk(7, None) == 7

def test_blend_risk_vol_only():
    assert _blend_risk(None, 3) == 3

def test_blend_risk_both_none():
    assert _blend_risk(None, None) is None

def test_blend_risk_clamped():
    # Should stay within 1-10
    assert _blend_risk(10, 10) == 10
    assert _blend_risk(1, 1) == 1
