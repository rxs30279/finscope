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
    "FTSE 250":  "^FTMC",
    "All-Share":  "^FTAS",
}

# 2 representative stocks per ICB sector — basket average used as sector proxy
SECTOR_TICKERS = {
    "Energy":                 ["SHEL.L", "BP.L", "HBR.L"],
    "Financials":             ["HSBA.L", "LLOY.L", "BARC.L", "NWG.L", "LSEG.L"],
    "Industrials":            ["RR.L",   "BA.L",  "AHT.L",  "IAG.L"],
    "Materials":              ["RIO.L",  "GLEN.L","AAL.L",  "ANTO.L","FRES.L"],
    "Consumer Discretionary": ["CPG.L",  "NXT.L", "IHG.L",  "GAW.L", "KGF.L"],
    "Consumer Staples":       ["BATS.L", "ULVR.L","RKT.L",  "TSCO.L","DGE.L", "IMB.L"],
    "Health Care":            ["AZN.L",  "GSK.L", "HLN.L",  "SN.L",  "HIK.L"],
    "Technology":             ["REL.L",  "HLMA.L","SGE.L",  "AUTO.L","RMV.L"],
    "Telecommunications":     ["VOD.L",  "BT-A.L","AAF.L"],
    "Utilities":              ["NG.L",   "SSE.L", "CNA.L",  "SVT.L", "UU.L"],
    "Real Estate":            ["LAND.L", "SGRO.L", "BLND.L", "BBOX.L", "DELN.L", "GPE.L"],
}

CROSS_ASSET_TICKERS = {
    "gbpusd":   "GBPUSD=X",
    "gilt_10y": "^TNGBP",   # UK 10Y gilt — validate ticker on first run
    "brent":    "BZ=F",
    "gold":     "GC=F",
    "vftse":    "^VFTSE",
}

VIX_TICKER = "^VIX"

ALL_PROXY_TICKERS = (
    list(BENCHMARK_TICKERS.values()) +
    [t for tickers in SECTOR_TICKERS.values() for t in tickers] +
    list(CROSS_ASSET_TICKERS.values()) +
    [VIX_TICKER]
)

# ── Shared price fetch (all proxy tickers, 1 year history, cached) ────────────
def _get_prices():
    def fetch():
        try:
            import pandas as pd
            df = yf.download(
                ALL_PROXY_TICKERS, period="1y",
                progress=False, auto_adjust=True, threads=True
            )["Close"]
            # yf.download returns MultiIndex columns when multiple tickers;
            # single ticker returns a Series — normalise to DataFrame
            if hasattr(df, "columns") and not isinstance(df.columns, str):
                return df
            return df.to_frame()
        except Exception as e:
            import pandas as pd
            print(f"[market] yfinance download failed: {e}")
            return pd.DataFrame()
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

# ── Fear & Greed state ────────────────────────────────────────────────────────
_fg_history: list = []  # last 4 readings: [{score, suggested_phase, timestamp}, ...]

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

# ── Helper functions ──────────────────────────────────────────────────────────
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
        vix_col = prices[VIX_TICKER].dropna() if VIX_TICKER in prices.columns else None
        vix_level = round(float(vix_col.iloc[-1]), 2) if vix_col is not None and len(vix_col) else None
        return {
            "benchmarks": benchmarks,
            "sectors": sectors,
            "vix": vix_level,
            "signal_summary": {
                "cycle_phase": _cycle["phase"],
                "top_rs_sector": top_rs,
                "breadth": avg_breadth,
            },
        }
    return _cached("sidebar", compute)

@router.get("/rotation")
def rotation():
    return _cached("rotation", _compute_rotation)

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
    if vftse.get("value") is not None:
        vftse["bias"] = "Low Vol — Risk-On" if vftse["value"] < 20 else ("High Vol — Risk-Off" if vftse["value"] > 30 else "Neutral")
    else:
        vftse["bias"] = None

    if gilt.get("pct_change") is not None:
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

@router.get("/fear-greed")
def fear_greed():
    return _cached("fear_greed", _compute_fear_greed)

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
