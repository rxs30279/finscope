# Market Tools Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add momentum/breadth/cross-asset analysis tools to the existing UK stock screener as five new tabs with a persistent sidebar.

**Architecture:** The FastAPI backend gains a new `market.py` module with six endpoint groups that fetch and compute metrics from Yahoo Finance (via `yfinance`), with a 15-minute in-memory cache. The React frontend gains a persistent `Sidebar` component and four new tab components (`RotationTab`, `BreadthTab`, `CrossAssetTab`, `SignalsTab`), wired into the existing `App.js` shell.

**Tech Stack:** Python 3.11, FastAPI, yfinance, pytest, React 18, Recharts, inline styles (existing pattern)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/requirements.txt` | Modify | Add yfinance |
| `backend/market.py` | Create | All market data endpoints + cache + yfinance logic |
| `backend/main.py` | Modify | Mount market router |
| `backend/tests/__init__.py` | Create | Test package marker |
| `backend/tests/conftest.py` | Create | FastAPI TestClient fixture |
| `backend/tests/test_market.py` | Create | Tests for all market endpoints |
| `frontend/src/utils.js` | Create | Shared `fmt`, `gc`, `API` constants |
| `frontend/src/App.js` | Modify | Tab nav, sidebar layout, import new tabs |
| `frontend/src/components/Sidebar.js` | Create | Persistent sidebar (benchmarks, sectors, signal summary) |
| `frontend/src/components/RotationTab.js` | Create | Sector heatmap + cycle wheel + RS table |
| `frontend/src/components/BreadthTab.js` | Create | Breadth gauge + highs/lows + A/D chart |
| `frontend/src/components/CrossAssetTab.js` | Create | 6 cross-asset KPI cards |
| `frontend/src/components/SignalsTab.js` | Create | Timestamped signal event feed |
| `.gitignore` | Modify | Add `.superpowers/` |

---

### Task 1: Backend foundation — yfinance, cache, router skeleton

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/market.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Add yfinance to requirements**

Edit `backend/requirements.txt` to:
```
fastapi
uvicorn
psycopg2-binary
python-dotenv
yfinance
```

- [ ] **Step 2: Install yfinance**

```bash
cd backend && pip install yfinance
```

Expected: `Successfully installed yfinance-...`

- [ ] **Step 3: Create backend/market.py with cache, ticker constants, and empty router**

```python
from fastapi import APIRouter
import yfinance as yf
import time
import numpy as np
from datetime import datetime

router = APIRouter(prefix="/api/market", tags=["market"])

# ── In-memory cache (key → (data, timestamp)) ─────────────────────────────────
_cache: dict = {}
CACHE_TTL = 900  # 15 minutes

def _cached(key: str, fn):
    now = time.time()
    if key in _cache and now - _cache[key][1] < CACHE_TTL:
        return _cache[key][0]
    data = fn()
    _cache[key] = (data, now)
    return data

# ── Ticker constants ───────────────────────────────────────────────────────────
BENCHMARK_TICKERS = {
    "FTSE 100":  "^FTSE",
    "FTSE 250":  "^FT2MI",
    "All-Share":  "^VUKE",
}

# 2 representative stocks per ICB sector — basket average used as sector proxy
SECTOR_TICKERS = {
    "Energy":                 ["SHEL.L", "BP.L"],
    "Financials":             ["HSBA.L", "LLOY.L"],
    "Industrials":            ["RR.L",   "BAE.L"],
    "Materials":              ["RIO.L",  "AAL.L"],
    "Consumer Discretionary": ["TSCO.L", "MKS.L"],
    "Consumer Staples":       ["ULVR.L", "DGE.L"],
    "Health Care":            ["AZN.L",  "GSK.L"],
    "Technology":             ["SAGE.L", "AUTO.L"],
    "Telecommunications":     ["VOD.L",  "BT-A.L"],
    "Utilities":              ["NG.L",   "SSE.L"],
    "Real Estate":            ["LAND.L", "SGRO.L"],
}

CROSS_ASSET_TICKERS = {
    "gbpusd":   "GBPUSD=X",
    "gilt_10y": "^TNGBP",   # UK 10Y gilt — validate ticker on first run
    "brent":    "BZ=F",
    "gold":     "GC=F",
    "vftse":    "^VFTSE",
}

ALL_PROXY_TICKERS = (
    list(BENCHMARK_TICKERS.values()) +
    [t for tickers in SECTOR_TICKERS.values() for t in tickers] +
    list(CROSS_ASSET_TICKERS.values())
)

# ── Shared price fetch (all proxy tickers, 1 year history, cached) ────────────
def _get_prices():
    def fetch():
        df = yf.download(
            ALL_PROXY_TICKERS, period="1y",
            progress=False, auto_adjust=True, threads=True
        )["Close"]
        # yf.download returns MultiIndex columns when multiple tickers;
        # single ticker returns a Series — normalise to DataFrame
        if hasattr(df, "columns") and not isinstance(df.columns, str):
            return df
        return df.to_frame()
    return _cached("prices", fetch)

# ── Cycle phase state (in-memory, manually set) ───────────────────────────────
_cycle = {
    "phase": "Recovery",
    "set_at": datetime.now().isoformat(),
}

PHASE_GUIDANCE = {
    "Recovery":    {"favour": ["Energy", "Financials", "Materials", "Industrials"],
                    "avoid":  ["Utilities", "Consumer Staples"]},
    "Expansion":   {"favour": ["Technology", "Consumer Discretionary", "Industrials"],
                    "avoid":  ["Health Care", "Utilities"]},
    "Slowdown":    {"favour": ["Health Care", "Consumer Staples", "Utilities"],
                    "avoid":  ["Energy", "Materials", "Financials"]},
    "Contraction": {"favour": ["Utilities", "Consumer Staples", "Health Care"],
                    "avoid":  ["Energy", "Financials", "Technology"]},
}

# ── In-memory signal log ──────────────────────────────────────────────────────
_signal_log: list = []
```

- [ ] **Step 4: Create tests/__init__.py and conftest.py**

```python
# backend/tests/__init__.py
# (empty)
```

```python
# backend/tests/conftest.py
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(app)
```

- [ ] **Step 5: Commit**

```bash
cd backend && git add requirements.txt market.py tests/__init__.py tests/conftest.py
git commit -m "feat: add market.py skeleton, cache utility, ticker constants"
```

---

### Task 2: Mount market router in main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add router import and mount to main.py**

Add after the existing imports at the top of `main.py`:
```python
from market import router as market_router
```

Add after `app.add_middleware(...)`:
```python
app.include_router(market_router)
```

- [ ] **Step 2: Verify router mounts without error**

```bash
cd backend && python -c "from main import app; print([r.path for r in app.routes])"
```

Expected output includes: `/api/market/...` paths (even if empty for now — just no ImportError).

- [ ] **Step 3: Commit**

```bash
cd backend && git add main.py && git commit -m "feat: mount market router in FastAPI app"
```

---

### Task 3: Sidebar API endpoint

**Files:**
- Modify: `backend/market.py`
- Modify: `backend/tests/test_market.py`

The sidebar endpoint computes today's % change for each benchmark and sector proxy basket, plus a model signal summary.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_market.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && pytest tests/test_market.py -v
```

