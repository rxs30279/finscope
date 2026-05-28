"""Breakout screener — algorithm computation engine.

Computes 6 independent breakout algorithms for ~600 stocks, combines into a
composite score, and stores daily snapshots in Supabase for backtesting.

Algorithm families (from breakout.md):
  1. Price-Level Breakouts  — new N-day highs
  2. Consolidation/Range    — Bollinger squeeze, ATR compression
  3. Volume-Confirmed       — volume ratio, declining volume during base
  4. MA Breakouts           — price vs MA, golden cross
  5. Volatility-Adjusted    — Donchian/Keltner channel breakouts
  6. Z-Score                — statistical outlier detection
"""

import math
import time
import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from dotenv import load_dotenv

from _mem import snapshot as _mem

# Import query and _get_pool — works both when running from backend/ dir
# and when running from project root (e.g. python -c "from backend.breakout import ...")
try:
    from prices import query, _get_pool
except ModuleNotFoundError:
    from backend.prices import query, _get_pool

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter()

# ── Constants ──────────────────────────────────────────────────────────────────

LOOKBACK_DAYS = 60  # minimum history needed for 20-day windows + consolidation
MIN_HISTORY = 30  # skip stocks with fewer than this many rows

# Composite score weights (from breakout.md 6-layer screen)
LAYER_WEIGHTS = {
    "trend_filter": 0.15,  # Layer 1: Price > 200-day MA
    "consolidation": 0.20,  # Layer 2: BB width < 25th percentile
    "accumulation": 0.20,  # Layer 3: OBV/VPT rising while price flat
    "money_flow": 0.20,  # Layer 4: CMF positive and rising
    "breakout_trigger": 0.15,  # Layer 5: Close > 20-day high
    "volume_confirm": 0.10,  # Layer 6: Volume ratio > 1.5x, MFI rising
}

# Layer thresholds (from breakout.md)
TREND_MA_PERIOD = 200
CONSOLIDATION_PCTILE_THRESHOLD = 25  # BB width below this = compressed
VOLUME_RATIO_THRESHOLD = 1.5
MFI_RISING_THRESHOLD = 50  # MFI above this on breakout day


# ── Helper: DB connection ─────────────────────────────────────────────────────


def _execute(sql, params=None):
    """Execute a write query and commit."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _fetch_all(sql, params=None):
    """Fetch rows as list of dicts."""
    return query(sql, params)


# ── Indicator Computation ─────────────────────────────────────────────────────


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to a DataFrame with columns:
    date, open, high, low, close, volume (sorted by date ascending).
    Returns the same DataFrame with new columns added.
    """
    d = df.copy()
    close = d["close"]
    high = d["high"]
    low = d["low"]
    volume = d["volume"]

    # ── Moving Averages ──
    d["ma_20"] = close.rolling(20).mean()
    d["ma_50"] = close.rolling(50).mean()
    d["ma_200"] = close.rolling(200).mean()

    # ── N-day highs (using .shift(1) to avoid lookahead bias) ──
    d["high_20"] = high.rolling(20).max().shift(1)
    d["high_52"] = high.rolling(52).max().shift(1)

    # ── Bollinger Bands (20,2) ──
    bb_std = close.rolling(20).std()
    d["bb_upper"] = d["ma_20"] + 2 * bb_std
    d["bb_lower"] = d["ma_20"] - 2 * bb_std
    d["bb_width"] = (d["bb_upper"] - d["bb_lower"]) / d["ma_20"]

    # ── ATR (Average True Range, 14) ──
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    d["atr"] = tr.rolling(14).mean()

    # ── Volume metrics ──
    d["volume_ma_20"] = volume.rolling(20).mean()
    d["volume_ratio"] = volume / d["volume_ma_20"]

    # ── On-Balance Volume (OBV) ──
    obv = (volume * ((close.diff() > 0).astype(int) * 2 - 1)).cumsum()
    d["obv"] = obv
    # OBV trend over last 10 days
    d["obv_slope"] = obv.diff(10) / obv.rolling(10).mean().replace(0, np.nan)

    # ── Chaikin Money Flow (CMF, 20) ──
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    d["cmf"] = (mfm * volume).rolling(20).sum() / volume.rolling(20).sum()

    # ── Money Flow Index (MFI, 14) ──
    typical_price = (high + low + close) / 3
    raw_money_flow = typical_price * volume
    pos_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0)
    neg_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0)
    pos_mf = pos_flow.rolling(14).sum()
    neg_mf = neg_flow.rolling(14).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    d["mfi"] = 100 - (100 / (1 + mfr))

    # ── Volume Price Trend (VPT) ──
    pct_change = close.pct_change()
    d["vpt"] = (volume * pct_change).cumsum()
    d["vpt_slope"] = d["vpt"].diff(10) / d["vpt"].rolling(10).mean().replace(0, np.nan)

    # ── Donchian Channels (20) ──
    d["donchian_upper"] = high.rolling(20).max()
    d["donchian_lower"] = low.rolling(20).min()

    # ── Keltner Channels (ATR-based) ──
    d["keltner_upper"] = d["ma_20"] + 1.5 * d["atr"]
    d["keltner_lower"] = d["ma_20"] - 1.5 * d["atr"]

    # ── Z-Score of returns ──
    returns = close.pct_change()
    d["returns_mean_20"] = returns.rolling(20).mean()
    d["returns_std_20"] = returns.rolling(20).std()
    d["z_score"] = (returns - d["returns_mean_20"]) / d["returns_std_20"].replace(
        0, np.nan
    )

    # ── NR7 / NR4 pattern (narrowest range in last N days) ──
    d["range"] = high - low
    d["nr7"] = d["range"] == d["range"].rolling(7).min()
    d["nr4"] = d["range"] == d["range"].rolling(4).min()

    return d


