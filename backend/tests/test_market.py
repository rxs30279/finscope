import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

# ── helpers ───────────────────────────────────────────────────────────────────
def _fake_prices(tickers, rows=280):
    """Return a DataFrame of fake closing prices (random walk, positive)."""
    np.random.seed(42)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=rows)
    data = {}
    for t in tickers:
        prices = 100 * np.cumprod(1 + np.random.normal(0.0002, 0.01, rows))
        data[t] = prices
    return pd.DataFrame(data, index=dates)

def _patch_prices(fake_df):
    """Context manager: patch _get_prices to return fake_df."""
    import market
    return patch.object(market, "_get_prices", return_value=fake_df)


# ── sidebar tests ─────────────────────────────────────────────────────────────
def test_sidebar_returns_expected_keys(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/sidebar")
    assert r.status_code == 200
    data = r.json()
    assert "benchmarks" in data
    assert "sectors" in data
    assert "signal_summary" in data

def test_sidebar_benchmarks_have_pct_change(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/sidebar")
    benchmarks = r.json()["benchmarks"]
    assert len(benchmarks) == 3
    for b in benchmarks:
        assert "name" in b
        assert "pct_change" in b

def test_sidebar_sectors_all_present(client):
    from market import ALL_PROXY_TICKERS, SECTOR_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/sidebar")
    sector_names = [s["name"] for s in r.json()["sectors"]]
    for name in SECTOR_TICKERS:
        assert name in sector_names