Expected: `FAILED` — endpoint not yet implemented.

- [ ] **Step 3: Implement /api/market/sidebar in market.py**

Add to `backend/market.py`:
```python
def _pct_change_today(prices, ticker):
    """Return today's % change for a single ticker. Returns None if insufficient data."""
    if ticker not in prices.columns:
        return None
    col = prices[ticker].dropna()
    if len(col) < 2:
        return None
    return float((col.iloc[-1] / col.iloc[-2]) - 1)

def _basket_pct_change(prices, tickers):
    """Average % change across a basket of tickers (ignores missing)."""
    changes = [_pct_change_today(prices, t) for t in tickers]
    valid = [c for c in changes if c is not None]
    return float(np.mean(valid)) if valid else None

def _compute_rs_score(prices, sector_tickers, benchmark_ticker, window=63):
    """RS score = basket 63-day return / benchmark 63-day return."""
    basket_prices = [
        prices[t].dropna() for t in sector_tickers if t in prices.columns
    ]
    if not basket_prices:
        return None
    min_len = min(len(p) for p in basket_prices)
    if min_len < window + 1:
        return None
    basket_ret = float(np.mean([
        (p.iloc[-1] / p.iloc[-(window + 1)]) - 1 for p in basket_prices
    ]))
    if benchmark_ticker not in prices.columns:
        return None
    bm = prices[benchmark_ticker].dropna()
    if len(bm) < window + 1:
        return None
    bm_ret = float((bm.iloc[-1] / bm.iloc[-(window + 1)]) - 1)
    if bm_ret == 0:
        return None
    return round((1 + basket_ret) / (1 + bm_ret), 4)

def _compute_rotation():
    """Compute RS scores + signals for all sectors. Returns list of dicts."""
    prices = _get_prices()
    bm_ticker = BENCHMARK_TICKERS["All-Share"]
    results = []
    for sector, tickers in SECTOR_TICKERS.items():
        rs_now = _compute_rs_score(prices, tickers, bm_ticker, window=63)
        rs_prior = _compute_rs_score(prices, tickers, bm_ticker, window=73)  # 10 days ago
        if rs_now is None or rs_prior is None:
            trend = "unknown"
            signal = "NEUTRAL"
        else:
            trend = "rising" if rs_now > rs_prior else "falling"
            if rs_now > 1.05 and trend == "rising":
                signal = "BUY"
            elif rs_now < 0.95 and trend == "falling":
                signal = "AVOID"
            else:
                signal = "NEUTRAL"

        # Breadth: % of basket stocks above their 50-day MA
        above = 0
        total = 0
        for t in tickers:
            if t not in prices.columns:
                continue
            col = prices[t].dropna()
            if len(col) < 51:
                continue
            ma50 = float(col.iloc[-51:-1].mean())
            total += 1
            if float(col.iloc[-1]) > ma50:
                above += 1
        breadth = round(above / total, 4) if total else None

        results.append({
            "sector": sector,
            "rs_score": rs_now,
            "trend": trend,
            "breadth": breadth,
            "signal": signal,
            "pct_change": _basket_pct_change(prices, tickers),
        })

    results.sort(key=lambda x: (x["rs_score"] or 0), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results

@router.get("/sidebar")
def sidebar():
    def compute():
        prices = _get_prices()
        benchmarks = [
            {"name": name, "pct_change": _pct_change_today(prices, ticker)}
            for name, ticker in BENCHMARK_TICKERS.items()
        ]
        sectors = [
            {
                "name": sector,
                "pct_change": _basket_pct_change(prices, tickers),
            }
            for sector, tickers in SECTOR_TICKERS.items()
        ]
        rotation = _compute_rotation()
        top_rs = rotation[0]["sector"] if rotation else None
        breadth_values = [r["breadth"] for r in rotation if r["breadth"] is not None]
        avg_breadth = round(float(np.mean(breadth_values)), 4) if breadth_values else None
        return {
            "benchmarks": benchmarks,
            "sectors": sectors,
            "signal_summary": {
                "cycle_phase": _cycle["phase"],
                "top_rs_sector": top_rs,
                "breadth": avg_breadth,
            },
        }
    return _cached("sidebar", compute)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd backend && pytest tests/test_market.py::test_sidebar_returns_expected_keys tests/test_market.py::test_sidebar_benchmarks_have_pct_change tests/test_market.py::test_sidebar_sectors_all_present -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add market.py tests/test_market.py && git commit -m "feat: add /api/market/sidebar endpoint"
```

---

### Task 4: Rotation API endpoint

**Files:**
- Modify: `backend/market.py`
- Modify: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing tests — append to test_market.py**

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd backend && pytest tests/test_market.py::test_rotation_returns_11_sectors -v
```

Expected: FAILED — endpoint not found.

- [ ] **Step 3: Implement /api/market/rotation**

Add to `backend/market.py`:
```python
@router.get("/rotation")
def rotation():
    return _cached("rotation", _compute_rotation)
```

- [ ] **Step 4: Run rotation tests**

```bash
cd backend && pytest tests/test_market.py -k rotation -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add market.py tests/test_market.py && git commit -m "feat: add /api/market/rotation endpoint"
```

---

### Task 5: Breadth API endpoint

**Files:**
- Modify: `backend/market.py`
- Modify: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing tests — append to test_market.py**

```python
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
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd backend && pytest tests/test_market.py::test_breadth_returns_expected_keys -v
```

Expected: FAILED.

- [ ] **Step 3: Implement /api/market/breadth**

Add to `backend/market.py`:
```python
def _compute_breadth():
    prices = _get_prices()
    all_basket_tickers = [t for tickers in SECTOR_TICKERS.values() for t in tickers]

    above_50 = 0
    total = 0
    new_highs = 0
    new_lows = 0

    for t in all_basket_tickers:
        if t not in prices.columns:
            continue
        col = prices[t].dropna()
        if len(col) < 51:
            continue
        total += 1
        current = float(col.iloc[-1])
        ma50 = float(col.iloc[-51:-1].mean())
        if current > ma50:
            above_50 += 1
        if len(col) >= 252:
            high_52 = float(col.iloc[-252:].max())
            low_52 = float(col.iloc[-252:].min())
            if current >= high_52 * 0.99:
                new_highs += 1
            if current <= low_52 * 1.01:
                new_lows += 1

    pct_above = round(above_50 / total, 4) if total else None

    # A/D line: 20 trading days, advancing = basket stocks with positive return on that day
    ad_line = []
    cumulative = 0
    if len(prices) >= 21:
        for i in range(-20, 0):
            adv = dec = unch = 0
            for t in all_basket_tickers:
                if t not in prices.columns:
                    continue
                col = prices[t].dropna()
                if len(col) < abs(i) + 1:
                    continue
                chg = float(col.iloc[i]) - float(col.iloc[i - 1])
                if chg > 0:
                    adv += 1
                elif chg < 0:
                    dec += 1
                else:
                    unch += 1
            cumulative += (adv - dec)
            ad_line.append({
                "date": prices.index[i].strftime("%Y-%m-%d"),
                "value": cumulative,
                "advances": adv,
                "declines": dec,
            })

    # Today's advances/declines
    today_adv = today_dec = today_unch = 0
    for t in all_basket_tickers:
        if t not in prices.columns:
            continue
        col = prices[t].dropna()
        if len(col) < 2:
            continue
        chg = float(col.iloc[-1]) - float(col.iloc[-2])
        if chg > 0:
            today_adv += 1
        elif chg < 0:
            today_dec += 1
        else:
            today_unch += 1

    return {
        "pct_above_50ma": pct_above,
        "advances": today_adv,
        "declines": today_dec,
        "unchanged": today_unch,
        "new_highs": new_highs,
        "new_lows": new_lows,
        "hl_ratio": round(new_highs / new_lows, 2) if new_lows else None,
        "ad_line": ad_line,
    }