# ── Algorithm Scoring Functions ────────────────────────────────────────────────


def _score_price_level(row: pd.Series) -> tuple:
    """Score 0-100 for price-level breakout.
    - Close above 20-day high (shifted): 60 pts
    - Close above 52-day high (shifted): +20 pts
    - Close at new all-time high in window: +20 pts
    """
    score = 0.0
    close = row["close"]
    high_20 = row.get("high_20")
    high_52 = row.get("high_52")

    if high_20 is not None and not np.isnan(high_20) and close > high_20:
        score += 60
    if high_52 is not None and not np.isnan(high_52) and close > high_52:
        score += 40

    return min(100, score)


def _score_consolidation(row: pd.Series, bb_pctile: float, atr_pctile: float) -> float:
    """Score 0-100 for consolidation/range breakout.
    - BB width < 25th percentile: 40 pts
    - ATR < 25th percentile: 30 pts
    - NR7 or NR4 pattern: 30 pts
    """
    score = 0.0

    if bb_pctile is not None and bb_pctile <= CONSOLIDATION_PCTILE_THRESHOLD:
        score += 40
    if atr_pctile is not None and atr_pctile <= CONSOLIDATION_PCTILE_THRESHOLD:
        score += 30
    if row.get("nr7", False) or row.get("nr4", False):
        score += 30

    return min(100, score)


def _score_volume(row: pd.Series) -> float:
    """Score 0-100 for volume confirmation.
    - Volume ratio > 1.5x: 50 pts (scales up to 100 at 3x)
    - Volume declining over base (volume_ma_20 < volume_ma_50): 25 pts
    - Volume spike with no price move (accumulation): 25 pts
    """
    score = 0.0
    vr = row.get("volume_ratio")

    if vr is not None and not np.isnan(vr):
        if vr > 1.5:
            score += min(
                50, (vr - 1.5) / 1.5 * 50
            )  # scales 50-100 as ratio goes 1.5x-3x
        elif vr > 1.0:
            score += 10  # modest volume

    # Volume declining during base (volume MA20 < volume MA50)
    v20 = row.get("volume_ma_20")
    v50 = row.get("volume_ma_50")
    if v20 is not None and v50 is not None and not np.isnan(v20) and not np.isnan(v50):
        if v20 < v50:
            score += 25

    # Accumulation: volume spike but price didn't move much
    close_change = abs(row.get("close_pct_change", 0))
    if vr is not None and not np.isnan(vr) and vr > 1.5 and close_change < 0.01:
        score += 25

    return min(100, score)


def _score_ma_cross(row: pd.Series) -> float:
    """Score 0-100 for MA breakouts.
    - Price > 50-day MA: 30 pts
    - Price > 200-day MA: 30 pts
    - 50-day MA > 200-day MA (golden cross): 40 pts
    """
    score = 0.0
    close = row["close"]
    ma50 = row.get("ma_50")
    ma200 = row.get("ma_200")

    if ma50 is not None and not np.isnan(ma50) and close > ma50:
        score += 30
    if ma200 is not None and not np.isnan(ma200) and close > ma200:
        score += 30
    if (
        ma50 is not None
        and ma200 is not None
        and not np.isnan(ma50)
        and not np.isnan(ma200)
        and ma50 > ma200
    ):
        score += 40

    return min(100, score)


