# UK Fear & Greed Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 5-component UK Fear & Greed index that scores sentiment 0–100, auto-detects the business cycle phase after 2 consecutive confirmed readings, displays compactly in the sidebar, and shows full component breakdown in the Breadth tab.

**Architecture:** A new `_compute_fear_greed()` function in `market.py` aggregates 5 z-score-normalised signals into a 0–100 score. It maintains in-memory history (`_fg_history`, last 4 readings) and auto-updates `_cycle` when 2 consecutive readings agree on a phase. The result is cached under `"fear_greed"` (shared between the sidebar and the dedicated endpoint). The frontend fetches fear_greed data in both `Sidebar.js` (from existing `/api/market/sidebar`) and `BreadthTab.js` (from the new `/api/market/fear-greed` endpoint).

**Tech Stack:** Python/FastAPI, numpy/pandas, yfinance (existing); React, inline styles (existing pattern)

---

## File Map

| File | Change |
|---|---|
| `backend/market.py` | Add `_fg_history`, `_zscore_to_score()`, `_suggest_phase()`, `_compute_fear_greed()`, `GET /fear-greed` endpoint; update `sidebar()` |
| `backend/tests/test_market.py` | Add tests for helpers, fear-greed endpoint, sidebar fear_greed key |
| `frontend/src/components/Sidebar.js` | Add `fgColor()`/`fgBg()` helpers + compact F&G block between VIX and ICB Sectors |
| `frontend/src/components/BreadthTab.js` | Fetch `/api/market/fear-greed`, add `FearGreedCard` component at top of tab |

---

## Task 1: Backend helpers — `_zscore_to_score` and `_suggest_phase`

**Files:**
- Modify: `backend/market.py`
- Test: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `backend/tests/test_market.py`:

```python
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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && python -m pytest tests/test_market.py::test_zscore_to_score_midpoint tests/test_market.py::test_suggest_phase_low_falling -v
```

Expected: `ERROR` — `market` has no attribute `_zscore_to_score`

- [ ] **Step 3: Add helpers to `backend/market.py`**

Insert after the `_signal_log: list = []` line (around line 96):

```python
# ── Fear & Greed helpers ──────────────────────────────────────────────────────
def _zscore_to_score(series, current_val):
    """Map current_val to 0-100 using z-score over series. Returns 50 on insufficient data."""
    if len(series) < 20:
        return 50
    mean = float(series.mean())
    std = float(series.std())
    if std == 0:
        return 50
    z = (current_val - mean) / std
    z = max(-2.0, min(2.0, z))
    return round((z + 2) / 4 * 100)

def _suggest_phase(score, trend):
    """Map F&G score + trend to a suggested cycle phase string."""
    if trend == "unknown":
        return "no_change"
    if 45 <= score <= 55:
        return "no_change"
    if score < 45 and trend == "falling":
        return "Contraction"
    if score < 45 and trend == "rising":
        return "Recovery"
    if score > 55 and trend == "rising":
        return "Expansion"
    if score > 55 and trend == "falling":
        return "Slowdown"
    return "no_change"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/test_market.py -k "zscore or suggest_phase" -v
```

Expected: 10 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/market.py backend/tests/test_market.py
git commit -m "feat: add _zscore_to_score and _suggest_phase helpers for fear-greed index"
```

---

## Task 2: `_compute_fear_greed()` and `_fg_history`

**Files:**
- Modify: `backend/market.py`
- Test: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_market.py`:

```python
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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && python -m pytest tests/test_market.py -k "fear_greed" -v
```