@router.get("/breadth")
def breadth():
    return _cached("breadth", _compute_breadth)
```

- [ ] **Step 4: Run breadth tests**

```bash
cd backend && pytest tests/test_market.py -k breadth -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add market.py tests/test_market.py && git commit -m "feat: add /api/market/breadth endpoint"
```

---

### Task 6: Cross-asset API endpoint

**Files:**
- Modify: `backend/market.py`
- Modify: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing tests — append to test_market.py**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && pytest tests/test_market.py::test_cross_asset_returns_expected_keys -v
```

Expected: FAILED.

- [ ] **Step 3: Implement /api/market/cross-asset**

Add to `backend/market.py`:
```python
def _cross_asset_item(prices, ticker):
    if ticker not in prices.columns:
        return {"value": None, "pct_change": None, "bias": None}
    col = prices[ticker].dropna()
    if len(col) < 2:
        return {"value": None, "pct_change": None, "bias": None}
    value = round(float(col.iloc[-1]), 4)
    pct_change = round(float((col.iloc[-1] / col.iloc[-2]) - 1), 6)
    return {"value": value, "pct_change": pct_change}

def _gilt_vs_utilities_zscore(prices):
    """Z-score of (gilt yield - utilities basket price change) over 252 days.
    Negative z-score = gilts expensive vs utilities (bearish for utilities)."""
    gilt_ticker = CROSS_ASSET_TICKERS["gilt_10y"]
    util_tickers = SECTOR_TICKERS["Utilities"]
    if gilt_ticker not in prices.columns:
        return None
    gilt = prices[gilt_ticker].dropna()
    util_cols = [prices[t].dropna() for t in util_tickers if t in prices.columns]
    if not util_cols or len(gilt) < 252:
        return None
    min_len = min(len(gilt), min(len(u) for u in util_cols))
    window = min(252, min_len)
    gilt_w = gilt.iloc[-window:]
    util_avg = np.mean([u.iloc[-window:].values for u in util_cols], axis=0)
    spread = gilt_w.values - util_avg
    if spread.std() == 0:
        return None
    zscore = round(float((spread[-1] - spread.mean()) / spread.std()), 2)
    return zscore

def _compute_cross_asset():
    prices = _get_prices()
    t = CROSS_ASSET_TICKERS
    gbpusd = _cross_asset_item(prices, t["gbpusd"])
    gilt   = _cross_asset_item(prices, t["gilt_10y"])
    brent  = _cross_asset_item(prices, t["brent"])
    gold   = _cross_asset_item(prices, t["gold"])
    vftse  = _cross_asset_item(prices, t["vftse"])
    zscore = _gilt_vs_utilities_zscore(prices)

    # Simple bias labels
    if vftse["value"] is not None:
        vftse["bias"] = "Low Vol — Risk-On" if vftse["value"] < 20 else ("High Vol — Risk-Off" if vftse["value"] > 30 else "Neutral")
    else:
        vftse["bias"] = None

    if gilt["pct_change"] is not None:
        gilt["bias"] = "Bearish (yields rising)" if gilt["pct_change"] > 0 else "Bullish (yields falling)"
    else:
        gilt["bias"] = None

    return {
        "gbpusd":            gbpusd,
        "gilt_10y":          gilt,
        "brent":             brent,
        "gold":              gold,
        "vftse":             vftse,
        "gilt_vs_utilities": {"zscore": zscore, "bias": "Gilts expensive vs Utilities" if zscore is not None and zscore < -1 else None},
    }

@router.get("/cross-asset")
def cross_asset():
    return _cached("cross_asset", _compute_cross_asset)
```

- [ ] **Step 4: Run cross-asset tests**

```bash
cd backend && pytest tests/test_market.py -k cross_asset -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
cd backend && git add market.py tests/test_market.py && git commit -m "feat: add /api/market/cross-asset endpoint"
```

---

### Task 7: Signals & Cycle API endpoints

**Files:**
- Modify: `backend/market.py`
- Modify: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing tests — append to test_market.py**

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && pytest tests/test_market.py -k "signals or cycle" -v
```

Expected: FAILED.

- [ ] **Step 3: Implement /api/market/signals and /api/market/cycle**

Add to `backend/market.py`:
```python
from fastapi import Body

def _compute_signals():
    """Generate signal log by running rotation + breadth and checking thresholds."""
    rotation_data = _compute_rotation()
    breadth_data  = _compute_breadth()
    now = datetime.now().strftime("%d %b %H:%M")
    signals = list(_signal_log)  # include manually added signals (e.g. phase changes)

    breadth_val = breadth_data.get("pct_above_50ma")
    if breadth_val is not None:
        if breadth_val > 0.65:
            signals.append({"timestamp": now, "type": "ALERT",
                            "message": f"Breadth at {breadth_val*100:.0f}% — bullish threshold crossed"})
        elif breadth_val < 0.40:
            signals.append({"timestamp": now, "type": "ALERT",
                            "message": f"Breadth at {breadth_val*100:.0f}% — bearish threshold crossed"})

    for s in rotation_data:
        if s["signal"] == "BUY":
            signals.append({"timestamp": now, "type": "BUY",
                            "message": f"{s['sector']} RS {s['rs_score']:.2f} rising — momentum breakout"})
        elif s["signal"] == "AVOID":
            signals.append({"timestamp": now, "type": "AVOID",
                            "message": f"{s['sector']} RS {s['rs_score']:.2f} falling — underperforming market"})

    # newest first (manual log entries are already ordered)
    return signals[:50]  # cap at 50 entries

