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


# ── _attach_risk_score ────────────────────────────────────────────────────────

from unittest.mock import patch


def _make_result(symbol, **kwargs):
    """Minimal screener result row."""
    defaults = {
        'symbol': symbol,
        'market_cap': 5e9,
        'revenue': 3e9,
        'operating_margin': 0.25,
        'price_to_book': 3.0,
    }
    defaults.update(kwargs)
    return defaults


def test_attach_risk_score_empty():
    from main import _attach_risk_score
    assert _attach_risk_score([]) == []


def test_attach_risk_score_attaches_fields():
    from main import _attach_risk_score
    results = [_make_result('SHEL.L')]

    ta_rows = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    # 10 closes with mild upward drift — oldest first
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i * 0.1} for i in range(252)]

    with patch('main.query', side_effect=[ta_rows, price_rows]):
        _attach_risk_score(results)

    r = results[0]
    assert 'risk_score' in r
    assert 'altman_z' in r
    assert 'volatility_annualised' in r
    assert r['risk_score'] is None or 1 <= r['risk_score'] <= 10


def test_attach_risk_score_null_when_no_data():
    from main import _attach_risk_score
    results = [_make_result('SHEL.L')]

    with patch('main.query', side_effect=[[], []]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_score'] is None
    assert r['altman_z'] is None
    assert r['volatility_annualised'] is None


def test_attach_risk_score_vol_none_when_insufficient_history():
    from main import _attach_risk_score
    results = [_make_result('SHEL.L')]

    ta_rows = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    # Only 10 closes — below the 63-row threshold
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i} for i in range(10)]

    with patch('main.query', side_effect=[ta_rows, price_rows]):
        _attach_risk_score(results)

    r = results[0]
    assert r['volatility_annualised'] is None
    # risk_score should still be set (from Altman alone)
    assert r['risk_score'] is not None


def test_screener_includes_risk_score(client):
    from unittest.mock import patch

    screener_row = {
        'symbol': 'SHEL.L', 'name': 'Shell', 'sector': 'Energy',
        'country': 'GB', 'exchange': 'LSE', 'ftse_index': 'FTSE 100',
        'financial_currency': 'USD',
        'market_cap': 5e9, 'revenue': 3e9, 'net_income': 5e8,
        'price_to_earnings': 12.0, 'price_to_book': 3.0, 'price_to_sales': 1.0,
        'roe': 0.15, 'roa': 0.08, 'roic': 0.12, 'roce': 0.10,
        'gross_margin': 0.4, 'operating_margin': 0.25, 'net_income_margin': 0.17,
        'revenue_growth': 0.05, 'eps_diluted_growth': 0.03, 'fcf_growth': 0.04,
        'debt_to_equity': 0.5, 'current_ratio': 1.5, 'fcf': 4e8, 'ebitda': 9e8,
        'revenue_cagr_10': 0.06, 'eps_cagr_10': 0.05, 'period_end_date': '2024-12-31',
        'fcf_margin': 0.13,
        'gross_margin_median': 0.38, 'operating_margin_median': 0.23,
        'net_margin_median': 0.15, 'roe_median': 0.14, 'roic_median': 0.11,
    }
    piotroski_row = {
        'company_symbol': 'SHEL.L',
        'roa_cur': 0.08, 'roa_prev': 0.07, 'cf_cfo': 4e8,
        'ta_cur': 4e9, 'ta_prev': 3.8e9,
        'de_cur': 0.5, 'de_prev': 0.6,
        'cr_cur': 1.5, 'cr_prev': 1.4,
        'sh_cur': 1e9, 'sh_prev': 1e9,
        'gm_cur': 0.4, 'gm_prev': 0.38,
        'rev_cur': 3e9, 'rev_prev': 2.8e9,
    }
    ta_row = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i * 0.05} for i in range(252)]

    with patch('main.query', side_effect=[
        [screener_row],   # screener SQL
        [piotroski_row],  # _attach_piotroski annual_financials
        ta_row,           # _attach_risk_score total_assets
        price_rows,       # _attach_risk_score price_history
    ]):
        with patch('prices.query', return_value=[]):  # _attach_momentum
            r = client.get('/api/screener')

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert 'risk_score' in data[0]
    assert 'altman_z' in data[0]
    assert 'volatility_annualised' in data[0]


def test_snapshot_includes_risk_fields(client):
    snap_row = {
        'company_symbol': 'SHEL.L',
        'market_cap': 5e9, 'revenue': 3e9, 'net_income': 5e8,
        'price_to_earnings': 12.0, 'price_to_book': 3.0, 'price_to_sales': 1.0,
        'roe': 0.15, 'roa': 0.08, 'roic': 0.12, 'roce': 0.10,
        'gross_margin': 0.4, 'operating_margin': 0.25, 'net_income_margin': 0.17,
        'revenue_growth': 0.05, 'eps_diluted_growth': 0.03, 'fcf_growth': 0.04,
        'debt_to_equity': 0.5, 'current_ratio': 1.5, 'fcf': 4e8, 'ebitda': 9e8,
        'revenue_cagr_10': 0.06, 'eps_cagr_10': 0.05, 'period_end_date': '2024-12-31',
        'fcf_margin': 0.13,
        'gross_margin_median': 0.38, 'operating_margin_median': 0.23,
        'net_margin_median': 0.15, 'roe_median': 0.14, 'roic_median': 0.11,
        'debt_to_assets': 0.3, 'cash_and_equiv': 2e8, 'net_debt': 5e8,
        'working_capital': 3e8, 'interest_coverage': 8.0, 'book_value': 1.5e9,
        'net_income_growth': 0.06, 'fcf_cagr_10': 0.05, 'equity_cagr_10': 0.04,
    }
    ta_row = [{'company_symbol': 'SHEL.L', 'total_assets': 4e9}]
    price_rows = [{'symbol': 'SHEL.L', 'close': 100.0 + i * 0.05} for i in range(252)]

    with patch('main.query', side_effect=[
        [snap_row],   # SELECT * FROM ttm_financials
        ta_row,       # _attach_risk_score total_assets
        price_rows,   # _attach_risk_score price_history
    ]):
        r = client.get('/api/snapshot?symbol=SHEL.L')

    assert r.status_code == 200
    data = r.json()
    assert 'risk_score' in data
    assert 'altman_z' in data
    assert 'volatility_annualised' in data
