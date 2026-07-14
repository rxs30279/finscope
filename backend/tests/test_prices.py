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
    with patch('yfinance.download', return_value=_fake_yf_download(['SHEL.L'], None)) as mock_dl, \
         patch('prices.query') as mock_query, \
         patch('prices._upsert_rows', return_value=10) as mock_upsert, \
         patch('prices._update_activity', return_value=[]) as mock_activity:
        mock_query.side_effect = [
            # active symbols from company_metadata
            [{'symbol': 'SHEL.L'}],
            # latest dates from price_history (empty — no history yet)
            [],
            # earliest dates from price_history (empty — no history yet)
            [],
        ]
        r = client.post('/api/prices/refresh')
    assert r.status_code == 200
    data = r.json()
    assert 'rows_added' in data
    assert 'updated' in data
    assert 'duration_seconds' in data
    # delisted-symbol bookkeeping ran for the attempted universe
    mock_activity.assert_called_once()


def test_refresh_refetches_trailing_window(client):
    """Bulk refresh fetches from ~_REVISION_DAYS behind the latest stored bar
    (not the day after it) so Yahoo's post-close revisions overwrite the
    preliminary closes stored just after the close."""
    import prices
    from datetime import date as _date
    today = _date.today()
    with patch('prices._fetch_ohlcv', return_value=[]) as mock_fetch, \
         patch('prices.query') as mock_query, \
         patch('prices._upsert_rows', return_value=0), \
         patch('prices._update_activity', return_value=[]):
        mock_query.side_effect = [
            # active symbols
            [{'symbol': 'SHEL.L'}],
            # latest stored date — fully up to date
            [{'symbol': 'SHEL.L', 'latest': today}],
            # earliest stored date — 5Y+ present, no backfill group
            [{'symbol': 'SHEL.L', 'earliest': today - timedelta(days=6 * 365)}],
        ]
        r = client.post('/api/prices/refresh')
    assert r.status_code == 200
    mock_fetch.assert_called_once()
    called_start = mock_fetch.call_args[0][1]
    assert today - timedelta(days=prices._REVISION_DAYS) <= called_start <= today


def test_refresh_deactivates_persistently_empty_symbols():
    """A symbol that comes back empty crosses the threshold and is deactivated."""
    import prices
    # SHEL.L returned data; DEAD.L was attempted but came back empty.
    rows_returned = [
        # symbol seen empty for the (_DEACTIVATE_AFTER - 1)th time already
        ('DEAD.L', False),
    ]
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = rows_returned
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    fake_pool = MagicMock()
    fake_pool.getconn.return_value = fake_conn
    with patch('prices._get_pool', return_value=fake_pool):
        deactivated = prices._update_activity({'SHEL.L'}, {'DEAD.L'})
    assert deactivated == ['DEAD.L']
    fake_conn.commit.assert_called_once()


def test_update_activity_noop_when_nothing_to_record():
    import prices
    with patch('prices._get_pool') as mock_pool:
        result = prices._update_activity(set(), set())
    assert result == []
    mock_pool.assert_not_called()


# ── _fetch_ohlcv_batch parsing tests ──────────────────────────────────────────

def _single_ticker_multiindex(sym, vols):
    """Build the MultiIndex frame yfinance returns for a 1-element ticker list."""
    n = len(vols)
    dates = pd.bdate_range(end=pd.Timestamp('2026-06-01'), periods=n)
    df = pd.DataFrame(
        {
            ('Open', sym): [1.0] * n,
            ('High', sym): [2.0] * n,
            ('Low', sym): [0.5] * n,
            ('Close', sym): [1.5] * n,
            ('Volume', sym): vols,
        },
        index=dates,
    )
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def test_fetch_ohlcv_batch_single_ticker_multiindex():
    """A 1-element ticker list yields a MultiIndex; the parser must still emit
    rows. Regression: the old len==1 path assumed flat columns and returned []."""
    import prices
    from datetime import date as _date
    df = _single_ticker_multiindex('WISE.L', [10, 20, 30])
    with patch('yfinance.download', return_value=df):
        rows = prices._fetch_ohlcv_batch(['WISE.L'], _date(2026, 1, 1))
    assert len(rows) == 3
    assert all(len(r) == 7 and r[0] == 'WISE.L' for r in rows)
    assert rows[0][6] == 10  # volume preserved