def _score_volatility(row: pd.Series) -> float:
    """Score 0-100 for volatility-adjusted breakouts.
    - Close above Donchian upper channel: 50 pts
    - Close above Keltner upper channel: 30 pts
    - Price breaking both channels: +20 pts
    """
    score = 0.0
    close = row["close"]
    donchian_u = row.get("donchian_upper")
    keltner_u = row.get("keltner_upper")

    if donchian_u is not None and not np.isnan(donchian_u) and close > donchian_u:
        score += 50
    if keltner_u is not None and not np.isnan(keltner_u) and close > keltner_u:
        score += 30
    if (
        donchian_u is not None
        and keltner_u is not None
        and not np.isnan(donchian_u)
        and not np.isnan(keltner_u)
        and close > donchian_u
        and close > keltner_u
    ):
        score += 20

    return min(100, score)


def _score_zscore(row: pd.Series) -> float:
    """Score 0-100 for statistical breakout.
    - Z-score > 2.0 (2 sigma event): 60 pts
    - Z-score > 1.5: 30 pts
    - Z-score > 3.0 (3 sigma event): +40 pts
    """
    z = row.get("z_score")
    if z is None or np.isnan(z):
        return 0.0

    if z > 3.0:
        return 100.0
    if z > 2.0:
        return 60.0
    if z > 1.5:
        return 30.0
    return 0.0


# ── Composite Score ────────────────────────────────────────────────────────────


def _compute_composite(scores: dict) -> tuple:
    """Compute weighted composite score and count layers passed.

    Args:
        scores: dict with keys 'price_level', 'consolidation', 'volume',
                'ma_cross', 'volatility', 'zscore' (each 0-100)

    Returns:
        (composite_score 0-100, layers_passed 0-6)
    """
    # Map algo names to layer names for threshold checking
    layer_map = {
        "price_level": "breakout_trigger",
        "consolidation": "consolidation",
        "volume": "volume_confirm",
        "ma_cross": "trend_filter",
        "volatility": "breakout_trigger",  # counts toward trigger
        "zscore": "breakout_trigger",
    }

    # Layer thresholds (score >= 50 = layer passed)
    layers_passed = 0
    weighted_sum = 0.0
    weight_total = 0.0

    # Map each algo to its layer weight
    algo_layer_map = {
        "price_level": "breakout_trigger",
        "consolidation": "consolidation",
        "volume": "volume_confirm",
        "ma_cross": "trend_filter",
        "volatility": "breakout_trigger",
        "zscore": "breakout_trigger",
    }

    # Count unique layers passed
    passed_layers = set()
    for algo, layer in algo_layer_map.items():
        algo_score = scores.get(algo, 0)
        if algo_score >= 50:
            passed_layers.add(layer)

    # Weighted composite: each algo gets equal weight within its layer
    layer_scores = {}
    for algo, layer in algo_layer_map.items():
        layer_scores.setdefault(layer, []).append(scores.get(algo, 0))

    for layer, algo_scores in layer_scores.items():
        weight = LAYER_WEIGHTS.get(layer, 0)
        avg_algo_score = sum(algo_scores) / len(algo_scores)
        weighted_sum += weight * avg_algo_score
        weight_total += weight

    composite = round(weighted_sum / weight_total, 1) if weight_total > 0 else 0
    layers_passed = len(passed_layers)

    return composite, layers_passed


# ── Main Computation ──────────────────────────────────────────────────────────


