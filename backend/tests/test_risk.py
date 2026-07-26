import sys, os, math, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import (
    _lin, _weighted_blend, _classify_risk_model, _classify_model,
    _altman_terms, _z_score,
    _Z_WEIGHTS, _ZDD_WEIGHTS, _z_to_risk, _zdd_to_risk, _annualised_vol,
    _vol_to_score, _roe_to_risk, _roe_blend, _debt_service_component,
)
from quality import effective_model


# ── _lin ──────────────────────────────────────────────────────────────────────

def test_lin_none():
    assert _lin(None, 1.0, 8.0) is None

def test_lin_ascending_risk():
    # safe=1 → 1, risky=8 → 10 (net-debt/EBITDA direction)
    assert _lin(0.5, 1.0, 8.0) == 1
    assert _lin(1.0, 1.0, 8.0) == 1
    assert _lin(8.0, 1.0, 8.0) == 10
    assert _lin(12.0, 1.0, 8.0) == 10
    assert _lin(4.5, 1.0, 8.0) == 6  # midpoint → 5.5 → round → 6

def test_lin_descending_risk():
    # safe=8 → 1, risky=1 → 10 (interest-coverage direction)
    assert _lin(10.0, 8.0, 1.0) == 1
    assert _lin(1.0, 8.0, 1.0) == 10
    assert _lin(-5.0, 8.0, 1.0) == 10  # negative coverage saturates at 10
    assert _lin(4.5, 8.0, 1.0) == 6


# ── _weighted_blend ───────────────────────────────────────────────────────────

def test_weighted_blend_all_present():
    # 0.6*4 + 0.4*6 = 4.8 → 5 (matches v1 _blend_risk behaviour)
    assert _weighted_blend([(4, 0.6), (6, 0.4)]) == 5

def test_weighted_blend_renormalises_missing():
    # None component redistributes its weight: only the 7 remains
    assert _weighted_blend([(7, 0.6), (None, 0.4)]) == 7
    # 0.4*2 + 0.3*None + 0.3*8 → (0.4*2 + 0.3*8) / 0.7 = 3.2/0.7 ≈ 4.57 → 5
    assert _weighted_blend([(2, 0.4), (None, 0.3), (8, 0.3)]) == 5

def test_weighted_blend_all_none():
    assert _weighted_blend([(None, 0.5), (None, 0.5)]) is None

def test_weighted_blend_clamped():
    assert _weighted_blend([(10, 1.0)]) == 10
    assert _weighted_blend([(1, 1.0)]) == 1


# ── _classify_risk_model ──────────────────────────────────────────────────────

def test_classify_trust_when_no_sector_or_industry():
    assert _classify_risk_model({'sector': None, 'industry': None}) == 'trust'
    assert _classify_risk_model({'sector': '', 'industry': ''}) == 'trust'

def test_classify_bank_by_industry():
    assert _classify_risk_model(
        {'sector': 'Financial Services', 'industry': 'Banks - Regional'}) == 'bank'
    assert _classify_risk_model(
        {'sector': 'Financial Services', 'industry': 'Banks - Diversified'}) == 'bank'

def test_classify_insurer_by_industry():
    assert _classify_risk_model(
        {'sector': 'Financial Services', 'industry': 'Insurance - Life'}) == 'insurer'

def test_classify_financial_sector_catch_all():
    assert _classify_risk_model(
        {'sector': 'Financial Services', 'industry': 'Asset Management'}) == 'financial'

def test_classify_asset_heavy_by_sector():
    for sector in ('Utilities', 'Real Estate', 'Energy', 'Basic Materials'):
        assert _classify_risk_model({'sector': sector, 'industry': 'x'}) == 'asset_heavy'

def test_classify_asset_heavy_by_telecom_industry():
    assert _classify_risk_model(
        {'sector': 'Communication Services', 'industry': 'Telecom Services'}) == 'asset_heavy'

def test_classify_asset_heavy_by_low_turnover():
    # Boku: Technology sector but merchant float inflates total assets
    row = {'sector': 'Technology', 'industry': 'Software - Infrastructure',
           'revenue': 128e6, 'total_assets': 501e6}
    assert _classify_risk_model(row) == 'asset_heavy'

def test_classify_general_when_turnover_healthy():
    row = {'sector': 'Technology', 'industry': 'Software - Application',
           'revenue': 400e6, 'total_assets': 500e6}
    assert _classify_risk_model(row) == 'general'

