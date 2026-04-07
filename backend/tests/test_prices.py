import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from datetime import date, timedelta


# ── helpers ───────────────────────────────────────────────────────────────────

def _fake_yf_download(symbols, start, rows=300):
    """Return a fake yfinance download DataFrame."""
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=rows)
    np.random.seed(42)
    if len(symbols) == 1:
        prices = 100 * np.cumprod(1 + np.random.normal(0.0002, 0.01, rows))
        df = pd.DataFrame({'Close': prices}, index=dates)
    else:
        close_data = {}
        for sym in symbols:
            prices = 100 * np.cumprod(1 + np.random.normal(0.0002, 0.01, rows))
            close_data[sym] = prices
        df = pd.DataFrame(close_data, index=dates)
        df.columns = pd.MultiIndex.from_product([['Close'], df.columns])
    return df


# ── refresh endpoint tests ────────────────────────────────────────────────────

def test_refresh_returns_summary(client):
    with patch('prices.yf.download', return_value=_fake_yf_download(['SHEL.L'], None)) as mock_dl, \
         patch('prices.query') as mock_query, \
         patch('prices._upsert_rows', return_value=10) as mock_upsert:
        mock_query.side_effect = [
            # all symbols from company_metadata
            [{'symbol': 'SHEL.L'}],
            # latest dates from price_history (empty — no history yet)
            [],
        ]
        r = client.post('/api/prices/refresh')
    assert r.status_code == 200
    data = r.json()
    assert 'rows_added' in data
    assert 'updated' in data
    assert 'duration_seconds' in data


# ── _attach_momentum tests ────────────────────────────────────────────────────

def test_attach_momentum_scores_range():
    import prices
    results = [{'symbol': f'S{i}.L'} for i in range(10)]
    mock_rows = [
        {'symbol': f'S{i}.L', 'close_63': 110 + i, 'close_252': 100.0}
        for i in range(10)
    ]
    with patch('prices.query', return_value=mock_rows):
        prices._attach_momentum(results)
    scores = [r['momentum_score'] for r in results if r['momentum_score'] is not None]
    assert all(1 <= s <= 10 for s in scores)


def test_attach_momentum_null_for_insufficient_history():
    import prices
    results = [{'symbol': 'SHEL.L'}]
    # No rows returned — stock has < 252 days of history
    with patch('prices.query', return_value=[]):
        prices._attach_momentum(results)
    assert results[0]['momentum_score'] is None


def test_attach_momentum_empty_results():
    import prices
    result = prices._attach_momentum([])
    assert result == []


# ── GET /api/prices/{symbol} ──────────────────────────────────────────────────

def test_get_prices_returns_list(client):
    rows = [
        {'date': date(2024, 1, 2), 'close': 310.5},
        {'date': date(2024, 1, 3), 'close': 315.0},
    ]
    with patch('prices.query', return_value=rows):
        r = client.get('/api/prices/SHEL.L')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]['date'] == '2024-01-02'
    assert data[0]['close'] == 310.5


def test_get_prices_404_when_no_data(client):
    with patch('prices.query', return_value=[]):
        r = client.get('/api/prices/UNKNOWN.L')
    assert r.status_code == 404


# ── POST /api/prices/refresh/{symbol} ────────────────────────────────────────

def test_refresh_symbol_already_up_to_date(client):
    from datetime import date as _date
    today = _date.today()
    yesterday = today - timedelta(days=1)
    with patch('prices.query', return_value=[{'latest': yesterday}]):
        r = client.post('/api/prices/refresh/SHEL.L')
    assert r.status_code == 200
    assert r.json() == {'rows_added': 0}


def test_refresh_symbol_fetches_missing_rows(client):
    from datetime import date as _date
    stale_date = _date(2026, 4, 2)
    with patch('prices.query', return_value=[{'latest': stale_date}]), \
         patch('prices._fetch_closes', return_value=[('SHEL.L', _date(2026, 4, 3), 320.0)]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=1) as mock_upsert:
        r = client.post('/api/prices/refresh/SHEL.L')
    assert r.status_code == 200
    assert r.json()['rows_added'] == 1
    mock_fetch.assert_called_once()
    mock_upsert.assert_called_once()


def test_refresh_symbol_no_history_uses_3yr_start(client):
    from datetime import date as _date
    with patch('prices.query', return_value=[{'latest': None}]), \
         patch('prices._fetch_closes', return_value=[]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=0):
        r = client.post('/api/prices/refresh/NEW.L')
    assert r.status_code == 200
    called_start = mock_fetch.call_args[0][1]
    assert (_date.today() - called_start).days >= 3 * 365 - 1
