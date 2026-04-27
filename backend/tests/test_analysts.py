import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from analysts import _derive_consensus, _parse_snapshot


# ── _derive_consensus ──────────────────────────────────────────────────────────

def test_derive_consensus_buy_when_buy_pct_ge_60():
    consensus, buy_pct, total = _derive_consensus(10, 8, 3, 1, 0)
    # strong_buy=10 buy=8 → bullish=18, total=22 → buy_pct=81.8%
    assert consensus == 'Buy'
    assert total == 22
    assert buy_pct >= 60

def test_derive_consensus_sell_when_bearish_ge_40():
    consensus, buy_pct, total = _derive_consensus(1, 2, 2, 5, 5)
    # bearish=10/15=66.7%
    assert consensus == 'Sell'

def test_derive_consensus_hold_in_middle():
    consensus, buy_pct, total = _derive_consensus(2, 4, 8, 2, 0)
    # buy_pct=37.5%, sell_pct=12.5%
    assert consensus == 'Hold'

def test_derive_consensus_none_when_no_analysts():
    consensus, buy_pct, total = _derive_consensus(0, 0, 0, 0, 0)
    assert consensus is None
    assert buy_pct is None
    assert total is None

def test_derive_consensus_none_inputs_treated_as_zero():
    consensus, buy_pct, total = _derive_consensus(None, None, None, None, None)
    assert consensus is None
    assert total is None


# ── _parse_snapshot ────────────────────────────────────────────────────────────

def _make_recs(sb=6, b=11, h=4, s=1, ss=0):
    return pd.DataFrame([{
        'period': '0m', 'strongBuy': sb, 'buy': b,
        'hold': h, 'sell': s, 'strongSell': ss
    }])

def _make_targets(mean=1600, high=2000, low=1200, median=1650, current=1400):
    return {'mean': mean, 'high': high, 'low': low, 'median': median, 'current': current}

def _make_earnings_est():
    return pd.DataFrame({
        'avg':  [1.5, 1.8, 6.2, 7.1]
    }, index=pd.Index(['0q', '+1q', '0y', '+1y'], name='period'))

def _make_rev_est():
    return pd.DataFrame({
        'avg': [5e9, 5.5e9]
    }, index=pd.Index(['0y', '+1y'], name='period'))

def _make_eps_rev():
    return pd.DataFrame({
        'upLast7days': [2, 1, 0, 0],
        'upLast30days': [4, 3, 2, 1],
        'downLast30days': [1, 2, 3, 2],
        'downLast7Days': [0, 0, 1, 0],
    }, index=pd.Index(['0q', '+1q', '0y', '+1y'], name='period'))

def _make_growth():
    return pd.DataFrame({
        'stockTrend': [0.12, 0.10, 0.15, 0.09]
    }, index=pd.Index(['0q', '+1q', '0y', '+1y'], name='period'))

def test_parse_snapshot_consensus_fields():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['symbol'] == 'AZN.L'
    assert row['strong_buy'] == 6
    assert row['buy'] == 11
    assert row['total_analysts'] == 22
    assert row['consensus'] == 'Buy'        # (6+11)/22 = 77% ≥ 60%
    assert row['buy_pct'] == 77.3

def test_parse_snapshot_price_targets():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['price_target_mean'] == 1600
    assert row['current_price'] == 1400
    assert row['upside_pct'] == round((1600 - 1400) / 1400 * 100, 1)

def test_parse_snapshot_eps_estimates():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['eps_est_current_q']  == 1.5
    assert row['eps_est_next_q']     == 1.8
    assert row['eps_est_current_yr'] == 6.2
    assert row['eps_est_next_yr']    == 7.1

def test_parse_snapshot_revisions():
    row = _parse_snapshot('AZN.L', _make_recs(), _make_targets(),
                          _make_earnings_est(), _make_rev_est(),
                          _make_eps_rev(), _make_growth())
    assert row['revisions_up_30d']   == 4
    assert row['revisions_down_30d'] == 1
    assert row['revision_score']     == 3   # 4 - 1

def test_parse_snapshot_none_recs_gives_null_consensus():
    row = _parse_snapshot('AZN.L', None, None, None, None, None, None)
    assert row['consensus'] is None
    assert row['total_analysts'] is None
    assert row['upside_pct'] is None


# ── API endpoint tests ─────────────────────────────────────────────────────────
# conftest.py already provides `client` via TestClient(app)