def test_classify_null_revenue_stays_general():
    # Pre-revenue biotech: turnover trigger must not fire on missing revenue
    row = {'sector': 'Healthcare', 'industry': 'Biotechnology',
           'revenue': None, 'total_assets': 100e6}
    assert _classify_risk_model(row) == 'general'


# ── _classify_model: the fund-name upgrade on the risk-score path ─────────────
# _attach_risk_score routes on _classify_model, not _classify_risk_model. Yahoo
# files most UK closed-end funds under Asset Management, so 108 of them used to
# run the asset-manager blend (vol 0.6 + ROE 0.4) — treating a NAV return as
# operating profitability — while the scrub and the value score already read
# them as trusts. The trust model is volatility-only.

_FUND = {'sector': 'Financial Services', 'industry': 'Asset Management'}


def test_classify_model_promotes_a_name_matched_fund():
    row = {**_FUND, 'name': 'Scottish Mortgage Ord'}
    assert _classify_risk_model(row) == 'financial'   # sector/industry alone
    assert _classify_model(row) == 'trust'            # + the name test


def test_classify_model_leaves_a_real_asset_manager_alone():
    row = {**_FUND, 'name': 'Liontrust Asset Management Plc'}
    assert _classify_model(row) == 'financial'


def test_classify_model_ignores_a_stored_risk_model():
    """_attach_risk_score computes the value that becomes risk_model, so its
    router must not read a stored one back — otherwise adding that column to
    the query would freeze whatever is already in screener_scores."""
    row = {**_FUND, 'name': 'Widgets plc', 'risk_model': 'trust'}
    assert _classify_model(row) == 'financial'
    assert effective_model(row) == 'trust'   # readers DO honour the stored value


def test_classify_model_needs_a_name_to_work():
    """The whole defect was a SELECT that omitted m.name — pin the dependency."""
    assert _classify_model({**_FUND}) == 'financial'


def test_classify_model_matches_classify_risk_model_off_the_fund_path():
    for row in ({'sector': 'Industrials', 'industry': 'Airlines',
                 'name': 'Some Trust plc'},          # name only counts for funds
                {'sector': 'Financial Services', 'industry': 'Banks—Regional',
                 'name': 'Big Trust Bank plc'},      # bank wins before financial
                {'sector': None, 'industry': None, 'name': 'Opaque'}):
        assert _classify_model(row) == _classify_risk_model(row)


# ── _altman_terms / _z_score ──────────────────────────────────────────────────

def test_altman_terms_none_when_total_assets_unusable():
    assert _altman_terms({'total_assets': None}) is None
    assert _altman_terms({'total_assets': 0}) is None

def test_altman_terms_uses_real_fields():
    row = {
        'total_assets': 4e9, 'working_capital': 4e8, 'retained_earnings': 1e9,
        'total_equity': 1.5e9, 'operating_income': 7.5e8, 'market_cap': 5e9,
        'revenue': 3e9,
    }
    t = _altman_terms(row)
    assert t['x1'] == pytest.approx(0.1)
    assert t['x2'] == pytest.approx(0.25)      # retained earnings, not equity
    assert t['x3'] == pytest.approx(0.1875)
    assert t['x4'] == pytest.approx(2.0)       # 5e9 / (4e9 - 1.5e9)
    assert t['x5'] == pytest.approx(0.75)

def test_altman_terms_x2_falls_back_to_equity():
    row = {'total_assets': 4e9, 'retained_earnings': None, 'total_equity': 1e9}
    assert _altman_terms(row)['x2'] == pytest.approx(0.25)

def test_altman_terms_skips_x4_when_equity_missing_or_exceeds_assets():
    assert 'x4' not in _altman_terms(
        {'total_assets': 4e9, 'market_cap': 5e9, 'total_equity': None, 'revenue': 1e9})
    assert 'x4' not in _altman_terms(
        {'total_assets': 4e9, 'market_cap': 5e9, 'total_equity': 5e9, 'revenue': 1e9})

def test_z_score_classic_weights():
    terms = {'x1': 0.1, 'x2': 0.25, 'x3': 0.1875, 'x4': 2.0, 'x5': 0.75}
    # 1.2*0.1 + 1.4*0.25 + 3.3*0.1875 + 0.6*2.0 + 1.0*0.75 = 3.03875
    assert _z_score(terms, _Z_WEIGHTS) == pytest.approx(3.039, abs=0.001)