Expected: `FAILED` — 404 (endpoint doesn't exist yet)

- [ ] **Step 3: Add `_fg_history` state and `_compute_fear_greed()` to `backend/market.py`**

Insert after the `_signal_log: list = []` line (after the existing `_fg_history` list and helpers added in Task 1):

```python
# ── Fear & Greed state ────────────────────────────────────────────────────────
_fg_history: list = []  # last 4 readings: [{score, suggested_phase, timestamp}, ...]
```

Then add `_compute_fear_greed()` after `_suggest_phase()`:

```python
def _compute_fear_greed():
    """Compute 5-component UK Fear & Greed score (0-100), update history, auto-set cycle phase."""
    prices = _get_prices()
    components = {}

    # 1. FTSE Momentum — FTSE 100 vs rolling 125-day MA
    ftse_ticker = BENCHMARK_TICKERS["FTSE 100"]
    if ftse_ticker in prices.columns:
        ftse = prices[ftse_ticker].dropna()
        if len(ftse) >= 126:
            roll_ma125 = ftse.rolling(125).mean()
            momentum_series = ((ftse - roll_ma125) / roll_ma125).dropna()
            if len(momentum_series) >= 20:
                current_momentum = float(momentum_series.iloc[-1])
                components["momentum"] = {
                    "score": _zscore_to_score(momentum_series, current_momentum),
                    "label": "FTSE Momentum",
                    "value": round(current_momentum * 100, 2),
                }
    if "momentum" not in components:
        components["momentum"] = {"score": 50, "label": "FTSE Momentum", "value": None}

    # 2. Market Breadth — % basket stocks above 50-day MA
    breadth_data = _compute_breadth()
    breadth_pct = breadth_data.get("pct_above_50ma")
    if breadth_pct is not None:
        components["breadth"] = {
            "score": round(breadth_pct * 100),
            "label": "Market Breadth",
            "value": round(breadth_pct * 100, 1),
        }
    else:
        components["breadth"] = {"score": 50, "label": "Market Breadth", "value": None}

    # 3. VIX — inverted (high VIX = fear = low score)
    if VIX_TICKER in prices.columns:
        vix = prices[VIX_TICKER].dropna()
        if len(vix) >= 20:
            current_vix = float(vix.iloc[-1])
            components["vix"] = {
                "score": _zscore_to_score(-vix, -current_vix),
                "label": "VIX",
                "value": round(current_vix, 2),
            }
    if "vix" not in components:
        components["vix"] = {"score": 50, "label": "VIX", "value": None}

    # 4. Safe Haven Demand — 20-day return spread: FTSE 100 vs UK gilt
    gilt_ticker = CROSS_ASSET_TICKERS["gilt_10y"]
    if ftse_ticker in prices.columns and gilt_ticker in prices.columns:
        ftse = prices[ftse_ticker].dropna()
        gilt = prices[gilt_ticker].dropna()
        if len(ftse) >= 21 and len(gilt) >= 21:
            spread = (ftse.pct_change(20) - gilt.pct_change(20)).dropna()
            if len(spread) >= 20:
                current_spread = float(spread.iloc[-1])
                components["safe_haven"] = {
                    "score": _zscore_to_score(spread, current_spread),
                    "label": "Safe Haven Demand",
                    "value": round(current_spread * 100, 2),
                }
    if "safe_haven" not in components:
        components["safe_haven"] = {"score": 50, "label": "Safe Haven Demand", "value": None}

    # 5. New Highs / Lows ratio from basket
    new_highs = breadth_data.get("new_highs", 0)
    new_lows = breadth_data.get("new_lows", 0)
    total_hl = new_highs + new_lows
    components["hl_ratio"] = {
        "score": round(new_highs / total_hl * 100) if total_hl > 0 else 50,
        "label": "New Highs / Lows",
        "value": f"{new_highs}/{new_lows}",
    }

    # Overall score = simple average
    scores = [c["score"] for c in components.values()]
    overall = round(sum(scores) / len(scores)) if scores else 50

    # Sentiment label
    if overall >= 75:   sentiment = "Extreme Greed"
    elif overall >= 55: sentiment = "Greed"
    elif overall >= 45: sentiment = "Neutral"
    elif overall >= 25: sentiment = "Fear"
    else:               sentiment = "Extreme Fear"

    # Trend: compare current score vs reading 3 cycles ago (before appending)
    if len(_fg_history) >= 3:
        trend = "rising" if overall > _fg_history[-3]["score"] else "falling"
    else:
        trend = "unknown"

    # Suggested phase from score + trend
    suggested_phase = _suggest_phase(overall, trend)

    # Update history (keep last 4)
    _fg_history.append({
        "score": overall,
        "suggested_phase": suggested_phase,
        "timestamp": datetime.now().isoformat(),
    })
    if len(_fg_history) > 4:
        _fg_history.pop(0)

    # Auto-update cycle if last 2 readings confirm same phase
    confirmed = False
    if len(_fg_history) >= 2 and suggested_phase != "no_change":
        last_two = _fg_history[-2:]
        if last_two[0]["suggested_phase"] == last_two[1]["suggested_phase"] == suggested_phase:
            confirmed = True
            if suggested_phase != _cycle["phase"]:
                _cycle["phase"] = suggested_phase
                _cycle["set_at"] = datetime.now().isoformat()
                _signal_log.insert(0, {
                    "timestamp": datetime.now().strftime("%d %b %H:%M"),
                    "type": "INFO",
                    "message": f"Cycle phase auto-updated to {suggested_phase} by Fear & Greed index (score: {overall})",
                })
                _cache.pop("signals", None)
                _cache.pop("sidebar", None)

    return {
        "score": overall,
        "sentiment": sentiment,
        "trend": trend,
        "suggested_phase": suggested_phase,
        "confirmed": confirmed,
        "components": components,
    }
```

- [ ] **Step 4: Add the endpoint to `backend/market.py`**

Add after the `cross_asset()` endpoint:

```python
@router.get("/fear-greed")
def fear_greed():
    return _cached("fear_greed", _compute_fear_greed)
```

- [ ] **Step 5: Run the fear-greed tests**

```bash
cd backend && python -m pytest tests/test_market.py -k "fear_greed" -v
```

Expected: 6 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/market.py backend/tests/test_market.py
git commit -m "feat: add _compute_fear_greed, _fg_history, and GET /api/market/fear-greed endpoint"
```

---

## Task 3: Update sidebar endpoint to include fear_greed

**Files:**
- Modify: `backend/market.py`
- Test: `backend/tests/test_market.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_market.py`:

```python
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
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd backend && python -m pytest tests/test_market.py::test_sidebar_includes_fear_greed -v
```

Expected: FAILED — `"fear_greed" not in data`

- [ ] **Step 3: Update `sidebar()` in `backend/market.py`**

Find the `compute()` inner function inside `sidebar()`. Replace the `return` statement:

```python
        # existing lines above unchanged ...
        vix_col = prices[VIX_TICKER].dropna() if VIX_TICKER in prices.columns else None
        vix_level = round(float(vix_col.iloc[-1]), 2) if vix_col is not None and len(vix_col) else None
        fg = _cached("fear_greed", _compute_fear_greed)
        return {
            "benchmarks": benchmarks,
            "sectors": sectors,
            "vix": vix_level,
            "fear_greed": {
                "score":          fg["score"],
                "sentiment":      fg["sentiment"],
                "trend":          fg["trend"],
                "suggested_phase": fg["suggested_phase"],
            },
            "signal_summary": {
                "cycle_phase": _cycle["phase"],
                "top_rs_sector": top_rs,
                "breadth": avg_breadth,
            },
        }
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests PASSED (including the new one)

- [ ] **Step 5: Commit**

```bash
git add backend/market.py backend/tests/test_market.py
git commit -m "feat: include fear_greed summary in sidebar endpoint"
```

---

## Task 4: Sidebar.js — compact Fear & Greed block

**Files:**
- Modify: `frontend/src/components/Sidebar.js`

- [ ] **Step 1: Add colour helpers and F&G block to `Sidebar.js`**

Add the two helper functions before the `PctBadge` component (top of file, after the imports):

```js
function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
}

function fgBg(score) {
  if (score >= 75) return '#0d2318';
  if (score >= 55) return '#1a1400';
  if (score >= 45) return '#1a1a1a';
  if (score >= 25) return '#2a1a00';
  return '#2a0d0d';
}
```

Then add the F&G block inside the `return` of `Sidebar`, between the VIX block and the `{/* Sectors */}` comment:

```jsx
      {/* Fear & Greed */}
      {data?.fear_greed && (
        <div style={{ marginTop:12, paddingTop:10, borderTop:'1px solid #1e1e1e' }}>
          <div style={labelStyle}>Fear &amp; Greed</div>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4 }}>
            <span style={{ fontFamily:'monospace', fontSize:22, fontWeight:700, color: fgColor(data.fear_greed.score) }}>
              {data.fear_greed.score}
            </span>
            <span style={{
              background: fgBg(data.fear_greed.score),
              color: fgColor(data.fear_greed.score),
              padding:'2px 6px', borderRadius:2, fontSize:9,
              border:`1px solid ${fgColor(data.fear_greed.score)}33`,
            }}>
              {data.fear_greed.sentiment?.toUpperCase()}
            </span>
          </div>
          <div style={{ background:'#1a1a1a', borderRadius:2, height:4, marginBottom:6 }}>
            <div style={{ background: fgColor(data.fear_greed.score), width:`${data.fear_greed.score}%`, height:4, borderRadius:2 }}/>
          </div>
          {data.fear_greed.suggested_phase && data.fear_greed.suggested_phase !== 'no_change' && (
            <div style={{ color:'#555', fontSize:9 }}>
              Auto phase: <span style={{ color: fgColor(data.fear_greed.score) }}>
                {data.fear_greed.suggested_phase}
                {data.fear_greed.trend === 'rising' ? ' ↑' : data.fear_greed.trend === 'falling' ? ' ↓' : ''}
              </span>
            </div>
          )}
        </div>
      )}
```

- [ ] **Step 2: Verify manually**

Start both backend and frontend. Open the app. The sidebar should show a Fear & Greed block between VIX and ICB Sectors with:
- A large score number in the appropriate colour
- A sentiment badge
- A thin progress bar
- An "Auto phase" line if suggested_phase is not `no_change`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.js
git commit -m "feat: add compact Fear & Greed block to sidebar"
```

---

## Task 5: BreadthTab.js — full Fear & Greed breakdown

**Files:**
- Modify: `frontend/src/components/BreadthTab.js`

- [ ] **Step 1: Add `FearGreedCard` component and updated fetch to `BreadthTab.js`**

Add `useState` to the existing import (it already has it) and add the `FearGreedCard` component before `BreadthGauge`:

```jsx
function fgColor(score) {
  if (score >= 75) return '#10b981';
  if (score >= 55) return '#f59e0b';
  if (score >= 45) return '#666';
  if (score >= 25) return '#f97316';
  return '#ef4444';
}

function FearGreedCard({ fg }) {
  if (!fg) return null;
  const color = fgColor(fg.score);
  const COMPONENT_ORDER = ['momentum', 'breadth', 'vix', 'safe_haven', 'hl_ratio'];
  return (
    <div style={{ background:'#111', border:'1px solid #1e1e1e', borderRadius:3, padding:16, marginBottom:16 }}>
      <div style={{ color:'#444', fontSize:9, textTransform:'uppercase', letterSpacing:'1.5px', marginBottom:12 }}>
        UK Fear &amp; Greed Index
      </div>

      {/* Score + sentiment */}
      <div style={{ display:'flex', alignItems:'flex-end', gap:16, marginBottom:10 }}>
        <div>
          <span style={{ color, fontSize:36, fontWeight:700, fontFamily:'monospace', lineHeight:1 }}>{fg.score}</span>
          <span style={{ color, fontSize:13, fontWeight:700, marginLeft:8 }}>{fg.sentiment?.toUpperCase()}</span>
        </div>
        <div style={{ color:'#555', fontSize:10, paddingBottom:4 }}>
          Trend: <span style={{ color: fg.trend === 'rising' ? '#10b981' : fg.trend === 'falling' ? '#ef4444' : '#666' }}>
            {fg.trend === 'rising' ? '↑ Rising' : fg.trend === 'falling' ? '↓ Falling' : '—'}
          </span>
          {fg.suggested_phase && fg.suggested_phase !== 'no_change' && (
            <> &nbsp;|&nbsp; Auto-phase: <span style={{ color }}>{fg.suggested_phase}</span>
            &nbsp;|&nbsp; Confirmed: <span style={{ color: fg.confirmed ? '#10b981' : '#555' }}>
              {fg.confirmed ? '2/2 readings' : '1/2 readings'}
            </span></>
          )}
        </div>
      </div>

      {/* Colour-banded progress bar */}
      <div style={{ position:'relative', height:6, borderRadius:3, marginBottom:16, background:'#1a1a1a', overflow:'hidden' }}>
        <div style={{ position:'absolute', left:'0%',  width:'25%', height:'100%', background:'#ef4444', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'25%', width:'20%', height:'100%', background:'#f97316', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'45%', width:'10%', height:'100%', background:'#666',    opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'55%', width:'20%', height:'100%', background:'#f59e0b', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:'75%', width:'25%', height:'100%', background:'#10b981', opacity:0.4 }}/>
        <div style={{ position:'absolute', left:`${fg.score}%`, transform:'translateX(-50%)', top:-2, width:3, height:10, background:'white', borderRadius:1 }}/>
      </div>

      {/* Component cards */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:6 }}>
        {COMPONENT_ORDER.map(key => {
          const c = fg.components?.[key];
          if (!c) return null;
          const cc = fgColor(c.score);
          return (
            <div key={key} style={{ background:'#141414', border:'1px solid #2a2a2a', borderRadius:2, padding:'8px 6px' }}>
              <div style={{ color:'#555', fontSize:8, marginBottom:4 }}>{c.label}</div>
              <div style={{ color:cc, fontSize:13, fontWeight:700, fontFamily:'monospace' }}>{c.score}</div>
              <div style={{ background:'#1a1a1a', borderRadius:1, height:3, margin:'4px 0' }}>
                <div style={{ background:cc, width:`${c.score}%`, height:3, borderRadius:1 }}/>
              </div>
              <div style={{ color:'#555', fontSize:8 }}>
                {c.score >= 75 ? 'Ext. Greed' : c.score >= 55 ? 'Greed' : c.score >= 45 ? 'Neutral' : c.score >= 25 ? 'Fear' : 'Ext. Fear'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update `BreadthTab` to fetch fear-greed and pass it to `FearGreedCard`**

Replace the existing `useState` and `useEffect` in `BreadthTab`:

```jsx
export default function BreadthTab({ refreshKey }) {
  const [data, setData]     = useState(null);
  const [fg, setFg]         = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetch(`${API}/market/breadth`).then(r => r.json()),
      fetch(`${API}/market/fear-greed`).then(r => r.json()),
    ]).then(([breadthData, fgData]) => {
      setData(breadthData);
      setFg(fgData);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [refreshKey]);
```

- [ ] **Step 3: Add `FearGreedCard` to the `BreadthTab` return**

In the `BreadthTab` return, add `<FearGreedCard fg={fg} />` immediately after the `<h2>` heading and before the existing 3-column grid:

```jsx
  return (
    <div>
      <h2 style={{ fontFamily:'monospace', fontSize:14, color:'#f97316', textTransform:'uppercase', letterSpacing:2, marginBottom:20 }}>Market Breadth</h2>
      <FearGreedCard fg={fg} />
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:16, marginBottom:16 }}>
        {/* ... rest of existing content unchanged ... */}
```

- [ ] **Step 4: Verify manually**

Open the Breadth tab. The Fear & Greed card should appear at the top showing:
- Large score + sentiment label
- Colour-banded bar with white marker at the score position
- Trend + auto-phase + confirmation status
- 5 component cards in a row

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BreadthTab.js
git commit -m "feat: add Fear & Greed full breakdown card to Breadth tab"
```