def _compute_breakout_scores(target_date: date = None) -> list:
    """Compute breakout scores for all stocks on the given date.

    Fetches last 60 days of OHLCV from price_history, computes indicators,
    scores each algorithm, and returns a list of result dicts.

    Args:
        target_date: The date to score (defaults to latest available trading day)

    Returns:
        List of dicts with all breakout score fields
    """
    if target_date is None:
        target_date = date.today()

    _mem("breakout_compute", "start")

    # Fetch all symbols
    symbols = [
        r["symbol"]
        for r in _fetch_all("SELECT symbol FROM company_metadata ORDER BY symbol")
    ]

    if not symbols:
        logger.warning("No symbols found in company_metadata")
        return []

    # Fetch price history for last LOOKBACK_DAYS + buffer
    start_date = target_date - timedelta(days=LOOKBACK_DAYS + 10)
    rows = _fetch_all(
        """
        SELECT symbol, date, open, high, low, close, volume
        FROM price_history
        WHERE symbol = ANY(%s) AND date >= %s AND date <= %s
        ORDER BY symbol, date ASC
        """,
        (symbols, start_date, target_date),
    )

    _mem("breakout_compute", "history_fetched", n_symbols=len(symbols), n_rows=len(rows))

    if not rows:
        logger.warning("No price history found")
        return []

    # Group by symbol into DataFrames
    df_map = {}
    for r in rows:
        df_map.setdefault(r["symbol"], []).append(
            {
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["volume"]),
            }
        )

    _mem("breakout_compute", "df_map_built", n_groups=len(df_map))

    results = []
    for sym in symbols:
        if sym not in df_map:
            continue
        data = df_map[sym]
        if len(data) < MIN_HISTORY:
            continue

        df = pd.DataFrame(data)
        df = df.sort_values("date").reset_index(drop=True)

        # Find the target row index (latest date <= target_date)
        target_idx = df[df["date"] <= target_date].index.max()
        if target_idx is None or target_idx < MIN_HISTORY:
            continue

        # Compute indicators on full dataset
        df = _compute_indicators(df)

        # Get the target row
        row = df.iloc[target_idx]

        # Compute percentile ranks for BB width and ATR across the universe
        # (We'll compute these after collecting all rows)
        bb_width_val = row.get("bb_width")
        atr_val = row.get("atr")

        # Store raw data for percentile computation
        results.append(
            {
                "symbol": sym,
                "date": target_date,
                "close": float(row["close"]) if not np.isnan(row["close"]) else None,
                "volume": int(row["volume"]) if not np.isnan(row["volume"]) else None,
                "volume_ratio": (
                    round(float(row["volume_ratio"]), 2)
                    if not np.isnan(row.get("volume_ratio", np.nan))
                    else None
                ),
                "bb_width": (
                    float(bb_width_val)
                    if bb_width_val is not None and not np.isnan(bb_width_val)
                    else None
                ),
                "atr": (
                    float(atr_val)
                    if atr_val is not None and not np.isnan(atr_val)
                    else None
                ),
                "cmf_20d": (
                    round(float(row["cmf"]), 3)
                    if not np.isnan(row.get("cmf", np.nan))
                    else None
                ),
                "mfi_14d": (
                    round(float(row["mfi"]), 1)
                    if not np.isnan(row.get("mfi", np.nan))
                    else None
                ),
                "ma_50d": (
                    float(row["ma_50"])
                    if not np.isnan(row.get("ma_50", np.nan))
                    else None
                ),
                "ma_200d": (
                    float(row["ma_200"])
                    if not np.isnan(row.get("ma_200", np.nan))
                    else None
                ),
                "n_day_high_20": (
                    float(row["high_20"])
                    if not np.isnan(row.get("high_20", np.nan))
                    else None
                ),
                "z_score": (
                    round(float(row["z_score"]), 3)
                    if not np.isnan(row.get("z_score", np.nan))
                    else None
                ),
                "obv_slope": (
                    float(row["obv_slope"])
                    if not np.isnan(row.get("obv_slope", np.nan))
                    else None
                ),
                "vpt_slope": (
                    float(row["vpt_slope"])
                    if not np.isnan(row.get("vpt_slope", np.nan))
                    else None
                ),
                "close_pct_change": (
                    float(row.get("close", 0)) / float(df.iloc[target_idx - 1]["close"])
                    - 1
                    if target_idx > 0
                    else 0
                ),
                # Raw row for algo scoring
                "_row": row,
            }
        )

    # Compute percentile ranks for BB width and ATR across universe
    bb_widths = [r["bb_width"] for r in results if r["bb_width"] is not None]
    atrs = [r["atr"] for r in results if r["atr"] is not None]

    def _percentile_rank(value, sorted_list):
        if value is None or not sorted_list:
            return None
        count_less = sum(1 for v in sorted_list if v < value)
        return (count_less / len(sorted_list)) * 100

    # Score each result
    for r in results:
        row = r.pop("_row")  # remove raw row

        bb_pctile = _percentile_rank(r["bb_width"], bb_widths)
        atr_pctile = _percentile_rank(r["atr"], atrs)

        algo_scores = {
            "price_level": _score_price_level(row),
            "consolidation": _score_consolidation(row, bb_pctile, atr_pctile),
            "volume": _score_volume(row),
            "ma_cross": _score_ma_cross(row),
            "volatility": _score_volatility(row),
            "zscore": _score_zscore(row),
        }

        composite, layers_passed = _compute_composite(algo_scores)

        # OBV / VPT trend
        obv_s = r.get("obv_slope")
        vpt_s = r.get("vpt_slope")
        obv_trend = (
            "rising"
            if obv_s is not None and obv_s > 0.01
            else "falling" if obv_s is not None and obv_s < -0.01 else "flat"
        )
        vpt_trend = (
            "rising"
            if vpt_s is not None and vpt_s > 0.01
            else "falling" if vpt_s is not None and vpt_s < -0.01 else "flat"
        )

        r.update(
            {
                "algo_price_level": round(algo_scores["price_level"], 1),
                "algo_consolidation": round(algo_scores["consolidation"], 1),
                "algo_volume": round(algo_scores["volume"], 1),
                "algo_ma_cross": round(algo_scores["ma_cross"], 1),
                "algo_volatility": round(algo_scores["volatility"], 1),
                "algo_zscore": round(algo_scores["zscore"], 1),
                "breakout_score": composite,
                "layers_passed": layers_passed,
                "bb_width_pctile": (
                    round(bb_pctile, 2) if bb_pctile is not None else None
                ),
                "atr_pctile": round(atr_pctile, 2) if atr_pctile is not None else None,
                "obv_trend": obv_trend,
                "vpt_trend": vpt_trend,
            }
        )

        # Clean up temp fields
        r.pop("bb_width", None)
        r.pop("atr", None)
        r.pop("obv_slope", None)
        r.pop("vpt_slope", None)
        r.pop("close_pct_change", None)

    _mem("breakout_compute", "end", n_results=len(results))
    return results