def test_z_score_zdd_drops_x5():
    terms = {'x1': 0.1, 'x2': 0.25, 'x3': 0.1875, 'x4': 2.0, 'x5': 99.0}
    # 6.56*0.1 + 3.26*0.25 + 6.72*0.1875 + 1.05*2.0 = 4.831 — x5 ignored
    assert _z_score(terms, _ZDD_WEIGHTS) == pytest.approx(4.831, abs=0.001)

def test_z_score_none_when_no_terms():
    assert _z_score(None, _Z_WEIGHTS) is None
    assert _z_score({}, _Z_WEIGHTS) is None


# ── _z_to_risk / _zdd_to_risk ─────────────────────────────────────────────────

def test_z_to_risk_safe_zone():
    assert _z_to_risk(3.0) == 1
    assert _z_to_risk(5.0) == 1

def test_z_to_risk_distress_zone():
    assert _z_to_risk(1.0) == 10
    assert _z_to_risk(-1.0) == 10

def test_z_to_risk_midpoint():
    # z=2.0 → 1 + 0.5*9 = 5.5 → round → 6
    assert _z_to_risk(2.0) == 6

def test_z_to_risk_grey_zone_interpolation():
    # z=2.5 → 1 + 0.25*9 = 3.25 → round → 3
    assert _z_to_risk(2.5) == 3

def test_z_to_risk_none_input():
    assert _z_to_risk(None) is None

def test_zdd_to_risk_bands():
    assert _zdd_to_risk(2.6) == 1
    assert _zdd_to_risk(4.0) == 1
    assert _zdd_to_risk(1.1) == 10
    assert _zdd_to_risk(0.0) == 10
    assert _zdd_to_risk(None) is None


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
    import random
    random.seed(42)
    closes = [100.0]
    for _ in range(251):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.01)))
    result = _annualised_vol(closes)
    assert result > 0
    assert result < 2.0  # sanity bound — well under 200%

def test_annualised_vol_winsorises_gap_returns():
    # A 10x suspension/relisting gap must be capped at ±25% per day, not
    # dominate the whole series (FXPO printed 804% annualised pre-cap).
    closes = [100.0] * 100 + [1000.0] + [1000.0] * 100
    result = _annualised_vol(closes)
    # one capped 0.25 return over 200 days: std ≈ 0.0177 → ~28% annualised
    assert result < 0.5


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


# ── ROE helpers ───────────────────────────────────────────────────────────────

def test_roe_to_risk_strong_and_weak():
    assert _roe_to_risk(0.20) == 2   # >= 15% → strong
    assert _roe_to_risk(0.15) == 2
    assert _roe_to_risk(0.0) == 10   # <= 0 → weak
    assert _roe_to_risk(-0.05) == 10

def test_roe_to_risk_midpoint():
    # roe=0.075 → 2 + (0.15-0.075)*(8/0.15) = 2 + 4 = 6
    assert _roe_to_risk(0.075) == 6

def test_roe_to_risk_none():
    assert _roe_to_risk(None) is None

def test_roe_blend_averages_ttm_and_median():
    assert _roe_blend({'roe': 0.10, 'roe_median': 0.20}) == pytest.approx(0.15)

def test_roe_blend_falls_back_to_single_leg():
    assert _roe_blend({'roe': 0.10, 'roe_median': None}) == pytest.approx(0.10)
    assert _roe_blend({'roe': None, 'roe_median': 0.20}) == pytest.approx(0.20)
    assert _roe_blend({'roe': None, 'roe_median': None}) is None


# ── _debt_service_component ───────────────────────────────────────────────────

def test_debt_service_healthy():
    # coverage 10x → 1; genuine net cash (debt reported) → 1
    assert _debt_service_component(
        {'interest_coverage': 10.0, 'net_debt': -5e8, 'ebitda': 1e9,
         'st_debt': 1e8, 'lt_debt': 4e8}) == 1

def test_debt_service_negative_coverage_saturates():
    assert _debt_service_component(
        {'interest_coverage': -2.0, 'net_debt': -5e8, 'ebitda': 1e9,
         'st_debt': 1e8, 'lt_debt': 4e8}) == round((10 + 1) / 2)

def test_debt_service_nd_ebitda_leg():
    # coverage None, nd/ebitda = 4.5 → midpoint of [1, 8] → 6
    assert _debt_service_component(
        {'interest_coverage': None, 'net_debt': 4.5e9, 'ebitda': 1e9}) == 6

