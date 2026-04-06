from fastapi import APIRouter
import yfinance as yf
import time
import numpy as np
import pandas as pd
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    "Real Estate":            ["LAND.L", "SGRO.L", "BLND.L", "BBOX.L", "PCTN.L", "GPE.L"],
}

# FTSE 100 — used for breadth calculations
BREADTH_TICKERS = [
    # Top 50 by market cap
    "AZN.L",  "SHEL.L", "HSBA.L", "ULVR.L", "BP.L",
    "RIO.L",  "GSK.L",  "LSEG.L", "REL.L",  "DGE.L",
    "BATS.L", "GLEN.L", "LLOY.L", "BARC.L", "NG.L",
    "RKT.L",  "IMB.L",  "HLN.L",  "AAL.L",  "NWG.L",
    "TSCO.L", "SSE.L",  "AHT.L",  "BA.L",   "RR.L",
    "HLMA.L", "SGE.L",  "IHG.L",  "SN.L",   "HIK.L",
    "CPG.L",  "EXPN.L", "STAN.L", "IAG.L",  "ANTO.L",
    "PRU.L",  "ABF.L",  "WPP.L",  "BT-A.L", "AUTO.L",
    "FRES.L", "MNG.L",  "CNA.L",  "SVT.L",  "UU.L",
    "LAND.L", "SGRO.L", "BLND.L", "VOD.L",  "NXT.L",
    # FTSE 100 remainder
    "AV.L",   "LGEN.L", "ADM.L",  "III.L",  "ITRK.L",
    "CRDA.L", "RTO.L",  "WTB.L",  "JD.L",   "MKS.L",
    "SBRY.L", "MNDI.L", "EZJ.L",  "ENT.L",  "FLTR.L",
    "PSON.L", "SDR.L",  "PSN.L",  "TW.L",   "MRO.L",
    "IMI.L",  "WEIR.L", "SKG.L",  "RMV.L",  "GAW.L",
]

CROSS_ASSET_TICKERS = {
    "gbpusd":   "GBPUSD=X",
    "brent":    "BZ=F",
    "gold":     "GC=F",
}

VIX_TICKER = "^VIX"
GILT_ETF_TICKER = "IGLT.L"  # iShares UK Gilt ETF — used for safe haven spread & z-score

ALL_PROXY_TICKERS = list(dict.fromkeys(
    list(BENCHMARK_TICKERS.values()) +
    [t for tickers in SECTOR_TICKERS.values() for t in tickers] +
    BREADTH_TICKERS +
    list(CROSS_ASSET_TICKERS.values()) +
    [VIX_TICKER, GILT_ETF_TICKER]
))

