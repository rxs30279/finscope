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


# ── rotation tests ────────────────────────────────────────────────────────────
def test_rotation_returns_11_sectors(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/rotation")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 11

def test_rotation_sector_has_required_fields(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/rotation")
    s = r.json()[0]
    for field in ["sector", "rank", "rs_score", "trend", "breadth", "signal", "pct_change"]:
        assert field in s, f"Missing field: {field}"

def test_rotation_signals_are_valid_values(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/rotation")
    for s in r.json():
        assert s["signal"] in ("BUY", "AVOID", "NEUTRAL")
        assert s["trend"] in ("rising", "falling", "unknown")


# ── breadth tests ─────────────────────────────────────────────────────────────
def test_breadth_returns_expected_keys(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/breadth")
    assert r.status_code == 200
    data = r.json()
    for key in ["pct_above_50ma", "advances", "declines", "unchanged",
                "new_highs", "new_lows", "hl_ratio", "ad_line"]:
        assert key in data, f"Missing key: {key}"

def test_breadth_ad_line_has_20_points(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/breadth")
    assert len(r.json()["ad_line"]) == 20

def test_breadth_pct_above_50ma_between_0_and_1(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/breadth")
    v = r.json()["pct_above_50ma"]
    if v is not None:
        assert 0.0 <= v <= 1.0


# ── cross-asset tests ─────────────────────────────────────────────────────────
def test_cross_asset_returns_expected_keys(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/cross-asset")
    assert r.status_code == 200
    data = r.json()
    for key in ["gbpusd", "gilt_10y", "brent", "gold", "vftse", "gilt_vs_utilities"]:
        assert key in data, f"Missing key: {key}"

def test_cross_asset_items_have_value_and_change(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/cross-asset")
    data = r.json()
    for key in ["gbpusd", "brent", "gold"]:
        item = data[key]
        assert "value" in item
        assert "pct_change" in item


# ── signals + cycle tests ─────────────────────────────────────────────────────
def test_signals_returns_list(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/signals")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

def test_signals_entries_have_required_fields(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/signals")
    for entry in r.json():
        for field in ["timestamp", "type", "message"]:
            assert field in entry

def test_cycle_get_returns_phase(client):
    r = client.get("/api/market/cycle")
    assert r.status_code == 200
    data = r.json()
    assert "phase" in data
    assert data["phase"] in ("Recovery", "Expansion", "Slowdown", "Contraction")

def test_cycle_post_updates_phase(client):
    r = client.post("/api/market/cycle", json={"phase": "Expansion"})
    assert r.status_code == 200
    r2 = client.get("/api/market/cycle")
    assert r2.json()["phase"] == "Expansion"
    # reset
    client.post("/api/market/cycle", json={"phase": "Recovery"})


# ── fear & greed helper tests ─────────────────────────────────────────────────
def test_zscore_to_score_midpoint():
    import market
    import pandas as pd
    series = pd.Series(range(100), dtype=float)
    # current value == mean → z = 0 → score = 50
    assert market._zscore_to_score(series, float(series.mean())) == 50

def test_zscore_to_score_high_value():
    import market
    import pandas as pd
    series = pd.Series(range(100), dtype=float)
    # very high value → z >> 2 → clipped → score = 100
    assert market._zscore_to_score(series, 9999.0) == 100

def test_zscore_to_score_low_value():
    import market
    import pandas as pd
    series = pd.Series(range(100), dtype=float)
    # very low value → z << -2 → clipped → score = 0
    assert market._zscore_to_score(series, -9999.0) == 0

def test_zscore_to_score_insufficient_data():
    import market
    import pandas as pd
    short = pd.Series([1.0, 2.0])
    assert market._zscore_to_score(short, 1.5) == 50

def test_zscore_to_score_constant_series():
    import market
    import pandas as pd
    constant = pd.Series([5.0] * 25)  # 25 identical values → std = 0
    assert market._zscore_to_score(constant, 5.0) == 50

def test_suggest_phase_unknown_trend():
    import market
    assert market._suggest_phase(30, "unknown") == "no_change"

def test_suggest_phase_neutral_zone():
    import market
    assert market._suggest_phase(50, "rising") == "no_change"
    assert market._suggest_phase(50, "falling") == "no_change"

def test_suggest_phase_low_falling():
    import market
    assert market._suggest_phase(20, "falling") == "Contraction"

def test_suggest_phase_low_rising():
    import market
    assert market._suggest_phase(20, "rising") == "Recovery"

def test_suggest_phase_high_rising():
    import market
    assert market._suggest_phase(70, "rising") == "Expansion"

def test_suggest_phase_high_falling():
    import market
    assert market._suggest_phase(70, "falling") == "Slowdown"


# ── fear & greed endpoint tests ───────────────────────────────────────────────
def test_fear_greed_compute_returns_expected_keys(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    assert r.status_code == 200
    data = r.json()
    for key in ["score", "sentiment", "trend", "suggested_phase", "confirmed", "components"]:
        assert key in data, f"Missing key: {key}"

def test_fear_greed_score_in_range(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    score = r.json()["score"]
    assert 0 <= score <= 100

def test_fear_greed_components_all_present(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    components = r.json()["components"]
    for key in ["momentum", "breadth", "vix", "safe_haven", "hl_ratio"]:
        assert key in components, f"Missing component: {key}"

def test_fear_greed_component_scores_in_range(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    for name, comp in r.json()["components"].items():
        assert 0 <= comp["score"] <= 100, f"{name} score out of range: {comp['score']}"

def test_fear_greed_sentiment_is_valid(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    assert r.json()["sentiment"] in (
        "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    )

def test_fear_greed_trend_is_valid(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    assert r.json()["trend"] in ("rising", "falling", "unknown")