@router.get("/signals")
def signals():
    return _cached("signals", _compute_signals)

@router.get("/cycle")
def get_cycle():
    return {
        "phase": _cycle["phase"],
        "set_at": _cycle["set_at"],
        "guidance": PHASE_GUIDANCE.get(_cycle["phase"], {}),
    }

@router.post("/cycle")
def set_cycle(body: dict = Body(...)):
    phase = body.get("phase")
    if phase not in PHASE_GUIDANCE:
        from fastapi import HTTPException
        raise HTTPException(400, f"phase must be one of {list(PHASE_GUIDANCE.keys())}")
    _cycle["phase"] = phase
    _cycle["set_at"] = datetime.now().isoformat()
    _signal_log.insert(0, {
        "timestamp": datetime.now().strftime("%d %b %H:%M"),
        "type": "INFO",
        "message": f"Cycle phase set to {phase} — manual override",
    })
    # clear signal cache so next fetch reflects new phase
    _cache.pop("signals", None)
    _cache.pop("sidebar", None)
    return _cycle
```

- [ ] **Step 4: Run all signal + cycle tests**

```bash
cd backend && pytest tests/test_market.py -k "signals or cycle" -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Run full test suite**

```bash
cd backend && pytest tests/ -v
```

Expected: All PASSED.

- [ ] **Step 6: Commit**

```bash
cd backend && git add market.py tests/test_market.py && git commit -m "feat: add /api/market/signals and /api/market/cycle endpoints"
```

---

### Task 8: Extract shared utils to frontend/src/utils.js

**Files:**
- Create: `frontend/src/utils.js`
- Modify: `frontend/src/App.js` — import from utils

The `fmt`, `gc`, and `API` constant are currently defined in App.js. Extract them so new components can import them without circular dependencies.

- [ ] **Step 1: Create frontend/src/utils.js**

```js
export const API = process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:8000/api';

export const fmt = (v, type = 'number') => {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
  if (type === 'currency') {
    const abs = Math.abs(v);
    const neg = v < 0 ? '-' : '';
    if (abs >= 1e12) return neg + '\u00A3' + (abs/1e12).toFixed(2) + 'T';
    if (abs >= 1e9)  return neg + '\u00A3' + (abs/1e9).toFixed(2) + 'B';
    if (abs >= 1e6)  return neg + '\u00A3' + (abs/1e6).toFixed(2) + 'M';
    return neg + '\u00A3' + abs.toLocaleString();
  }
  if (type === 'pct') return `${(v*100).toFixed(1)}%`;
  if (type === 'pct_direct') return `${v.toFixed(1)}%`;
  if (type === 'x')   return `${v.toFixed(2)}x`;
  if (type === 'ratio') return v.toFixed(2);
  return v.toLocaleString();
};

export const gc = (v) => {
  if (v === null || v === undefined) return '#94a3b8';
  return v >= 0 ? '#10b981' : '#ef4444';
};

export const pctColor = (v) => {
  if (v === null || v === undefined) return '#94a3b8';
  if (v > 0.005) return '#10b981';
  if (v < -0.005) return '#ef4444';
  return '#f59e0b';
};
```

- [ ] **Step 2: Update App.js to import from utils**

At the top of `frontend/src/App.js`, replace the three definitions:
```js
// Remove these lines:
const API = process.env.NODE_ENV === 'production' ? '/api' : 'http://localhost:8000/api';
const fmt = ...
const gc = ...

// Replace with:
import { API, fmt, gc } from './utils';
```

- [ ] **Step 3: Verify app still builds**

```bash
cd frontend && npm start
```

