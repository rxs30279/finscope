import pytest
import pandas as pd
import numpy as np
from contextlib import ExitStack
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
    """Context manager: patch the price feeds — the shared 1-year _get_prices, the
    sidebar-only live frame (_get_sidebar_prices, used by the sidebar endpoint for
    benchmarks/sectors/VIX) and the 2-year F&G feed (_get_fg_prices_2y, which the
    Fear & Greed calc now combines in) — to return fake_df, so the calcs stay
    hermetic and never hit the network."""
    import market
    stack = ExitStack()
    stack.enter_context(patch.object(market, "_get_prices", return_value=fake_df))
    stack.enter_context(patch.object(market, "_get_sidebar_prices", return_value=fake_df))
    stack.enter_context(patch.object(market, "_get_fg_prices_2y", return_value=fake_df))
    return stack


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
    assert "fear_greed" in data

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

def test_sidebar_includes_fear_greed(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/sidebar")
    data = r.json()
    assert "fear_greed" in data, "sidebar missing fear_greed key"
    fg = data["fear_greed"]
    assert "score" in fg
    assert "sentiment" in fg
    assert "trend" in fg
def test_sidebar_benchmarks_use_live_current_bar(client):
    """Benchmarks are LIVE: the % change reflects the current-day (last) bar
    against the previous close, not a session-trimmed value. Plant a known move
    on the final row and assert it comes straight through."""
    import market
    from market import ALL_PROXY_TICKERS, BENCHMARK_TICKERS

    fake = _fake_prices(ALL_PROXY_TICKERS)
    ftse = BENCHMARK_TICKERS["FTSE 100"]
    last_date = fake.index[-1]
    # A clean +2% on the live current-day bar.
    fake.loc[last_date, ftse] = float(fake[ftse].iloc[-2]) * 1.02

    market._cache.clear()
    with _patch_prices(fake):
        r = client.get("/api/market/sidebar")
    market._cache.clear()
    bm = {b["name"]: b["pct_change"] for b in r.json()["benchmarks"]}
    assert bm["FTSE 100"] == pytest.approx(0.02, abs=1e-9)


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
    for key in ["gbpusd", "brent", "gold", "gilt_vs_utilities"]:
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


# ── day-change helper tests ───────────────────────────────────────────────────
def _frame(**cols):
    """Price frame over 4 consecutive sessions; None marks a missing bar."""
    idx = pd.to_datetime(["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"])
    return pd.DataFrame(cols, index=idx)


def test_pct_change_today_normal_series():
    import market
    prices = _frame(**{"^FTSE": [100.0, 101.0, 100.0, 102.0]})
    assert market._pct_change_today(prices, "^FTSE") == pytest.approx(0.02)


def test_pct_change_today_none_when_previous_bar_missing():
    import market
    # The ^FTAS July-2026 outage: Yahoo kept quoting the index but stopped printing
    # daily bars, so the last two *valid* points straddled a 3-session gap. Pairing
    # them rendered a multi-session return as "today's move" (+2.6% vs a real
    # -0.06%). A gap must yield None, not a plausible-looking wrong number.
    prices = _frame(**{"^FTAS": [100.0, None, None, 102.0]})
    assert market._pct_change_today(prices, "^FTAS") is None


def test_pct_change_today_none_when_todays_bar_missing():
    import market
    # Stale feed: the ticker stopped printing entirely. Its last two bars are
    # adjacent, but they are not the current session — that is yesterday's move.
    prices = _frame(**{"SHEL.L": [100.0, 101.0, 102.0, None]})
    assert market._pct_change_today(prices, "SHEL.L") is None


def test_basket_pct_change_skips_gappy_members():
    import market
    # One healthy member (+2%), one gappy member that must not contribute.
    prices = _frame(
        **{"AAA.L": [100.0, 101.0, 100.0, 102.0], "BBB.L": [100.0, None, None, 150.0]}
    )
    assert market._basket_pct_change(prices, ["AAA.L", "BBB.L"]) == pytest.approx(0.02)


# ── gilt yield helper tests ───────────────────────────────────────────────────
def test_value_at_or_before_exact_hit():
    import market
    rows = {"2026-07-06": 4.0, "2026-07-13": 4.2}
    assert market._value_at_or_before(rows, "2026-07-13") == ("2026-07-13", 4.2)

def test_value_at_or_before_snaps_back_over_weekend():
    import market
    # Fri 07-10 is the latest business day before a Sat 07-11 target.
    rows = {"2026-07-10": 4.1, "2026-07-13": 4.3}
    assert market._value_at_or_before(rows, "2026-07-11") == ("2026-07-10", 4.1)

def test_value_at_or_before_target_before_first_date():
    import market
    rows = {"2026-07-10": 4.1}
    assert market._value_at_or_before(rows, "2026-07-01") is None

def test_value_at_or_before_empty_dict():
    import market
    assert market._value_at_or_before({}, "2026-07-13") is None


def _boundary_at(dt):
    """Evaluate _gilt_daily_boundary() with market.datetime.now() pinned to dt
    (mirrors the _eod_cutoff tests: patch the whole datetime name in market)."""
    import market
    with patch.object(market, "datetime") as mdt:
        mdt.now.return_value = dt
        return market._gilt_daily_boundary()

def test_gilt_boundary_none_before_publication():
    from datetime import datetime as real_dt
    # 11:30 Mon — before the 12:30 fetch boundary → hold, nothing due.
    assert _boundary_at(real_dt(2026, 7, 13, 11, 30)) is None

def test_gilt_boundary_none_on_weekend():
    from datetime import datetime as real_dt
    # Sat afternoon — BoE doesn't publish → never refresh.
    assert _boundary_at(real_dt(2026, 7, 11, 14, 0)) is None

def test_gilt_boundary_after_publication():
    from datetime import datetime as real_dt
    # 12:30 Mon exactly → today's 12:30 boundary is due.
    assert _boundary_at(real_dt(2026, 7, 13, 12, 30)) == real_dt(2026, 7, 13, 12, 30).timestamp()

def test_gilt_boundary_evening_still_todays_boundary():
    from datetime import datetime as real_dt
    # 22:00 Mon → still today's 12:30 boundary (a warm entry from before noon is
    # due exactly one catch-up refresh; one from the afternoon is already fresh).
    assert _boundary_at(real_dt(2026, 7, 13, 22, 0)) == real_dt(2026, 7, 13, 12, 30).timestamp()


# ── signals tests ─────────────────────────────────────────────────────────────
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

# ── EOD cutoff tests (Fear & Greed uses last completed session, not intraday) ──
def test_eod_cutoff_excludes_today_during_session():
    import market
    from datetime import datetime as real_dt
    fixed = real_dt(2026, 6, 10, 11, 0)  # 11:00 London, session in progress
    with patch.object(market, "datetime") as mdt:
        mdt.now.return_value = fixed
        cutoff = market._eod_cutoff()
    # Today's partial bar is excluded → cutoff is today's date (exclusive bound).
    assert cutoff == pd.Timestamp("2026-06-10")

def test_eod_cutoff_none_after_close():
    import market
    from datetime import datetime as real_dt
    fixed = real_dt(2026, 6, 10, 18, 0)  # 18:00 London, EOD settled
    with patch.object(market, "datetime") as mdt:
        mdt.now.return_value = fixed
        # Nothing to trim once the session has closed — today's bar is real EOD.
        assert market._eod_cutoff() is None


# ── fear & greed endpoint tests ───────────────────────────────────────────────
def test_fear_greed_compute_returns_expected_keys(client):
    from market import ALL_PROXY_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS)
    with _patch_prices(fake):
        r = client.get("/api/market/fear-greed")
    assert r.status_code == 200
    data = r.json()
    for key in ["score", "sentiment", "trend", "components", "as_of"]:
        assert key in data, f"Missing key: {key}"
    # as_of is the date of the latest bar the (live) reading was built from.
    assert data["as_of"] is None or isinstance(data["as_of"], str)

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
    for key in ["momentum", "breadth", "currency", "safe_haven", "hl_ratio"]:
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

def test_fear_greed_not_held_back_by_lagging_ftse_long(client):
    """The dedicated 2-year ^FTSE feed (_get_ftse_long) sometimes trails the shared
    feed by a session (a Yahoo period quirk). The headline must still anchor its date
    stamp to the shared feed, not freeze on the stale long-feed session."""
    import market
    from market import ALL_PROXY_TICKERS, BENCHMARK_TICKERS
    fake = _fake_prices(ALL_PROXY_TICKERS, rows=300)
    latest = fake.index.max().strftime("%Y-%m-%d")
    # ftse_long stops one session short of the shared feed.
    ftse_long_lagged = fake[BENCHMARK_TICKERS["FTSE 100"]].iloc[:-1]
    market._cache.pop("fear_greed", None)  # endpoint memoizes; don't read a prior test's value
    with _patch_prices(fake), \
         patch.object(market, "_get_ftse_long", return_value=ftse_long_lagged):
        r = client.get("/api/market/fear-greed")
    assert r.json()["as_of"] == latest, "headline stamp froze on the stale long-feed session"