# ── Helper: convert numpy types to native Python ──────────────────────────────


def _to_native(v):
    """Convert numpy types to native Python types for psycopg2 compatibility."""
    if v is None:
        return None
    if isinstance(v, (np.floating, np.float64, np.float32)):
        return float(v)
    if isinstance(v, (np.integer, np.int64, np.int32)):
        return int(v)
    if isinstance(v, (np.bool_)):
        return bool(v)
    return v


# ── Database Write ─────────────────────────────────────────────────────────────


def _upsert_scores(results: list) -> int:
    """Upsert breakout scores into breakout_scores table."""
    if not results:
        return 0

    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        import psycopg2.extras

        rows = []
        for r in results:
            rows.append(
                (
                    r["symbol"],
                    r["date"],
                    _to_native(r["algo_price_level"]),
                    _to_native(r["algo_consolidation"]),
                    _to_native(r["algo_volume"]),
                    _to_native(r["algo_ma_cross"]),
                    _to_native(r["algo_volatility"]),
                    _to_native(r["algo_zscore"]),
                    _to_native(r["breakout_score"]),
                    _to_native(r["layers_passed"]),
                    _to_native(r["close"]),
                    _to_native(r["volume"]),
                    _to_native(r["volume_ratio"]),
                    _to_native(r["bb_width_pctile"]),
                    _to_native(r["atr_pctile"]),
                    _to_native(r["cmf_20d"]),
                    _to_native(r["mfi_14d"]),
                    r["obv_trend"],
                    r["vpt_trend"],
                    _to_native(r["ma_50d"]),
                    _to_native(r["ma_200d"]),
                    _to_native(r["n_day_high_20"]),
                    _to_native(r["z_score"]),
                )
            )

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO breakout_scores
                (symbol, date, algo_price_level, algo_consolidation, algo_volume,
                 algo_ma_cross, algo_volatility, algo_zscore, breakout_score,
                 layers_passed, close, volume, volume_ratio, bb_width_pctile,
                 atr_pctile, cmf_20d, mfi_14d, obv_trend, vpt_trend,
                 ma_50d, ma_200d, n_day_high_20, z_score)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                algo_price_level    = EXCLUDED.algo_price_level,
                algo_consolidation  = EXCLUDED.algo_consolidation,
                algo_volume         = EXCLUDED.algo_volume,
                algo_ma_cross       = EXCLUDED.algo_ma_cross,
                algo_volatility     = EXCLUDED.algo_volatility,
                algo_zscore         = EXCLUDED.algo_zscore,
                breakout_score      = EXCLUDED.breakout_score,
                layers_passed       = EXCLUDED.layers_passed,
                close               = EXCLUDED.close,
                volume              = EXCLUDED.volume,
                volume_ratio        = EXCLUDED.volume_ratio,
                bb_width_pctile     = EXCLUDED.bb_width_pctile,
                atr_pctile          = EXCLUDED.atr_pctile,
                cmf_20d             = EXCLUDED.cmf_20d,
                mfi_14d             = EXCLUDED.mfi_14d,
                obv_trend           = EXCLUDED.obv_trend,
                vpt_trend           = EXCLUDED.vpt_trend,
                ma_50d              = EXCLUDED.ma_50d,
                ma_200d             = EXCLUDED.ma_200d,
                n_day_high_20       = EXCLUDED.n_day_high_20,
                z_score             = EXCLUDED.z_score
            """,
            rows,
            page_size=1000,
        )
        count = max(0, cur.rowcount)
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _upsert_signals(results: list) -> int:
    """Upsert breakout signals (only stocks with breakout_score >= 50)."""
    signals = [
        r
        for r in results
        if r["breakout_score"] is not None and r["breakout_score"] >= 50
    ]
    if not signals:
        return 0

    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        import psycopg2.extras

        rows = [
            (
                r["symbol"],
                r["date"],
                _to_native(r["breakout_score"]),
                _to_native(r["layers_passed"]),
            )
            for r in signals
        ]

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO breakout_signals (symbol, date, breakout_score, layers_passed)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                breakout_score  = EXCLUDED.breakout_score,
                layers_passed   = EXCLUDED.layers_passed
            """,
            rows,
            page_size=1000,
        )
        count = max(0, cur.rowcount)
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Backtesting ────────────────────────────────────────────────────────────────