Expected: App loads in browser with no console errors. Screener still works.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/utils.js src/App.js && git commit -m "refactor: extract fmt, gc, API to utils.js"
```

---

### Task 9: Update App.js shell — tab navigation + sidebar layout

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Add tab state and nav buttons to App.js**

In the `App` function, add new tab state alongside the existing `page` state. Replace the existing `App` component with:

```js
export default function App() {
  const [page, setPage]           = useState('screener'); // screener | rotation | breadth | cross-asset | signals | company
  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [searchQ, setSearchQ]     = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [showSearch, setShowSearch] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const doSearch = (q) => {
    setSearchQ(q);
    if (q.length < 1) { setSearchResults([]); return; }
    fetch(`${API}/search?q=${encodeURIComponent(q)}`).then(r=>r.json()).then(setSearchResults);
  };

  const selectCompany = (sym) => {
    setSelectedSymbol(sym);
    setPage('company');
    setShowSearch(false);
    setSearchQ('');
    setSearchResults([]);
  };

  const handleRefresh = () => {
    setRefreshKey(k => k + 1);
    setLastUpdated(new Date().toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' }));
  };

  const NAV_TABS = [
    { id: 'screener',    label: 'Screener'    },
    { id: 'rotation',    label: 'Rotation'    },
    { id: 'breadth',     label: 'Breadth'     },
    { id: 'cross-asset', label: 'Cross-Asset' },
    { id: 'signals',     label: 'Signals'     },
  ];

  const showSidebar = page !== 'company';

  return (
    <div style={{ minHeight:'100vh', background:'#0a0a0a', fontFamily:'monospace' }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />

      {/* Nav */}
      <nav style={{ background:'#0a0a0a', borderBottom:'1px solid #2a2a2a', padding:'0 32px', display:'flex', alignItems:'center', height:52, position:'sticky', top:0, zIndex:100 }}>
        <div style={{ fontFamily:'monospace', fontSize:16, fontWeight:700, color:'#f97316', marginRight:32, cursor:'pointer', letterSpacing:2, textTransform:'uppercase' }} onClick={()=>setPage('screener')}>
          Egg Basket
        </div>
        <div style={{ display:'flex', gap:2 }}>
          {NAV_TABS.map(t => (
            <button key={t.id} style={{ ...S.navBtn, ...(page===t.id ? S.navBtnActive : {}) }} onClick={()=>setPage(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:12 }}>
          {lastUpdated && <span style={{ color:'#444', fontSize:10, fontFamily:'monospace' }}>Updated {lastUpdated}</span>}
          <button onClick={handleRefresh} style={{ background:'#1a1a1a', color:'#666', border:'1px solid #2a2a2a', padding:'4px 10px', borderRadius:2, fontFamily:'monospace', fontSize:10, cursor:'pointer' }}>↻</button>
          <div style={{ position:'relative' }}>
            <input
              placeholder="Search ticker or company…"
              value={searchQ}
              onChange={e=>{ doSearch(e.target.value); setShowSearch(true); }}
              onFocus={()=>setShowSearch(true)}
              onBlur={()=>setTimeout(()=>setShowSearch(false),200)}
              style={S.searchInput}
            />
            {showSearch && searchResults.length>0 && (
              <div style={S.dropdown}>
                {searchResults.map(r=>(
                  <div key={r.symbol} onClick={()=>selectCompany(r.symbol)} style={S.dropdownItem}>
                    <span style={{ fontFamily:'monospace', fontWeight:700, color:'#818cf8', minWidth:70 }}>{r.symbol.replace('.L','')}</span>
                    <span style={{ color:'#94a3b8', fontSize:13 }}>{r.name}</span>
                    <span style={{ marginLeft:'auto', fontSize:11, color:'#64748b' }}>{r.exchange}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* Body: sidebar + main */}
      <div style={{ display:'flex', maxWidth:1400, margin:'0 auto' }}>
        {showSidebar && <Sidebar refreshKey={refreshKey} />}
        <main style={{ flex:1, padding:'32px 24px', minWidth:0 }}>
          {page==='screener'    && <Screener onSelect={selectCompany} />}
          {page==='rotation'    && <RotationTab refreshKey={refreshKey} />}
          {page==='breadth'     && <BreadthTab refreshKey={refreshKey} />}
          {page==='cross-asset' && <CrossAssetTab refreshKey={refreshKey} />}
          {page==='signals'     && <SignalsTab refreshKey={refreshKey} />}
          {page==='company' && selectedSymbol && (
            <CompanyDetail symbol={selectedSymbol} onBack={()=>setPage('screener')} />
          )}
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add imports for new components at top of App.js**

After the existing `import` statements, add:
```js
import { API, fmt, gc } from './utils';
import Sidebar from './components/Sidebar';
import RotationTab from './components/RotationTab';
import BreadthTab from './components/BreadthTab';
import CrossAssetTab from './components/CrossAssetTab';
import SignalsTab from './components/SignalsTab';
```

And create the `frontend/src/components/` directory:
```bash
mkdir -p frontend/src/components
```

Create temporary stub files so the build doesn't fail (use the Write tool for each):

`frontend/src/components/Sidebar.js`:
```js
export default function Sidebar() { return null; }
```

`frontend/src/components/RotationTab.js`:
```js
export default function RotationTab() { return null; }
```

`frontend/src/components/BreadthTab.js`:
```js
export default function BreadthTab() { return null; }
```

`frontend/src/components/CrossAssetTab.js`:
```js
export default function CrossAssetTab() { return null; }
```

`frontend/src/components/SignalsTab.js`:
```js
export default function SignalsTab() { return null; }
```

- [ ] **Step 3: Verify app builds and tabs appear in nav**

```bash
cd frontend && npm start
```

Expected: App loads, five nav tabs visible, clicking each shows the placeholder text, Screener still works.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/App.js src/components/ && git commit -m "feat: add tab navigation and sidebar layout to App.js"
```

---

### Task 10: Sidebar component

**Files:**
- Overwrite: `frontend/src/components/Sidebar.js`

- [ ] **Step 1: Write Sidebar.js**

```js
import { useState, useEffect } from 'react';
import { API, pctColor } from '../utils';

function PctBadge({ value }) {
  if (value === null || value === undefined) return <span style={{ color:'#444', fontSize:10 }}>—</span>;
  const pct = (value * 100).toFixed(2);
  const color = pctColor(value);
  const bg = value > 0.005 ? '#0d2318' : value < -0.005 ? '#2a0d0d' : '#1a1400';
  return (
    <span style={{ background:bg, color, padding:'1px 5px', borderRadius:2, fontSize:10, fontFamily:'monospace' }}>
      {value > 0 ? '+' : ''}{pct}%
    </span>
  );
}

export default function Sidebar({ refreshKey }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch(`${API}/market/sidebar`)
      .then(r => r.json())
      .then(setData)
      .catch(() => {});
  }, [refreshKey]);

  const labelStyle = { color:'#444', fontSize:9, letterSpacing:'1.5px', textTransform:'uppercase', marginBottom:8 };
  const rowStyle   = { display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4 };
  const nameStyle  = { color:'#94a3b8', fontSize:10 };

  return (
    <aside style={{ width:185, flexShrink:0, background:'#0d0d0d', borderRight:'1px solid #1e1e1e', padding:'16px 12px', minHeight:'calc(100vh - 52px)', position:'sticky', top:52, overflowY:'auto' }}>

      {/* Benchmarks */}
      <div style={labelStyle}>Benchmarks</div>
      {data?.benchmarks?.map(b => (
        <div key={b.name} style={rowStyle}>
          <span style={nameStyle}>{b.name}</span>
          <PctBadge value={b.pct_change} />
        </div>
      )) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* Sectors */}
      <div style={{ ...labelStyle, marginTop:16 }}>ICB Sectors</div>
      {data?.sectors?.map(s => (
        <div key={s.name} style={rowStyle}>
          <span style={{ ...nameStyle, maxWidth:110, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.name}</span>
          <PctBadge value={s.pct_change} />
        </div>
      )) ?? <div style={{ color:'#333', fontSize:10 }}>Loading…</div>}

      {/* Signal Summary */}
      {data?.signal_summary && (
        <div style={{ marginTop:16, borderTop:'1px solid #1e1e1e', paddingTop:12 }}>
          <div style={labelStyle}>Model Signal</div>
          <div style={{ background:'#1a1400', border:'1px solid #333', borderRadius:3, padding:10 }}>
            <div style={{ color:'#f59e0b', fontSize:11, marginBottom:6, fontWeight:700 }}>
              ⚡ {data.signal_summary.cycle_phase?.toUpperCase()}
            </div>
            <div style={{ color:'#666', fontSize:9 }}>
              Breadth: <span style={{ color:'#10b981' }}>{data.signal_summary.breadth !== null ? `${(data.signal_summary.breadth*100).toFixed(0)}%` : '—'}</span>
            </div>
            <div style={{ color:'#666', fontSize:9 }}>
              Top RS: <span style={{ color:'#60a5fa' }}>{data.signal_summary.top_rs_sector ?? '—'}</span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
```

- [ ] **Step 2: Verify sidebar renders**

```bash
cd frontend && npm start
```

Expected: Left sidebar shows benchmark and sector rows with % badges. "Loading…" briefly, then data.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/Sidebar.js && git commit -m "feat: add Sidebar component with benchmarks, sectors, signal summary"
```

---

### Task 11: Rotation tab

**Files:**
- Overwrite: `frontend/src/components/RotationTab.js`

- [ ] **Step 1: Write RotationTab.js**

```js
import { useState, useEffect } from 'react';
import { API } from '../utils';

const PHASE_ANGLES  = { Recovery: 45, Expansion: 135, Slowdown: 225, Contraction: 315 };
const PHASE_COLOURS = { Recovery:'#10b981', Expansion:'#60a5fa', Slowdown:'#f59e0b', Contraction:'#ef4444' };

const PHASES = ['Recovery', 'Expansion', 'Slowdown', 'Contraction'];

function needleXY(phase, cx, cy, r) {
  const deg = PHASE_ANGLES[phase] || 45;
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function CycleWheel({ phase, onSetPhase }) {
  const cx = 90, cy = 90, r = 65;
  const needle = needleXY(phase, cx, cy, 55);
  const colour = PHASE_COLOURS[phase] || '#f59e0b';

  return (
    <div style={{ textAlign:'center' }}>
      <svg width={180} height={180} viewBox="0 0 180 180">
        {/* Quadrant fills */}
        <path d={`M${cx},${cy} L${cx},${cy-r} A${r},${r} 0 0,1 ${cx+r},${cy} Z`} fill="#0d2318" stroke="#1e4030" strokeWidth={1}/>
        <path d={`M${cx},${cy} L${cx+r},${cy} A${r},${r} 0 0,1 ${cx},${cy+r} Z`} fill="#1a1400" stroke="#3a2800" strokeWidth={1}/>
        <path d={`M${cx},${cy} L${cx},${cy+r} A${r},${r} 0 0,1 ${cx-r},${cy} Z`} fill="#2a0d0d" stroke="#4a1a1a" strokeWidth={1}/>
        <path d={`M${cx},${cy} L${cx-r},${cy} A${r},${r} 0 0,1 ${cx},${cy-r} Z`} fill="#0d1a2a" stroke="#1a3040" strokeWidth={1}/>
        {/* Labels */}
        <text x={cx+42} y={cy-38} fill="#10b981" fontSize={9} fontFamily="monospace" textAnchor="middle">RECOVERY</text>
        <text x={cx+42} y={cy+46} fill="#60a5fa" fontSize={9} fontFamily="monospace" textAnchor="middle">EXPANSION</text>
        <text x={cx-40} y={cy+46} fill="#f59e0b" fontSize={9} fontFamily="monospace" textAnchor="middle">SLOWDOWN</text>
        <text x={cx-38} y={cy-38} fill="#ef4444" fontSize={9} fontFamily="monospace" textAnchor="middle">CONTRACTION</text>
        {/* Center */}
        <circle cx={cx} cy={cy} r={22} fill="#111" stroke="#333" strokeWidth={1}/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={needle.x} y2={needle.y} stroke={colour} strokeWidth={2.5} strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r={4} fill={colour}/>
      </svg>
      <div style={{ color: colour, fontSize:13, fontWeight:700, marginTop:4 }}>{phase?.toUpperCase()}</div>
      <select
        value={phase}
        onChange={e => onSetPhase(e.target.value)}
        style={{ marginTop:8, background:'#1a1a1a', color:'#666', border:'1px solid #333', padding:'3px 8px', borderRadius:2, fontFamily:'monospace', fontSize:10, cursor:'pointer' }}
      >
        {PHASES.map(p => <option key={p} value={p}>{p}</option>)}
      </select>
    </div>
  );
}

function SectorHeatmap({ sectors }) {
  if (!sectors?.length) return null;
  return (
    <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:6 }}>
      {sectors.map(s => {
        const rs = s.rs_score;
        const rank = s.rank;
        const isTop = rank <= 4;
        const isBottom = rank >= 8;
        const bg    = isTop ? `rgba(16,185,129,${0.08 + (4-rank)*0.04})` : isBottom ? `rgba(239,68,68,${0.05 + (rank-8)*0.03})` : '#101010';
        const border= isTop ? '#10b981' : isBottom ? '#ef4444' : '#222';
        const color = isTop ? '#10b981' : isBottom ? '#ef4444' : '#555';
        return (
          <div key={s.sector} style={{ background:bg, border:`1px solid ${border}`, borderRadius:2, padding:'8px 6px', textAlign:'center' }}>
            <div style={{ color, fontSize:9, fontWeight:700 }}>#{rank}</div>
            <div style={{ color:'#e5e5e5', fontSize:10, marginTop:2 }}>{s.sector}</div>
            <div style={{ color, fontSize:9, marginTop:1 }}>{rs?.toFixed(2)}</div>
          </div>
        );
      })}
    </div>
  );
}

function RSTable({ sectors }) {
  if (!sectors?.length) return null;
  const badgeStyle = (sig) => ({
    background: sig==='BUY' ? '#0d3320' : sig==='AVOID' ? '#2a0d0d' : '#1a1a1a',
    color:      sig==='BUY' ? '#10b981' : sig==='AVOID' ? '#ef4444' : '#555',
    padding:'2px 7px', borderRadius:2, fontSize:9,
  });
  return (
    <table style={{ width:'100%', borderCollapse:'collapse', fontSize:11, fontFamily:'monospace' }}>
      <thead>
        <tr style={{ borderBottom:'1px solid #2a2a2a' }}>
          {['Rank','Sector','RS Score','Trend','Breadth','Signal'].map(h => (
            <th key={h} style={{ padding:'6px 10px', color:'#f97316', fontSize:9, textTransform:'uppercase', letterSpacing:0.5, textAlign: h==='Rank'||h==='RS Score'||h==='Breadth' ? 'right' : 'left' }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sectors.map(s => (
          <tr key={s.sector} style={{ borderBottom:'1px solid #141414' }}>
            <td style={{ padding:'6px 10px', color:'#555', textAlign:'right' }}>#{s.rank}</td>
            <td style={{ padding:'6px 10px', color:'#e5e5e5' }}>{s.sector}</td>
            <td style={{ padding:'6px 10px', color: s.rs_score>1 ? '#10b981' : '#ef4444', textAlign:'right' }}>{s.rs_score?.toFixed(2) ?? '—'}</td>
            <td style={{ padding:'6px 10px', color: s.trend==='rising' ? '#10b981' : s.trend==='falling' ? '#ef4444' : '#555' }}>
              {s.trend==='rising' ? '↑ Rising' : s.trend==='falling' ? '↓ Falling' : '—'}
            </td>
            <td style={{ padding:'6px 10px', color:'#94a3b8', textAlign:'right' }}>
              {s.breadth !== null && s.breadth !== undefined ? `${(s.breadth*100).toFixed(0)}%` : '—'}
            </td>
            <td style={{ padding:'6px 10px' }}><span style={badgeStyle(s.signal)}>{s.signal}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RotationTab({ refreshKey }) {
  const [rotation, setRotation] = useState([]);
  const [cycle, setCycle]       = useState(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/market/rotation`).then(r=>r.json()),
      fetch(`${API}/market/cycle`).then(r=>r.json()),
    ]).then(([rot, cyc]) => {
      setRotation(Array.isArray(rot) ? rot : []);
      setCycle(cyc);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [refreshKey]);

  const handleSetPhase = (phase) => {
    fetch(`${API}/market/cycle`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ phase }),
    }).then(r=>r.json()).then(setCycle);
  };

  const card = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };
  const title = { color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading rotation data…</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Sector Rotation</h2>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, marginBottom:16 }}>
        <div style={card}>
          <div style={title}>Sector Heatmap — RS Rank</div>
          <SectorHeatmap sectors={rotation} />
        </div>
        <div style={card}>
          <div style={title}>Business Cycle</div>
          {cycle && <CycleWheel phase={cycle.phase} onSetPhase={handleSetPhase} />}
          {cycle?.guidance && (
            <div style={{ marginTop:12, fontSize:10 }}>
              <div style={{ color:'#10b981', marginBottom:2 }}>Favour: {cycle.guidance.favour?.join(', ')}</div>
              <div style={{ color:'#ef4444' }}>Avoid: {cycle.guidance.avoid?.join(', ')}</div>
            </div>
          )}
        </div>
      </div>
      <div style={card}>
        <div style={title}>RS Ranking Table</div>
        <RSTable sectors={rotation} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify Rotation tab renders**

```bash
cd frontend && npm start
```

Click "Rotation" tab. Expected: heatmap grid, cycle wheel with needle, RS ranking table all visible.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/RotationTab.js && git commit -m "feat: add RotationTab with heatmap, cycle wheel, RS table"
```

---

### Task 12: Breadth tab

**Files:**
- Overwrite: `frontend/src/components/BreadthTab.js`

- [ ] **Step 1: Write BreadthTab.js**

```js
import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { API } from '../utils';

function BreadthGauge({ value }) {
  // value: 0.0–1.0
  const pct    = value !== null && value !== undefined ? value : 0.5;
  const cx = 100, cy = 100, r = 80;
  // Semicircle: 0% → left (180°), 100% → right (0°), 50% → top
  const angleDeg = 180 - pct * 180;
  const rad = angleDeg * Math.PI / 180;
  const nx  = cx + 68 * Math.cos(rad);
  const ny  = cy - 68 * Math.sin(rad);
  const color = pct > 0.60 ? '#10b981' : pct < 0.40 ? '#ef4444' : '#f59e0b';
  const label = pct > 0.60 ? 'Bullish Breadth' : pct < 0.40 ? 'Bearish Breadth' : 'Neutral';

  return (
    <div style={{ textAlign:'center' }}>
      <svg width={200} height={115} viewBox="0 0 200 115">
        {/* Background arc */}
        <path d={`M20,100 A80,80 0 0,1 180,100`} fill="none" stroke="#1e1e1e" strokeWidth={14} strokeLinecap="round"/>
        {/* Coloured arc — gradient approximated via 3 segments */}
        <path d={`M20,100 A80,80 0 0,1 100,20`}  fill="none" stroke="#ef4444" strokeWidth={10} strokeLinecap="round" opacity={0.4}/>
        <path d={`M100,20 A80,80 0 0,1 180,100`} fill="none" stroke="#10b981" strokeWidth={10} strokeLinecap="round" opacity={0.4}/>
        {/* Needle */}
        <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth={3} strokeLinecap="round"/>
        <circle cx={cx} cy={cy} r={5} fill={color}/>
        {/* Value */}
        <text x={cx} y={cy-12} textAnchor="middle" fill={color} fontSize={20} fontFamily="monospace" fontWeight={700}>
          {value !== null && value !== undefined ? `${(value*100).toFixed(0)}%` : '—'}
        </text>
      </svg>
      <div style={{ color, fontSize:11, marginTop:2 }}>{label}</div>
    </div>
  );
}

export default function BreadthTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/breadth`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  const card  = { background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 };
  const title = { color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 };

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading breadth data…</div>;

  const tooltipStyle = { background:'#141414', border:'1px solid #2a2a2a', borderRadius:4, fontSize:11, color:'#e5e5e5', fontFamily:'monospace' };

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Market Breadth</h2>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16, marginBottom:16 }}>

        {/* Gauge */}
        <div style={card}>
          <div style={title}>% Above 50-Day MA</div>
          <BreadthGauge value={data?.pct_above_50ma} />
          <div style={{ display:'flex', justifyContent:'space-around', marginTop:12, fontSize:10, fontFamily:'monospace' }}>
            <span style={{ color:'#555' }}>Adv: <span style={{ color:'#10b981' }}>{data?.advances ?? '—'}</span></span>
            <span style={{ color:'#555' }}>Dec: <span style={{ color:'#ef4444' }}>{data?.declines ?? '—'}</span></span>
            <span style={{ color:'#555' }}>Unch: <span style={{ color:'#555' }}>{data?.unchanged ?? '—'}</span></span>
          </div>
        </div>

        {/* 52-week highs/lows */}
        <div style={card}>
          <div style={title}>52-Week Highs / Lows</div>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { label:'New Highs', value: data?.new_highs, color:'#10b981', bg:'#0d2318' },
              { label:'New Lows',  value: data?.new_lows,  color:'#ef4444', bg:'#2a0d0d' },
              { label:'H/L Ratio', value: data?.hl_ratio?.toFixed(1) + 'x', color:'#e5e5e5', bg:'#1a1a1a' },
            ].map(({ label, value, color, bg }) => (
              <div key={label} style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                <span style={{ color:'#94a3b8', fontSize:11 }}>{label}</span>
                <span style={{ background:bg, color, padding:'2px 10px', borderRadius:2, fontSize:13, fontWeight:700 }}>
                  {value ?? '—'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* A/D placeholder card — chart is below */}
        <div style={card}>
          <div style={title}>Advance / Decline</div>
          <div style={{ fontSize:10, color:'#555', lineHeight:1.8 }}>
            <div>Today advancing: <span style={{ color:'#10b981' }}>{data?.advances ?? '—'}</span></div>
            <div>Today declining: <span style={{ color:'#ef4444' }}>{data?.declines ?? '—'}</span></div>
            <div style={{ marginTop:8, color:'#444' }}>A/D line below ↓</div>
          </div>
        </div>
      </div>

      {/* A/D Line chart */}
      {data?.ad_line?.length > 0 && (
        <div style={card}>
          <div style={title}>Cumulative Advance / Decline Line (20 days)</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={data.ad_line} margin={{ top:5, right:10, bottom:5, left:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e1e1e" />
              <XAxis dataKey="date" tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }} tickFormatter={d => d.slice(5)} />
              <YAxis tick={{ fontSize:9, fill:'#444', fontFamily:'monospace' }} />
              <Tooltip contentStyle={tooltipStyle} />
              <ReferenceLine y={0} stroke="#333" />
              <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={2} dot={false} name="A/D Line" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify Breadth tab renders**

```bash
cd frontend && npm start
```

Click "Breadth". Expected: gauge, highs/lows card, A/D chart visible.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/BreadthTab.js && git commit -m "feat: add BreadthTab with gauge, highs/lows, A/D chart"
```

---

### Task 13: Cross-Asset tab

**Files:**
- Overwrite: `frontend/src/components/CrossAssetTab.js`

- [ ] **Step 1: Write CrossAssetTab.js**

```js
import { useState, useEffect } from 'react';
import { API } from '../utils';

function AssetCard({ label, item, decimals = 2, prefix = '' }) {
  if (!item) return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#333', fontSize:18, fontWeight:700, fontFamily:'monospace' }}>—</div>
    </div>
  );

  const { value, pct_change, bias } = item;
  const chgColor = pct_change === null ? '#555' : pct_change > 0 ? '#10b981' : pct_change < 0 ? '#ef4444' : '#f59e0b';
  const arrow = pct_change === null ? '' : pct_change > 0.001 ? ' ↑' : pct_change < -0.001 ? ' ↓' : ' →';

  return (
    <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color:'#e5e5e5', fontSize:20, fontWeight:700, fontFamily:'monospace' }}>
        {value !== null && value !== undefined ? `${prefix}${value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}` : '—'}
      </div>
      <div style={{ color: chgColor, fontSize:10, marginTop:4 }}>
        {pct_change !== null && pct_change !== undefined
          ? `${pct_change > 0 ? '+' : ''}${(pct_change * 100).toFixed(2)}%${arrow}`
          : '—'}
      </div>
      {bias && <div style={{ color:'#555', fontSize:9, marginTop:4 }}>{bias}</div>}
    </div>
  );
}

function ZScoreCard({ label, item }) {
  if (!item) return <div style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:16 }}><div style={{ color:'#444', fontSize:9 }}>{label}</div><div style={{ color:'#333' }}>—</div></div>;
  const { zscore, bias } = item;
  const color = zscore === null ? '#555' : zscore < -1 ? '#ef4444' : zscore > 1 ? '#10b981' : '#f59e0b';
  return (
    <div style={{ background: zscore !== null && zscore < -1 ? '#1a0a0a' : '#141414', border:`1px solid ${zscore !== null && zscore < -1 ? '#3a1a1a' : '#2a2a2a'}`, borderRadius:2, padding:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:1, marginBottom:6 }}>{label}</div>
      <div style={{ color, fontSize:20, fontWeight:700, fontFamily:'monospace' }}>
        {zscore !== null && zscore !== undefined ? `${zscore > 0 ? '+' : ''}${zscore.toFixed(2)}σ` : '—'}
      </div>
      {bias && <div style={{ color:'#555', fontSize:9, marginTop:4 }}>{bias}</div>}
    </div>
  );
}

export default function CrossAssetTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/cross-asset`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading cross-asset data…</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Cross-Asset</h2>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12 }}>
        <AssetCard label="GBP / USD"       item={data?.gbpusd}   decimals={4} />
        <AssetCard label="10Y Gilt Yield"  item={data?.gilt_10y} decimals={2} prefix="%" />
        <AssetCard label="Brent Crude"     item={data?.brent}    decimals={2} prefix="$" />
        <AssetCard label="Gold"            item={data?.gold}     decimals={0} prefix="$" />
        <AssetCard label="VFTSE Volatility" item={data?.vftse}   decimals={1} />
        <ZScoreCard label="Gilt vs Utilities (z-score)" item={data?.gilt_vs_utilities} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify Cross-Asset tab renders**

```bash
cd frontend && npm start
```

Click "Cross-Asset". Expected: 6 KPI cards visible (values or `—` if data unavailable).

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/CrossAssetTab.js && git commit -m "feat: add CrossAssetTab with 6 KPI cards"
```

---

### Task 14: Signals tab

**Files:**
- Overwrite: `frontend/src/components/SignalsTab.js`

- [ ] **Step 1: Write SignalsTab.js**

```js
import { useState, useEffect } from 'react';
import { API } from '../utils';

const BADGE_STYLES = {
  BUY:   { background:'#0d3320', color:'#10b981' },
  AVOID: { background:'#2a0d0d', color:'#ef4444' },
  ALERT: { background:'#1a1400', color:'#f59e0b' },
  INFO:  { background:'#0d1a2a', color:'#60a5fa' },
};

function SignalBadge({ type }) {
  const style = BADGE_STYLES[type] || BADGE_STYLES.INFO;
  return (
    <span style={{ ...style, padding:'2px 7px', borderRadius:2, fontSize:9, fontFamily:'monospace', whiteSpace:'nowrap', fontWeight:700 }}>
      {type}
    </span>
  );
}

export default function SignalsTab({ refreshKey }) {
  const [signals, setSignals]   = useState([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/market/signals`)
      .then(r => r.json())
      .then(d => { setSignals(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [refreshKey]);

  if (loading) return <div style={{ color:'#444', padding:32, fontFamily:'monospace' }}>Loading signals…</div>;

  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Signal Log</h2>
      <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16 }}>
        <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
          {signals.length} signal{signals.length !== 1 ? 's' : ''} — newest first
        </div>
        {signals.length === 0 && (
          <div style={{ color:'#333', fontSize:12, padding:'24px 0', textAlign:'center' }}>
            No signals triggered yet. Check back after market open.
          </div>
        )}
        {signals.map((s, i) => (
          <div key={i} style={{ display:'flex', gap:12, alignItems:'flex-start', borderBottom:'1px solid #141414', padding:'10px 0', fontFamily:'monospace' }}>
            <span style={{ color:'#444', fontSize:9, whiteSpace:'nowrap', marginTop:2 }}>{s.timestamp}</span>
            <SignalBadge type={s.type} />
            <span style={{ color:'#e5e5e5', fontSize:11 }}>{s.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify Signals tab renders**

```bash
cd frontend && npm start
```

Click "Signals". Expected: signal log with timestamped entries (BUY/AVOID/ALERT/INFO badges).

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/SignalsTab.js && git commit -m "feat: add SignalsTab with timestamped signal feed"
```

---

### Task 15: .gitignore update

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add .superpowers/ to .gitignore**

Open `.gitignore` and add the following line (if not already present):
```
.superpowers/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore && git commit -m "chore: ignore .superpowers/ brainstorm artefacts"
```

---

## Summary

| Task | Backend / Frontend | Deliverable |
|---|---|---|
| 1 | Backend | yfinance install, market.py skeleton, cache, test setup |
| 2 | Backend | Mount market router in main.py |
| 3 | Backend | `/api/market/sidebar` endpoint + tests |
| 4 | Backend | `/api/market/rotation` endpoint + tests |
| 5 | Backend | `/api/market/breadth` endpoint + tests |
| 6 | Backend | `/api/market/cross-asset` endpoint + tests |
| 7 | Backend | `/api/market/signals` + `/api/market/cycle` + tests |
| 8 | Frontend | Shared `utils.js`, App.js import update |
| 9 | Frontend | App.js shell: tab nav + sidebar layout |
| 10 | Frontend | `Sidebar.js` |
| 11 | Frontend | `RotationTab.js` |
| 12 | Frontend | `BreadthTab.js` |
| 13 | Frontend | `CrossAssetTab.js` |
| 14 | Frontend | `SignalsTab.js` |
| 15 | Infra | `.gitignore` update |