def test_fetch_ohlcv_batch_handles_nan_volume():
    """A NaN volume must not crash int() (latent bug in the old paths)."""
    import prices
    from datetime import date as _date
    df = _single_ticker_multiindex('X.L', [np.nan, 5])
    with patch('yfinance.download', return_value=df):
        rows = prices._fetch_ohlcv_batch(['X.L'], _date(2026, 1, 1))
    assert len(rows) == 2
    assert rows[0][6] == 0  # NaN volume coerced to 0


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
        {'date': date(2024, 1, 2), 'open': 308.0, 'high': 312.0, 'low': 307.0,
         'close': 310.5, 'volume': 1234567},
        {'date': date(2024, 1, 3), 'open': 311.0, 'high': 316.0, 'low': 310.0,
         'close': 315.0, 'volume': 987654},
    ]
    with patch('prices.query', return_value=rows):
        r = client.get('/api/prices/SHEL.L')
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]['date'] == '2024-01-02'
    assert data[0]['close'] == 310.5
    assert data[0]['open'] == 308.0
    assert data[0]['high'] == 312.0
    assert data[0]['low'] == 307.0
    assert data[0]['volume'] == 1234567


def test_get_prices_404_when_no_data(client):
    with patch('prices.query', return_value=[]):
        r = client.get('/api/prices/UNKNOWN.L')
    assert r.status_code == 404


# ── POST /api/prices/refresh/{symbol} ────────────────────────────────────────

def test_refresh_symbol_up_to_date_refetches_revision_window(client):
    """A symbol with history through today still re-fetches the trailing
    revision window so post-close corrections to recent bars are picked up."""
    import prices
    from datetime import date as _date
    today = _date.today()
    # earliest old enough to skip backfill; latest=today so only the top-up runs
    with patch('prices.query',
               return_value=[{'earliest': _date(2018, 1, 1), 'latest': today}]), \
         patch('prices._fetch_ohlcv', return_value=[]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=0):
        r = client.post('/api/prices/refresh/SHEL.L')
    assert r.status_code == 200
    assert r.json() == {'rows_added': 0}
    mock_fetch.assert_called_once()
    called_start = mock_fetch.call_args[0][1]
    assert today - timedelta(days=prices._REVISION_DAYS) <= called_start <= today


def test_refresh_symbol_fetches_missing_rows(client):
    from datetime import date as _date
    stale_date = _date(2026, 4, 2)
    # earliest is old (5Y present) so only the top-up path runs — one fetch
    with patch('prices.query',
               return_value=[{'earliest': _date(2018, 1, 1), 'latest': stale_date}]), \
         patch('prices._fetch_ohlcv', return_value=[('SHEL.L', _date(2026, 4, 3), 1, 2, 0, 320.0, 5)]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=1) as mock_upsert:
        r = client.post('/api/prices/refresh/SHEL.L')
    assert r.status_code == 200
    assert r.json()['rows_added'] == 1
    mock_fetch.assert_called_once()
    mock_upsert.assert_called_once()


def test_refresh_symbol_no_history_uses_3yr_start(client):
    from datetime import date as _date
    with patch('prices.query', return_value=[{'earliest': None, 'latest': None}]), \
         patch('prices._fetch_ohlcv', return_value=[]) as mock_fetch, \
         patch('prices._upsert_rows', return_value=0):
        r = client.post('/api/prices/refresh/NEW.L')
    assert r.status_code == 200
    called_start = mock_fetch.call_args[0][1]
    assert (_date.today() - called_start).days >= 3 * 365 - 1