def test_get_analyst_history_returns_list(client):
    rows = [
        {'symbol': 'AZN.L', 'snapshot_date': '2026-04-01', 'consensus': 'Buy', 'buy_pct': 77.3},
        {'symbol': 'AZN.L', 'snapshot_date': '2026-04-02', 'consensus': 'Buy', 'buy_pct': 79.0},
    ]
    with patch('analysts._query', return_value=rows):
        r = client.get('/api/analysts/AZN.L')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]['consensus'] == 'Buy'

def test_get_analyst_history_404_when_no_data(client):
    with patch('analysts._query', return_value=[]):
        r = client.get('/api/analysts/UNKNOWN.L')
    assert r.status_code == 404

def test_get_analyst_latest_returns_list(client):
    rows = [
        {'symbol': 'AZN.L', 'snapshot_date': '2026-04-07', 'consensus': 'Buy',  'buy_pct': 77.3},
        {'symbol': 'SHEL.L','snapshot_date': '2026-04-07', 'consensus': 'Hold', 'buy_pct': 45.0},
    ]
    with patch('analysts._query', return_value=rows):
        r = client.get('/api/analysts/latest')
    assert r.status_code == 200
    assert len(r.json()) == 2

def test_get_analyst_changes_returns_list(client):
    rows = [
        {'symbol': 'AZN.L', 'prev_consensus': 'Hold', 'consensus': 'Buy',
         'prev_upside': 5.0, 'upside_pct': 22.0, 'snapshot_date': '2026-04-07'}
    ]
    with patch('analysts._query', return_value=rows):
        r = client.get('/api/analysts/changes')
    assert r.status_code == 200
    assert r.json()[0]['symbol'] == 'AZN.L'

def test_refresh_endpoint_dispatches_workflow(client):
    with patch('analysts.gh_actions.dispatch', return_value='2026-04-27T07:00:00Z') as mock_dispatch:
        r = client.post('/api/analysts/refresh')
    assert r.status_code == 200
    assert r.json() == {'status': 'dispatched', 'dispatched_at': '2026-04-27T07:00:00Z'}
    mock_dispatch.assert_called_once_with('refresh-analysts.yml')


# ── Screener analyst integration ───────────────────────────────────────────────

def test_screener_includes_analyst_columns(client):
    screener_row = {
        'symbol': 'AZN.L', 'name': 'AstraZeneca', 'sector': 'Health Care',
        'country': 'GB', 'exchange': 'LSE', 'ftse_index': 'FTSE 100',
        'financial_currency': 'GBP', 'market_cap': 200e9, 'revenue': 40e9,
        'net_income': 5e9, 'price_to_earnings': 18.0, 'price_to_book': 4.0,
        'price_to_sales': 3.0, 'roe': 0.25, 'roa': 0.08, 'roic': 0.12,
        'roce': 0.15, 'gross_margin': 0.72, 'operating_margin': 0.28,
        'net_income_margin': 0.14, 'revenue_growth': 0.10, 'eps_diluted_growth': 0.12,
        'fcf_growth': 0.08, 'debt_to_equity': 0.8, 'current_ratio': 1.5,
        'fcf': 6e9, 'ebitda': 10e9, 'revenue_cagr_10': 0.07, 'eps_cagr_10': 0.09,
        'period_end_date': '2025-12-31', 'fcf_margin': 0.15,
        'gross_margin_median': 0.70, 'operating_margin_median': 0.26,
        'net_margin_median': 0.13, 'roe_median': 0.22, 'roic_median': 0.11,
        # analyst fields joined from analyst_snapshots
        'consensus': 'Buy', 'buy_pct': 77.3, 'upside_pct': 14.3,
        'total_analysts': 22, 'revision_score': 3,
    }
    with patch('main.query', return_value=[screener_row]), \
         patch('prices._attach_momentum', side_effect=lambda r: r), \
         patch('main._attach_piotroski', side_effect=lambda r: r), \
         patch('main._attach_risk_score', side_effect=lambda r: r):
        r = client.get('/api/screener')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]['consensus'] == 'Buy'
    assert data[0]['upside_pct'] == 14.3

def test_screener_filter_by_consensus(client):
    with patch('main.query', return_value=[]) as mock_q, \
         patch('prices._attach_momentum', side_effect=lambda r: r), \
         patch('main._attach_piotroski', side_effect=lambda r: r), \
         patch('main._attach_risk_score', side_effect=lambda r: r):
        r = client.get('/api/screener?consensus=Buy')
    assert r.status_code == 200
    # Verify the SQL was called with consensus filter param
    call_args = mock_q.call_args
    assert 'Buy' in call_args[0][1]   # params tuple contains 'Buy'