def test_debt_service_drops_nd_leg_when_ebitda_nonpositive():
    # negative EBITDA: only the coverage leg counts; 1x cover on the [6, 0.5]
    # band → 9
    assert _debt_service_component(
        {'interest_coverage': 1.0, 'net_debt': 5e8, 'ebitda': -1e8}) == 9

def test_debt_service_ignores_phantom_net_cash():
    # updater.py computes net_debt = -cash when yfinance misses the debt lines
    # (PHP: "net cash" at a real 48% LTV) — must not conclude safety from it
    assert _debt_service_component(
        {'interest_coverage': None, 'net_debt': -5e8, 'ebitda': 1e9,
         'st_debt': None, 'lt_debt': None}) is None

def test_debt_service_none_when_no_inputs():
    assert _debt_service_component(
        {'interest_coverage': None, 'net_debt': None, 'ebitda': None}) is None


# ── _attach_risk_score ────────────────────────────────────────────────────────

from unittest.mock import patch


def _fin_row(symbol, **kwargs):
    """A row as returned by the attacher's ttm + metadata bulk query."""
    defaults = {
        'company_symbol': symbol, 'sector': 'Consumer Cyclical',
        'industry': 'Specialty Retail',
        'market_cap': 5e9, 'price_to_book': 3.0, 'revenue': 3e9,
        'operating_income': 7.5e8, 'working_capital': 4e8,
        'retained_earnings': 1e9, 'total_equity': 1.5e9, 'total_assets': 4e9,
        'interest_coverage': 12.0, 'net_debt': 5e8, 'ebitda': 9e8,
        'st_debt': 2e8, 'lt_debt': 8e8, 'roe': 0.15, 'roe_median': 0.14,
    }
    defaults.update(kwargs)
    return defaults


def _prices(symbol, n=252, drift=0.05):
    return [{'symbol': symbol, 'close': 100.0 + i * drift} for i in range(n)]


def test_attach_risk_score_empty():
    from main import _attach_risk_score
    assert _attach_risk_score([]) == []