# ── Shared price fetch (all proxy tickers, 1 year history, cached) ────────────
def _get_prices():
    def fetch():
        def _fetch_one(ticker):
            try:
                hist = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
                if hist.empty:
                    return ticker, None
                col = hist["Close"]
                if col.index.tz is not None:
                    col.index = col.index.tz_localize(None)
                return ticker, col
            except Exception:
                return ticker, None

        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(_fetch_one, t): t for t in ALL_PROXY_TICKERS}
            frames = {}
            for future in as_completed(futures):
                ticker, col = future.result()
                if col is not None:
                    frames[ticker] = col

        if not frames:
            print("[market] yfinance: no data returned for any ticker")
            return pd.DataFrame()
        return pd.DataFrame(frames)
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
def _zscore_to_score(series, current_val, clip=2.0):
    """Map current_val to 0-100 using z-score over series. Returns 50 on insufficient data."""
    if len(series) < 20:
        return 50
    mean = float(series.mean())
    std = float(series.std())
    if std == 0:
        return 50
    z = (current_val - mean) / std
    z = max(-clip, min(clip, z))
    return round((z + clip) / (2 * clip) * 100)

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

    # 2. Market Breadth — % basket stocks above 50-day MA, z-score normalised
    breadth_data = _compute_breadth()
    above_flags = {}
    for t in BREADTH_TICKERS:
        if t in prices.columns:
            col = prices[t].dropna()
            if len(col) >= 51:
                ma50 = col.rolling(50).mean()
                above_flags[t] = (col > ma50).astype(float)
    if above_flags:
        breadth_series = pd.DataFrame(above_flags).mean(axis=1).dropna()
        if len(breadth_series) >= 20:
            current_breadth = float(breadth_series.iloc[-1])
            components["breadth"] = {
                "score": _zscore_to_score(breadth_series, current_breadth),
                "label": "Market Breadth",
                "value": round(current_breadth * 100, 1),
            }
    if "breadth" not in components:
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

    # 4. Safe Haven Demand — 20-day return spread: FTSE 100 vs UK gilt ETF
    gilt_ticker = GILT_ETF_TICKER
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

    # 5. Realised Volatility — 20-day annualised vol of FTSE 100, inverted (high vol = fear = low score)
    if ftse_ticker in prices.columns:
        ftse = prices[ftse_ticker].dropna()
        if len(ftse) >= 22:
            log_returns = np.log(ftse / ftse.shift(1)).dropna()
            rv_series = log_returns.rolling(20).std().dropna() * np.sqrt(252)
            if len(rv_series) >= 20:
                current_rv = float(rv_series.iloc[-1])
                components["realised_vol"] = {
                    "score": _zscore_to_score(-rv_series, -current_rv, clip=3.0),
                    "label": "Realised Vol",
                    "value": round(current_rv * 100, 1),
                }
    if "realised_vol" not in components:
        components["realised_vol"] = {"score": 50, "label": "Realised Vol", "value": None}

    # 6. New Highs / Lows — % of stocks at 52w high minus % at 52w low, centred at 50
    new_highs    = breadth_data.get("new_highs", 0)
    new_lows     = breadth_data.get("new_lows", 0)
    hl_universe  = breadth_data.get("hl_universe", 0)
    if hl_universe > 0:
        hl_score = round(50 + ((new_highs - new_lows) / hl_universe) * 50)
        hl_score = max(0, min(100, hl_score))
    else:
        hl_score = 50
    components["hl_ratio"] = {
        "score": hl_score,
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

def _fetch_boe_gilt_yields():
    """Fetch UK nominal zero coupon gilt yields from Bank of England.
    - 5Y/10Y/20Y: BoE IADB API (single request, series IUDSNZC/IUDMNZC/IUDLNZC)
    - 2Y/30Y: BoE zip file (glcnominalddata.zip, sheet '4. spot curve')
    Returns {"snapshot": {2: float, 5: float, ...}, "history": [{date, y2, y5, y10, y20, y30}, ...]}
    """
    import io, zipfile

    IADB_URL = (
        "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
        "?csv.x=yes&Datefrom=01/Jan/2021&Dateto=31/Dec/2026"
        "&SeriesCodes=IUDSNZC,IUDMNZC,IUDLNZC&CSVF=TT&UsingCodes=Y&VPD=Y&VFD=N"
    )
    ZIP_URL = (
        "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip"
    )
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    # ── IADB: 5Y, 10Y, 20Y ───────────────────────────────────────────────────
    iadb_data = {5: {}, 10: {}, 20: {}}
    try:
        r = requests.get(IADB_URL, timeout=20, headers=HEADERS)
        r.raise_for_status()
        lines = r.text.splitlines()
        # Find the data section (after blank line separator)
        data_start = 0
        for i, line in enumerate(lines):
            if line.strip() == "":
                data_start = i + 1
                break
        if data_start == 0:
            data_start = 1  # fallback: skip just the header row

        col_map = {}  # column_index -> maturity
        for i, line in enumerate(lines[data_start:]):
            parts = [p.strip().strip('"') for p in line.split(",")]
            if i == 0:
                # Header row: DATE, IUDSNZC, IUDMNZC, IUDLNZC
                for j, col in enumerate(parts):
                    if col == "IUDSNZC":  col_map[j] = 5
                    elif col == "IUDMNZC": col_map[j] = 10
                    elif col == "IUDLNZC": col_map[j] = 20
                continue
            if len(parts) < 2 or not parts[0]:
                continue
            try:
                dt = datetime.strptime(parts[0], "%d %b %Y")
                date_str = dt.strftime("%Y-%m-%d")
                for j, maturity in col_map.items():
                    if j < len(parts) and parts[j]:
                        try:
                            iadb_data[maturity][date_str] = float(parts[j])
                        except ValueError:
                            pass
            except ValueError:
                continue
    except Exception as e:
        print(f"[market] BoE IADB gilt fetch failed: {e}")

    # ── Zip: 2Y and 30Y ──────────────────────────────────────────────────────
    zip_data = {2: {}, 30: {}}
    try:
        import openpyxl
        r = requests.get(ZIP_URL, timeout=60, headers=HEADERS)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        # Find the most recent xlsx file
        xlsx_names = sorted([n for n in zf.namelist() if n.endswith(".xlsx")])
        if not xlsx_names:
            raise ValueError("No xlsx files found in zip")
        latest = xlsx_names[-1]
        wb = openpyxl.load_workbook(io.BytesIO(zf.read(latest)), read_only=True, data_only=True)
        ws = wb["4. spot curve"]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise ValueError("Empty sheet")
        # Row 0 is header — find columns for 2.0 and 30.0 years
        header = rows[0]
        col_2y  = next((i for i, h in enumerate(header) if h is not None and abs(float(h) - 2.0)  < 0.01), None) if any(isinstance(h, (int, float)) for h in header) else None
        col_30y = next((i for i, h in enumerate(header) if h is not None and abs(float(h) - 30.0) < 0.01), None) if any(isinstance(h, (int, float)) for h in header) else None
        for row in rows[1:]:
            if not row or row[0] is None:
                continue
            try:
                # Date column (column 0) may be a datetime object or string
                cell_date = row[0]
                if hasattr(cell_date, "strftime"):
                    date_str = cell_date.strftime("%Y-%m-%d")
                else:
                    dt = datetime.strptime(str(cell_date).strip(), "%Y-%m-%d")
                    date_str = dt.strftime("%Y-%m-%d")
                # Only keep last 5 years
                if date_str < "2021-01-01":
                    continue
                if col_2y is not None and col_2y < len(row) and row[col_2y] is not None:
                    try:
                        zip_data[2][date_str] = float(row[col_2y])
                    except (ValueError, TypeError):
                        pass
                if col_30y is not None and col_30y < len(row) and row[col_30y] is not None:
                    try:
                        zip_data[30][date_str] = float(row[col_30y])
                    except (ValueError, TypeError):
                        pass
            except (ValueError, TypeError, AttributeError):
                continue
    except Exception as e:
        print(f"[market] BoE zip gilt fetch failed: {e}")

    # ── Merge all series ──────────────────────────────────────────────────────
    all_series = {
        2:  zip_data[2],
        5:  iadb_data[5],
        10: iadb_data[10],
        20: iadb_data[20],
        30: zip_data[30],
    }

    if not any(all_series.values()):
        return {"snapshot": {}, "history": []}

    # Snapshot: latest value per maturity
    snapshot = {}
    for maturity, rows_dict in all_series.items():
        if rows_dict:
            snapshot[maturity] = rows_dict[max(rows_dict.keys())]

    # History: list of {date, y2, y5, y10, y20, y30}
    all_dates = sorted(set(d for rows_dict in all_series.values() for d in rows_dict))
    history = []
    for date in all_dates:
        row = {"date": date}
        for m in [2, 5, 10, 20, 30]:
            row[f"y{m}"] = all_series[m].get(date)
        if any(v is not None for k, v in row.items() if k != "date"):
            history.append(row)

    return {"snapshot": snapshot, "history": history}

def _fetch_cnn_fg():
    """Fetch CNN Fear & Greed Index via the fear-and-greed PyPI package."""
    try:
        import fear_and_greed
        result = fear_and_greed.get()
        return {
            "value": round(float(result.value), 1),
            "description": result.description,
            "last_update": result.last_update.isoformat() if result.last_update else None,
        }
    except Exception as e:
        print(f"[market] CNN fear-greed fetch failed: {e}")
        return {"value": None, "description": None, "last_update": None}

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
        cnn_fg = _cached("cnn_fear_greed", _fetch_cnn_fg)
        fg = _cached("fear_greed", _compute_fear_greed)
        return {
            "benchmarks": benchmarks,
            "sectors": sectors,
            "vix": vix_level,
            "cnn_fear_greed": cnn_fg,
            "fear_greed": {
                "score":           fg["score"],
                "sentiment":       fg["sentiment"],
                "trend":           fg["trend"],
                "suggested_phase": fg["suggested_phase"],
            },
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
    all_basket_tickers = BREADTH_TICKERS

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
        "above_50ma": above_50,
        "below_50ma": total - above_50,
        "hl_universe": sum(1 for t in all_basket_tickers if t in prices.columns and len(prices[t].dropna()) >= 252),
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
    gilt_ticker = GILT_ETF_TICKER
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
    brent  = _cross_asset_item(prices, t["brent"])
    gold   = _cross_asset_item(prices, t["gold"])
    zscore = _gilt_vs_utilities_zscore(prices)

    return {
        "gbpusd":            gbpusd,
        "brent":             brent,
        "gold":              gold,
        "gilt_vs_utilities": {"zscore": zscore, "bias": "Gilts expensive vs Utilities" if zscore is not None and zscore < -1 else None},
    }

@router.get("/cross-asset")
def cross_asset():
    return _cached("cross_asset", _compute_cross_asset)

@router.get("/gilt-yields")
def gilt_yields():
    return _cached("gilt_yields", _fetch_boe_gilt_yields)

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
