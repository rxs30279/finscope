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