def _compute_backtest(target_date: date = None) -> dict:
    """Compute forward returns for historical breakout signals.

    For each signal in breakout_signals, looks forward 5, 10, and 20 trading
    days and calculates the return. Stores results in breakout_backtest table.

    Args:
        target_date: Only compute for signals on this date (default: all uncomputed)

    Returns:
        dict with summary stats
    """
    if target_date is None:
        # Find signals that haven't been backtested yet
        signals = _fetch_all("""
            SELECT s.symbol, s.date, s.breakout_score, s.layers_passed
            FROM breakout_signals s
            LEFT JOIN breakout_backtest b ON b.signal_date = s.date AND b.symbol = s.symbol
            WHERE b.id IS NULL
            ORDER BY s.date DESC
            LIMIT 500
            """)
    else:
        signals = _fetch_all(
            """
            SELECT symbol, date, breakout_score, layers_passed
            FROM breakout_signals
            WHERE date = %s
            """,
            (target_date,),
        )

    if not signals:
        return {"signals_processed": 0, "message": "No unprocessed signals"}

    # Fetch price history for all relevant symbols
    symbols = list(set(s["symbol"] for s in signals))
    min_date = min(s["date"] for s in signals)
    max_date = max(s["date"] for s in signals)

    # Need forward-looking prices: fetch up to 30 extra days
    rows = _fetch_all(
        """
        SELECT symbol, date, close
        FROM price_history
        WHERE symbol = ANY(%s) AND date >= %s
        ORDER BY symbol, date ASC
        """,
        (symbols, min_date),
    )

    # Build price lookup: symbol -> [(date, close)]
    price_map = {}
    for r in rows:
        price_map.setdefault(r["symbol"], []).append((r["date"], float(r["close"])))

    backtest_rows = []
    for s in signals:
        sym = s["symbol"]
        sig_date = s["date"]
        prices = price_map.get(sym, [])
        if not prices:
            continue

        # Find signal date index
        idx = None
        for i, (d, _) in enumerate(prices):
            if d == sig_date:
                idx = i
                break
        if idx is None:
            continue

        signal_close = prices[idx][1]

        # Look forward 5, 10, 20 trading days
        fwd_5 = prices[idx + 5][1] if idx + 5 < len(prices) else None
        fwd_10 = prices[idx + 10][1] if idx + 10 < len(prices) else None
        fwd_20 = prices[idx + 20][1] if idx + 20 < len(prices) else None

        backtest_rows.append(
            (
                sig_date,
                sym,
                s["breakout_score"],
                s["layers_passed"],
                round((fwd_5 / signal_close - 1), 3) if fwd_5 else None,
                round((fwd_10 / signal_close - 1), 3) if fwd_10 else None,
                round((fwd_20 / signal_close - 1), 3) if fwd_20 else None,
            )
        )

    if not backtest_rows:
        return {"signals_processed": 0, "message": "Insufficient forward price data"}

    # Upsert
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        import psycopg2.extras

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO breakout_backtest
                (signal_date, symbol, breakout_score, layers_passed,
                 forward_5d, forward_10d, forward_20d)
            VALUES %s
            """,
            backtest_rows,
            page_size=500,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

    # Compute summary stats
    stats = _fetch_all(
        """
        SELECT
            COUNT(*) AS total,
            ROUND(AVG(forward_5d)::numeric, 4) AS avg_5d,
            ROUND(AVG(forward_10d)::numeric, 4) AS avg_10d,
            ROUND(AVG(forward_20d)::numeric, 4) AS avg_20d,
            ROUND(SUM(CASE WHEN forward_5d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_5d,
            ROUND(SUM(CASE WHEN forward_10d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_10d,
            ROUND(SUM(CASE WHEN forward_20d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_20d
        FROM breakout_backtest
        WHERE signal_date IN (SELECT date FROM breakout_signals WHERE date >= %s)
        """,
        (min_date,),
    )

    return {
        "signals_processed": len(backtest_rows),
        "stats": stats[0] if stats else None,
    }


# ── Backfill ───────────────────────────────────────────────────────────────────


def _backfill_breakout_scores(days: int = 60) -> dict:
    """Compute breakout scores for the last N trading days.

    Useful for initial population and backtesting history.
    """
    # Get distinct dates from price_history
    dates = _fetch_all(
        """
        SELECT DISTINCT date FROM price_history
        WHERE date >= CURRENT_DATE - %s::integer
        ORDER BY date DESC
        """,
        (days,),
    )

    if not dates:
        return {"dates_processed": 0, "message": "No price history found"}

    processed = 0
    total = len(dates)
    for i, d in enumerate(dates):
        dt = d["date"]
        logger.info("Backfilling breakout scores for %s (%d/%d)", dt, i + 1, total)
        try:
            results = _compute_breakout_scores(dt)
            if results:
                _upsert_scores(results)
                _upsert_signals(results)
                processed += 1
        except Exception as e:
            logger.error("Backfill failed for %s: %s", dt, e)

    return {
        "dates_processed": processed,
        "total_dates": total,
        "message": f"Processed {processed}/{total} dates",
    }


# ── API Endpoints ──────────────────────────────────────────────────────────────


@router.post("/api/breakout/run")
def run_breakout():
    """Compute breakout scores for all stocks on the latest trading day.

    Called by cron-job.org after the daily price refresh.
    Runs synchronously — fetches price history, computes indicators, upserts.
    """
    t0 = time.time()
    logger.info("Breakout computation starting")

    try:
        results = _compute_breakout_scores()
        if not results:
            return {
                "status": "ok",
                "stocks_processed": 0,
                "signals": 0,
                "duration_seconds": round(time.time() - t0, 1),
                "message": "No stocks processed",
            }

        scores_count = _upsert_scores(results)
        signals_count = _upsert_signals(results)

        # Run backtest for today's signals
        backtest_result = _compute_backtest()

        return {
            "status": "ok",
            "stocks_processed": len(results),
            "signals": signals_count,
            "duration_seconds": round(time.time() - t0, 1),
            "backtest": backtest_result,
        }
    except Exception as e:
        logger.error("Breakout computation failed: %s", e)
        import traceback

        traceback.print_exc()
        return {"status": "error", "error": str(e)}


@router.post("/api/breakout/backfill")
def run_backfill(days: int = Query(60, ge=1, le=365)):
    """Backfill breakout scores for the last N trading days.

    Useful for initial population and to generate backtesting history.
    """
    t0 = time.time()
    result = _backfill_breakout_scores(days)
    result["duration_seconds"] = round(time.time() - t0, 1)
    return result


@router.get("/api/breakout/signals")
def get_signals(
    target_date_str: Optional[str] = None,
    min_score: Optional[float] = Query(None, ge=0, le=100),
    min_layers: Optional[int] = Query(None, ge=1, le=6),
    sector: Optional[str] = None,
    ftse_index: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Return today's breakout signals with company metadata."""
    target_date = target_date_str if target_date_str else date.today().isoformat()

    wheres = ["s.date = %s"]
    params = [target_date]

    if min_score is not None:
        wheres.append("s.breakout_score >= %s")
        params.append(min_score)
    if min_layers is not None:
        wheres.append("s.layers_passed >= %s")
        params.append(min_layers)

    join_clause = ""
    if sector or ftse_index:
        join_clause = "JOIN company_metadata m ON m.symbol = s.symbol"
        if sector:
            wheres.append("m.sector = %s")
            params.append(sector)
        if ftse_index:
            if ftse_index == "FTSE 350":
                wheres.append("m.ftse_index IN ('FTSE 100', 'FTSE 250')")
            elif ftse_index == "FTSE All-Share":
                wheres.append(
                    "m.ftse_index IN ('FTSE 100', 'FTSE 250', 'FTSE SmallCap')"
                )
            else:
                wheres.append("m.ftse_index = %s")
                params.append(ftse_index)

    params.append(limit)
    sql = f"""
        SELECT s.symbol, s.date, s.breakout_score, s.layers_passed,
               sc.algo_price_level, sc.algo_consolidation, sc.algo_volume,
               sc.algo_ma_cross, sc.algo_volatility, sc.algo_zscore,
               sc.close, sc.volume, sc.volume_ratio,
               sc.bb_width_pctile, sc.atr_pctile, sc.cmf_20d, sc.mfi_14d,
               sc.obv_trend, sc.vpt_trend,
               sc.ma_50d, sc.ma_200d, sc.n_day_high_20, sc.z_score,
               m.name, m.sector AS company_sector, m.ftse_index, m.exchange
        FROM breakout_signals s
        JOIN breakout_scores sc ON sc.symbol = s.symbol AND sc.date = s.date
        LEFT JOIN company_metadata m ON m.symbol = s.symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY s.breakout_score DESC
        LIMIT %s
    """
    return _fetch_all(sql, params)


@router.get("/api/breakout/history/{symbol}")
def get_breakout_history(symbol: str, days: int = Query(60, ge=1, le=365)):
    """Return historical breakout scores for a single symbol."""
    rows = _fetch_all(
        """
        SELECT date, breakout_score, layers_passed,
               algo_price_level, algo_consolidation, algo_volume,
               algo_ma_cross, algo_volatility, algo_zscore,
               close, volume_ratio, cmf_20d, mfi_14d,
               bb_width_pctile, atr_pctile, obv_trend, vpt_trend
        FROM breakout_scores
        WHERE symbol = %s AND date >= CURRENT_DATE - %s::integer
        ORDER BY date ASC
        """,
        (symbol, days),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No breakout history found")
    return rows


@router.get("/api/breakout/summary")
def get_breakout_summary(target_date_str: Optional[str] = None):
    """Return aggregate breakout stats for a given date."""
    target_date = target_date_str if target_date_str else date.today().isoformat()

    stats = _fetch_all(
        """
        SELECT
            COUNT(*) AS total_signals,
            ROUND(AVG(breakout_score)::numeric, 1) AS avg_score,
            MAX(breakout_score) AS max_score,
            ROUND(AVG(layers_passed)::numeric, 1) AS avg_layers,
            COUNT(*) FILTER (WHERE layers_passed >= 4) AS strong_signals,
            COUNT(*) FILTER (WHERE layers_passed >= 2 AND layers_passed < 4) AS moderate_signals
        FROM breakout_signals
        WHERE date = %s
        """,
        (target_date,),
    )

    # Layer breakdown
    layer_stats = _fetch_all(
        """
        SELECT
            ROUND(AVG(algo_price_level)::numeric, 1) AS avg_price_level,
            ROUND(AVG(algo_consolidation)::numeric, 1) AS avg_consolidation,
            ROUND(AVG(algo_volume)::numeric, 1) AS avg_volume,
            ROUND(AVG(algo_ma_cross)::numeric, 1) AS avg_ma_cross,
            ROUND(AVG(algo_volatility)::numeric, 1) AS avg_volatility,
            ROUND(AVG(algo_zscore)::numeric, 1) AS avg_zscore
        FROM breakout_scores
        WHERE date = %s
        """,
        (target_date,),
    )

    # Backtest summary
    backtest_stats = _fetch_all(
        """
        SELECT
            COUNT(*) AS total_backtested,
            ROUND(AVG(forward_5d)::numeric, 4) AS avg_5d_return,
            ROUND(AVG(forward_10d)::numeric, 4) AS avg_10d_return,
            ROUND(AVG(forward_20d)::numeric, 4) AS avg_20d_return,
            ROUND(SUM(CASE WHEN forward_5d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_5d,
            ROUND(SUM(CASE WHEN forward_10d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_10d,
            ROUND(SUM(CASE WHEN forward_20d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_20d
        FROM breakout_backtest
        """,
    )

    return {
        "date": target_date,
        "stats": stats[0] if stats else None,
        "layer_stats": layer_stats[0] if layer_stats else None,
        "backtest": backtest_stats[0] if backtest_stats else None,
    }


@router.get("/api/breakout/backtest")
def get_backtest_results(
    min_score: Optional[float] = Query(None, ge=0, le=100),
    limit: int = Query(100, ge=1, le=500),
):
    """Return backtest results, optionally filtered by breakout score."""
    wheres = ["1=1"]
    params = []
    if min_score is not None:
        wheres.append("b.breakout_score >= %s")
        params.append(min_score)
    params.append(limit)

    rows = _fetch_all(
        f"""
        SELECT b.signal_date, b.symbol, b.breakout_score, b.layers_passed,
               b.forward_5d, b.forward_10d, b.forward_20d,
               m.name, m.sector
        FROM breakout_backtest b
        LEFT JOIN company_metadata m ON m.symbol = b.symbol
        WHERE {' AND '.join(wheres)}
        ORDER BY b.signal_date DESC, b.breakout_score DESC
        LIMIT %s
        """,
        params,
    )
    return rows


@router.get("/api/breakout/backtest/stats")
def get_backtest_summary():
    """Return aggregate backtest statistics grouped by score range."""
    rows = _fetch_all("""
        SELECT
            CASE
                WHEN breakout_score >= 80 THEN '80-100'
                WHEN breakout_score >= 60 THEN '60-80'
                WHEN breakout_score >= 40 THEN '40-60'
                ELSE '0-40'
            END AS score_range,
            COUNT(*) AS total,
            ROUND(AVG(forward_5d)::numeric, 4) AS avg_5d,
            ROUND(AVG(forward_10d)::numeric, 4) AS avg_10d,
            ROUND(AVG(forward_20d)::numeric, 4) AS avg_20d,
            ROUND(SUM(CASE WHEN forward_5d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_5d,
            ROUND(SUM(CASE WHEN forward_10d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_10d,
            ROUND(SUM(CASE WHEN forward_20d > 0 THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0), 4) AS win_rate_20d
        FROM breakout_backtest
        GROUP BY score_range
        ORDER BY score_range
        """)
    return rows