def test_attach_risk_score_attaches_fields():
    from main import _attach_risk_score
    results = [{'symbol': 'SHEL.L'}]

    with patch('main.query', side_effect=[[_fin_row('SHEL.L')], _prices('SHEL.L')]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_model'] == 'general'
    assert 1 <= r['risk_score'] <= 10
    assert r['altman_z'] is not None
    assert r['volatility_annualised'] is not None
    assert 'altman' in r['risk_components'] and 'volatility' in r['risk_components']


def test_attach_risk_score_bank_skips_altman():
    from main import _attach_risk_score
    results = [{'symbol': 'BARC.L'}]
    fin = _fin_row('BARC.L', sector='Financial Services',
                   industry='Banks - Diversified', total_assets=1.5e12,
                   total_equity=75e9, price_to_book=1.0, roe=0.09, roe_median=0.09)

    with patch('main.query', side_effect=[[fin], _prices('BARC.L')]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_model'] == 'bank'
    assert r['altman_z'] is None
    assert 1 <= r['risk_score'] <= 10
    assert {'roe', 'leverage', 'price_to_book'} <= set(r['risk_components'])


def test_attach_risk_score_trust_is_vol_only():
    from main import _attach_risk_score
    results = [{'symbol': 'ATT.L'}]
    fin = _fin_row('ATT.L', sector=None, industry=None)

    with patch('main.query', side_effect=[[fin], _prices('ATT.L')]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_model'] == 'trust'
    assert r['altman_z'] is None
    assert r['risk_score'] == r['risk_components']['volatility']


def test_attach_risk_score_asset_heavy_uses_zdd():
    from main import _attach_risk_score
    results = [{'symbol': 'BOKU.L'}]
    # Boku-shaped: Technology but turnover 0.26 → asset_heavy via the trigger
    fin = _fin_row('BOKU.L', sector='Technology',
                   industry='Software - Infrastructure',
                   market_cap=437e6, total_assets=501e6, working_capital=91e6,
                   retained_earnings=None, total_equity=153e6,
                   operating_income=21e6, revenue=129e6,
                   interest_coverage=65.5, net_debt=-194e6, ebitda=29e6)

    with patch('main.query', side_effect=[[fin], _prices('BOKU.L', drift=0.15)]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_model'] == 'asset_heavy'
    assert r['altman_z'] is not None          # holds Z'', not classic Z
    assert r['risk_components']['debt_service'] == 1
    assert r['risk_score'] <= 4


def test_attach_risk_score_null_when_no_data():
    from main import _attach_risk_score
    results = [{'symbol': 'SHEL.L'}]

    with patch('main.query', side_effect=[[], []]):
        _attach_risk_score(results)

    r = results[0]
    assert r['risk_score'] is None
    assert r['altman_z'] is None
    assert r['volatility_annualised'] is None
    assert r['risk_model'] == 'general'  # unknown ≠ trust


def test_attach_risk_score_vol_none_when_insufficient_history():
    from main import _attach_risk_score
    results = [{'symbol': 'SHEL.L'}]

    # Only 10 closes — below the 63-row threshold
    with patch('main.query', side_effect=[[_fin_row('SHEL.L')], _prices('SHEL.L', n=10, drift=1.0)]):
        _attach_risk_score(results)

    r = results[0]
    assert r['volatility_annualised'] is None
    # risk_score should still be set (from Altman alone)
    assert r['risk_score'] is not None


def test_attach_risk_score_clamps_extreme_z():
    from main import _attach_risk_score
    results = [{'symbol': 'EEE.L'}]
    # Tiny asset base vs huge market cap → raw Z in the hundreds
    fin = _fin_row('EEE.L', market_cap=1e9, total_assets=18e6,
                   total_equity=10e6, retained_earnings=None,
                   working_capital=2e6, operating_income=1e6, revenue=20e6)

    with patch('main.query', side_effect=[[fin], _prices('EEE.L')]):
        _attach_risk_score(results)

    assert results[0]['altman_z'] == 30.0


def test_screener_includes_risk_score(client):
    from unittest.mock import patch
    import main

    # momentum/piotroski/risk/altman_z/volatility are precomputed into
    # screener_scores and pulled in via a single JOIN (see compute_and_store_scores),
    # so the endpoint now makes ONE query() call and the score columns arrive already
    # attached to the row — no inline _attach_risk_score/_attach_momentum DB calls.
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
        # precomputed columns supplied by the screener_scores JOIN
        'momentum_score': 7, 'piotroski_score': 6, 'risk_score': 8,
        'risk_model': 'asset_heavy', 'altman_z': 3.2, 'volatility_annualised': 0.28,
    }

    main._screener_cache.clear()  # avoid a stale entry from another test
    try:
        with patch('main.query', return_value=[screener_row]):
            r = client.get('/api/screener')
    finally:
        main._screener_cache.clear()

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]['risk_score'] == 8
    assert data[0]['risk_model'] == 'asset_heavy'
    assert data[0]['altman_z'] == 3.2
    assert data[0]['volatility_annualised'] == 0.28


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

    # The MQVR fetch for the header factor strip (showcase._MQVR_SQL): momentum
    # comes stored, quality/value are computed from these columns.
    mqvr_row = {
        'symbol': 'SHEL.L', 'sector': 'Energy', 'industry': 'Oil & Gas',
        'market_cap': 5e9, 'revenue': 3e9, 'net_debt': 5e8, 'ebitda': 9e8,
        'price_to_earnings': 12.0, 'price_to_book': 3.0, 'price_to_sales': 1.0,
        'roe': 0.15, 'roic': 0.12,
        'gross_margin': 0.4, 'operating_margin': 0.25, 'net_income_margin': 0.17,
        'eps_cagr_10': 0.05, 'eps_diluted': 1.2, 'fcf_margin': 0.13,
        'dividends_per_share': 0.5, 'dividend_yield': 0.04,
        'period_end_price': 25.0, 'fcf': 4e8,
        'gross_margin_median': 0.38, 'operating_margin_median': 0.23,
        'net_margin_median': 0.15, 'roe_median': 0.14, 'roic_median': 0.11,
        'total_analysts': None, 'eps_growth_next_yr': None,
        'eps_est_current_yr': None, 'momentum_score': 7,
    }

    with patch('main.query', side_effect=[
        [snap_row],               # SELECT * FROM ttm_financials
        [_fin_row('SHEL.L')],     # _attach_risk_score fundamentals
        _prices('SHEL.L'),        # _attach_risk_score price_history
        [mqvr_row],               # _MQVR_SQL for the header factor strip
    ]):
        r = client.get('/api/snapshot?symbol=SHEL.L')

    assert r.status_code == 200
    data = r.json()
    assert 'risk_score' in data
    assert 'risk_model' in data
    assert 'altman_z' in data
    assert 'volatility_annualised' in data
    assert 'risk_components' in data
    assert data['momentum_score'] == 7
    assert isinstance(data['quality_score'], int)
    assert isinstance(data['value_score'], int)
