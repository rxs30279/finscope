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
