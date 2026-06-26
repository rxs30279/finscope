from fastapi import APIRouter, Response
import os
import tempfile
import threading
import time
import numpy as np
import pandas as pd
import requests
import psycopg2.extras
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# Reuse prices.py's connection pool + read helper rather than opening a second
# pool — market.py only touches the DB for the Fear & Greed history table.
from prices import query as _db_query, _get_pool as _db_pool

router = APIRouter(prefix="/api/market", tags=["market"])

# ── In-memory cache (key → (data, timestamp)) ─────────────────────────────────
# Default TTL for the genuinely intraday-live endpoints (Fear & Greed, rotation,
# breadth, cross-asset…) whose underlying daily Close tracks the live price and
# is meant to move through the trading day. Endpoints backed by data that changes
# at most daily/monthly (BoE gilts, ONS macro, the F&G history table) override it
# with a longer per-key TTL below.
_cache: dict = {}
CACHE_TTL = 900           # 15 minutes — live intraday endpoints
CACHE_TTL_LIVE_OPEN = 120 # 2 minutes — sidebar live frame while the LSE is open
CACHE_TTL_HOURLY = 3600   # 1 hour — daily-changing data (gilts, F&G history table)
CACHE_TTL_DAILY = 86400   # 24 hours — monthly-changing data (ONS macro)

# Per-key locks (single-flight) so a burst of concurrent requests for the same
# key collapses to ONE computation instead of stampeding the (expensive) Yahoo
# fetch. `_locks_guard` only protects the small lock/refresh bookkeeping dicts.
_cache_locks: dict = {}
_refreshing: set = set()
_locks_guard = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _cache_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _cache_locks[key] = lock
        return lock


def _maybe_refresh_async(key: str, fn):
    """Recompute `key` in a background daemon thread, off the request path. Used
    by the stale-while-revalidate path so a stale-but-usable entry is served
    instantly while the refresh happens behind it. At most one refresh per key
    runs at a time. A failed/empty refresh never clobbers the existing entry."""
    with _locks_guard:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _run():
        try:
            data = fn()
            if data is None or (hasattr(data, "empty") and data.empty):
                return  # don't overwrite a good entry with a failed/empty fetch
            _cache[key] = (data, time.time())
        except Exception as e:
            print(f"[market] background refresh failed for {key}: {e}")
        finally:
            with _locks_guard:
                _refreshing.discard(key)

    threading.Thread(target=_run, name=f"refresh-{key}", daemon=True).start()


def _cached(key: str, fn, ttl: int = CACHE_TTL, swr: bool = False):
    """Cache `fn()` under `key` for `ttl` seconds.

    swr=True (stale-while-revalidate): once an entry exists, a stale read returns
    the old value immediately and refreshes in the background — so callers never
    block on the recompute. A missing entry (cold worker) still computes
    synchronously under the single-flight lock. swr=False keeps the old behaviour
    (stale → synchronous recompute), still de-duplicated by the lock."""
    now = time.time()
    entry = _cache.get(key)
    if entry is not None and now - entry[1] < ttl:
        return entry[0]
    if entry is not None and swr:
        _maybe_refresh_async(key, fn)
        return entry[0]
    # Missing, or stale without SWR → compute under single-flight, re-checking the
    # cache after acquiring the lock in case another thread just filled it.
    lock = _key_lock(key)
    with lock:
        entry = _cache.get(key)
        if entry is not None and time.time() - entry[1] < ttl:
            return entry[0]
        data = fn()
        _cache[key] = (data, time.time())
        return data


# ── On-disk price snapshots ───────────────────────────────────────────────────
# The shared price frames are the one genuinely slow input (a live multi-hundred-
# ticker Yahoo fetch). Persisting them to disk lets a freshly-started worker seed
# its in-memory cache from a recent snapshot — turning a cold first request into a
# fast local read instead of a blocking Yahoo round-trip. The daily prices cron
# (run_prices.py → warm_price_snapshots) refreshes the snapshot after EOD prices
# land; live worker fetches also rewrite it. Path is shared between the cron exec
# and the uvicorn workers (same container filesystem).
_SNAPSHOT_DIR = os.environ.get(
    "MARKET_SNAPSHOT_DIR",
    os.path.join(tempfile.gettempdir(), "finscope_market_cache"),
)


def _snapshot_path(name: str) -> str:
    return os.path.join(_SNAPSHOT_DIR, f"{name}.pkl")


def _save_snapshot(name: str, df) -> None:
    """Atomically persist a price DataFrame. Best-effort — failures are logged
    and swallowed (the snapshot is an optimisation, never a correctness input)."""
    if df is None or (hasattr(df, "empty") and df.empty):
        return
    try:
        os.makedirs(_SNAPSHOT_DIR, exist_ok=True)
        tmp = _snapshot_path(name) + ".tmp"
        df.to_pickle(tmp)
        os.replace(tmp, _snapshot_path(name))  # atomic on POSIX
    except Exception as e:
        print(f"[market] snapshot save failed for {name}: {e}")


def _load_snapshot(name: str):
    try:
        path = _snapshot_path(name)
        if os.path.exists(path):
            return pd.read_pickle(path)
    except Exception as e:
        print(f"[market] snapshot load failed for {name}: {e}")
    return None


def _cached_price_frame(key: str, fetch, ttl: int = CACHE_TTL):
    """Cache helper for the heavy shared price frames. Like _cached(swr=True) but
    seeds a cold (in-memory-missing) worker from the on-disk snapshot so the first
    request returns instantly instead of blocking on the live Yahoo fetch. A
    background refresh is kicked off to restore intraday liveness. With no snapshot
    on disk (very first deploy) it falls back to a synchronous single-flight fetch."""
    now = time.time()
    entry = _cache.get(key)
    if entry is not None and now - entry[1] < ttl:
        return entry[0]
    if entry is None:
        snap = _load_snapshot(key)
        if snap is not None and not snap.empty:
            _cache[key] = (snap, now)          # seed as fresh → instant response
            _maybe_refresh_async(key, fetch)   # pull live data behind it
            return snap
        return _cached(key, fetch)             # no snapshot → blocking fetch (once)
    # Stale → serve stale immediately, refresh in the background.
    _maybe_refresh_async(key, fetch)
    return entry[0]


def _lse_open(now=None):
    """True if the LSE is in a regular trading session right now (Mon–Fri,
    08:00–16:30 London). Mirrors _lse_open() in main.py / isLseOpen() in the
    frontend. Holidays aren't excluded — misjudging a holiday as "open" only
    forgoes the long closed-market cache (the data is static anyway), so it
    degrades to the faster refresh rather than serving wrong data."""
    try:
        from zoneinfo import ZoneInfo
        now = now or datetime.now(ZoneInfo("Europe/London"))
    except Exception:
        now = now or datetime.utcnow()  # London ≈ UTC; close enough for the gate
    if now.weekday() >= 5:  # Sat/Sun
        return False
    mins = now.hour * 60 + now.minute
    return 8 * 60 <= mins <= 16 * 60 + 30


def _live_ttl() -> int:
    """Cache TTL for the live sidebar data: short while the market is open (the
    figures move intraday on the ~15-min-delayed feed), long once closed (they're
    static until the next bell, so there's nothing fresher to fetch)."""
    return CACHE_TTL_LIVE_OPEN if _lse_open() else CACHE_TTL_HOURLY


# ── Ticker constants ───────────────────────────────────────────────────────────
BENCHMARK_TICKERS = {
    "FTSE 100": "^FTSE",
    "FTSE 250": "^FTMC",
    "All-Share": "^FTAS",
}

# Representative constituents per ICB sector — basket average used as sector proxy
SECTOR_TICKERS = {
    "Energy": ["SHEL.L", "BP.L", "HBR.L"],
    "Financials": [
        "HSBA.L",
        "LLOY.L",
        "BARC.L",
        "NWG.L",
        "LSEG.L",
        "STAN.L",
        "AV.L",
        "LGEN.L",
        "ADM.L",
        "MNG.L",
        "PRU.L",
        "SDR.L",
        "III.L",
    ],
    "Industrials": [
        "RR.L",
        "BA.L",
        "SMIN.L",  # Smiths Group — replaced AHT.L (Ashtead delisted from LSE, moved primary listing to the US)
        "IMI.L",
        "WEIR.L",
        "RTO.L",
        "ITRK.L",
        "MRO.L",
        "EXPN.L",
        "HLMA.L",
    ],
    "Consumer Discretionary": [
        "CPG.L",
        "NXT.L",
        "IHG.L",
        "GAW.L",
        "KGF.L",
        "JD.L",
        "MKS.L",
        "WTB.L",
        "EZJ.L",
        "ENT.L",
        "FLTR.L",
        "PSN.L",
        "TW.L",
        "WPP.L",
        "PSON.L",
        "IAG.L",
    ],
    "Materials": [
        "RIO.L",
        "GLEN.L",
        "AAL.L",
        "ANTO.L",
        "FRES.L",
        "MNDI.L",
        "CRDA.L",
    ],
    "Consumer Staples": [
        "BATS.L",
        "ULVR.L",
        "RKT.L",
        "TSCO.L",
        "DGE.L",
        "IMB.L",
        "SBRY.L",
        "ABF.L",
    ],
    "Health Care": ["AZN.L", "GSK.L", "HLN.L", "SN.L", "HIK.L"],
    "Technology": ["REL.L", "SGE.L", "AUTO.L", "RMV.L"],
    "Telecommunications": ["VOD.L", "BT-A.L", "AAF.L"],
    "Utilities": ["NG.L", "SSE.L", "CNA.L", "SVT.L", "UU.L"],
    "Real Estate": ["LAND.L", "SGRO.L", "BLND.L", "BBOX.L", "PCTN.L", "GPE.L"],
}

# FTSE 100 constituents — the breadth universe for the Breadth tab and the Fear &
# Greed breadth / new-highs-lows components. Sourced from company_metadata (kept current
# by the quarterly refresh_index_membership.py) so the list tracks index reshuffles
# instead of drifting; the hardcoded snapshot below is the fallback used only if the DB
# is unreachable. Regenerate the fallback periodically from the same query.
_BREADTH_TICKERS_FALLBACK = [
    "AAF.L", "AAL.L", "ABF.L", "ADM.L", "ALW.L", "ANTO.L", "AUTO.L", "AV.L", "AZN.L",
    "BA.L", "BAB.L", "BARC.L", "BATS.L", "BBOX.L", "BEZ.L", "BGEO.L", "BKG.L", "BLND.L",
    "BNZL.L", "BP.L", "BRBY.L", "BT-A.L", "BTRW.L", "CCEP.L", "CCH.L", "CNA.L", "CPG.L",
    "CRDA.L", "CTEC.L", "DCC.L", "DGE.L", "DPLM.L", "EDV.L", "ENT.L", "EXPN.L", "FCIT.L",
    "FRES.L", "GAW.L", "GLEN.L", "GSK.L", "HLMA.L", "HLN.L", "HSBA.L", "HSX.L", "HWDN.L",
    "IAG.L", "ICG.L", "IGG.L", "IHG.L", "III.L", "IMB.L", "IMI.L", "INF.L", "ITRK.L",
    "JD.L", "KGF.L", "LAND.L", "LGEN.L", "LLOY.L", "LMP.L", "LSEG.L", "MKS.L", "MNDI.L",
    "MNG.L", "MRO.L", "MTLN.L", "NG.L", "NWG.L", "NXT.L", "PCT.L", "PRU.L", "PSH.L",
    "PSN.L", "PSON.L", "REL.L", "RIO.L", "RKT.L", "RMV.L", "RR.L", "RTO.L", "SBRY.L",
    "SDLF.L", "SDR.L", "SGE.L", "SGRO.L", "SHEL.L", "SMIN.L", "SMT.L", "SN.L", "SPX.L",
    "SSE.L", "STAN.L", "STJ.L", "SVT.L", "TSCO.L", "ULVR.L", "UU.L", "VOD.L", "WEIR.L",
    "WTB.L",
]


def _load_breadth_tickers():
    """Active FTSE 100 symbols from company_metadata, falling back to the hardcoded
    snapshot if the DB is unreachable or returns an implausibly short list (a partial
    refresh shouldn't shrink the breadth universe). Evaluated once at import; backend
    processes are long-lived and re-import on restart, so this picks up reshuffles."""
    try:
        rows = _db_query(
            "SELECT symbol FROM company_metadata"
            " WHERE ftse_index = 'FTSE 100' AND is_active ORDER BY symbol"
        )
        syms = [r["symbol"] for r in rows]
        return syms if len(syms) >= 90 else list(_BREADTH_TICKERS_FALLBACK)
    except Exception:
        return list(_BREADTH_TICKERS_FALLBACK)


BREADTH_TICKERS = _load_breadth_tickers()

CROSS_ASSET_TICKERS = {
    "gbpusd": "GBPUSD=X",
    "brent": "BZ=F",
    "gold": "GC=F",
}

VIX_TICKER = "^VIX"
GILT_ETF_TICKER = "IGLT.L"  # iShares UK Gilt ETF — used for safe haven spread & z-score

# ONS timeseries JSON (no API key). d7g7/mm23 = CPI 12-month inflation rate;
# ihyq/pn2 = GDP QoQ first estimate (flash, ~4 weeks after quarter end);
# ihyq/qna = GDP QoQ revised (quarterly national accounts, ~3 months lag — fallback).
ONS_CPI_URL = "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data"
ONS_GDP_QOQ_URL          = "https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/ihyq/pn2/data"
ONS_GDP_QOQ_URL_FALLBACK = "https://www.ons.gov.uk/economy/grossdomesticproductgdp/timeseries/ihyq/qna/data"

ALL_PROXY_TICKERS = list(
    dict.fromkeys(
        list(BENCHMARK_TICKERS.values())
        + [t for tickers in SECTOR_TICKERS.values() for t in tickers]
        + BREADTH_TICKERS
        + list(CROSS_ASSET_TICKERS.values())
        + [VIX_TICKER, GILT_ETF_TICKER]
    )
)

# The subset of proxy tickers the SIDEBAR itself renders: benchmarks, sector
# baskets and VIX (~85 names) — everything EXCEPT the ~100 breadth tickers, which
# only feed Fear & Greed (separately cached at 15 min). Fetched as its own small
# frame so the sidebar can refresh fast intraday without dragging the full breadth
# universe through Yahoo each cycle.
SIDEBAR_LIVE_TICKERS = list(
    dict.fromkeys(
        list(BENCHMARK_TICKERS.values())
        + [t for tickers in SECTOR_TICKERS.values() for t in tickers]
        + [VIX_TICKER]
    )
)


# ── Shared price fetch (all proxy tickers, 1 year history, cached) ────────────
def _fetch_frame(tickers, snapshot_name, period="1y"):
    """Threaded live Yahoo fetch of `tickers` (Close series, `period` history),
    persisting a disk snapshot under `snapshot_name` on success. Shared by the full
    proxy frame and the smaller sidebar-live frame."""
    import yfinance as yf  # deferred — only this fetch path needs it

    def _fetch_one(ticker):
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if hist.empty:
                return ticker, None
            col = hist["Close"]
            if col.index.tz is not None:
                col.index = col.index.tz_localize(None)
            return ticker, col
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        frames = {}
        for future in as_completed(futures):
            ticker, col = future.result()
            if col is not None:
                frames[ticker] = col

    if not frames:
        print(f"[market] yfinance: no data returned for any ticker ({snapshot_name})")
        return pd.DataFrame()
    df = pd.DataFrame(frames)
    _save_snapshot(snapshot_name, df)
    return df


def _fetch_prices_frame():
    """Live Yahoo fetch of the full proxy universe (1y). Persists a disk snapshot
    on success. Module-level (not a closure) so the daily cron can force a fresh
    fetch via warm_price_snapshots() without going through the seeded cache."""
    return _fetch_frame(ALL_PROXY_TICKERS, "prices")


def _fetch_sidebar_frame():
    """Live Yahoo fetch of just the sidebar's benchmark/sector/VIX tickers (~85, a
    subset of ALL_PROXY_TICKERS). Refreshed on the fast market-hours TTL so the
    sidebar's intraday figures stay current without re-pulling the ~100 breadth
    tickers (those feed Fear & Greed, which is separately cached at 15 min)."""
    return _fetch_frame(SIDEBAR_LIVE_TICKERS, "sidebar_prices")


def _get_prices():
    return _cached_price_frame("prices", _fetch_prices_frame)


def _get_sidebar_prices():
    """Small live frame for the sidebar (benchmarks/sectors/VIX), refreshed on the
    fast market-hours TTL — ~2 min while the LSE is open, 1 h once closed."""
    return _cached_price_frame("sidebar_prices", _fetch_sidebar_frame, ttl=_live_ttl())


def _get_ftse_long():
    """2-year ^FTSE close history, cached separately. Used only for the momentum
    component so its scaling window covers a full year of gap readings (the 125-day MA
    eats the first ~6 months, leaving too few points in the shared 1y fetch)."""
    import yfinance as yf  # deferred — only this fetch path needs it
    def fetch():
        try:
            hist = yf.Ticker(BENCHMARK_TICKERS["FTSE 100"]).history(
                period="2y", auto_adjust=True
            )
            if hist.empty:
                return None
            col = hist["Close"]
            if col.index.tz is not None:
                col.index = col.index.tz_localize(None)
            return col
        except Exception:
            return None

    return _cached("ftse_long", fetch)


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


def _deviation_to_score(series, current_val, clip=2.0):
    """Map current_val to 0-100 centred on ZERO (not the trailing mean), scaled by the
    series' own volatility. Use for directional signals where the sign of current_val is
    itself meaningful — e.g. price above its MA should read as greed (>50), below as fear
    (<50), regardless of how extended it has been recently. Returns 50 on insufficient data."""
    if len(series) < 20:
        return 50
    std = float(series.std())
    if std == 0:
        return 50
    z = current_val / std
    z = max(-clip, min(clip, z))
    return round((z + clip) / (2 * clip) * 100)


def _pct_rank_to_score(series, current_val, min_obs=20):
    """Map current_val to 0-100 as its PERCENTILE within `series` (the trailing
    window), Hazen convention (strictly-less + half-equal) so ties land mid-band and
    the median maps to ~50. Every component scored this way uses the full 0-100 range
    over its own history, which keeps the averaged composite dynamic rather than
    clustered near 50. Higher raw value must already mean 'more greed' (callers negate
    inverted signals like the VIX / realised vol / a stronger pound). Returns 50 on
    insufficient data."""
    w = series.dropna() if hasattr(series, "dropna") else pd.Series(series).dropna()
    n = len(w)
    if n < min_obs:
        return 50
    arr = w.to_numpy()
    lo = float((arr < current_val).sum())
    eq = float((arr == current_val).sum())
    return round((lo + 0.5 * eq) / n * 100)


# ── Fear & Greed state ────────────────────────────────────────────────────────
_fg_history: list = []  # last 4 readings: [{score, timestamp}, ...], used for the trend read


def _eod_cutoff():
    """Exclusive upper bound for EOD price data, as a tz-naive Timestamp.

    Today's session is still in progress until the London close has settled, so
    bars dated today are excluded (return today's date) until 17:00 London — by
    which point the LSE 16:30 close has filtered through to the daily bar. After
    that the bar is a genuine EOD value and nothing is trimmed (return None)."""
    try:
        from zoneinfo import ZoneInfo
        now_london = datetime.now(ZoneInfo("Europe/London"))
    except Exception:
        now_london = datetime.utcnow()  # London ≈ UTC; close enough for the cutoff
    if now_london.hour >= 17:
        return None
    return pd.Timestamp(now_london.date())


def _compute_fear_greed():
    """Compute 6-component UK Fear & Greed score (0-100), update history, auto-set cycle phase.

    Operates LIVE on the current-day bar (Yahoo's daily Close tracks the live
    price intraday) and refreshes on the 15-minute _cached() TTL, so the score
    moves through the trading day rather than being pinned to the last completed
    session. The returned `as_of` carries the date of the bar actually used
    (today during an open session)."""
    # Source a 2-year price frame for every component (the dedicated F&G 2y fetch), but
    # let the fresher shared 1-year feed win on the recent overlap so the score still
    # moves intraday on the 15-minute TTL. combine_first keeps the 2y depth and
    # extends/refreshes the tail with the live feed.
    prices = _get_prices().combine_first(_get_fg_prices_2y())
    components = {}

    ftse_ticker = BENCHMARK_TICKERS["FTSE 100"]

    # Date of the latest bar this reading is built from (UK-anchored, so a US-market day
    # with no UK trading doesn't advance the stamp). Anchor to the ^FTSE column — the
    # source driving most components. During an open session this is today's date.
    as_of = None
    if ftse_ticker in prices.columns:
        ftse_col = prices[ftse_ticker].dropna()
        if not ftse_col.empty:
            as_of = ftse_col.index.max().strftime("%Y-%m-%d")

    # Each component: build its raw daily series over the 2-year frame, then score the
    # latest reading as its PERCENTILE within its own trailing two-year range. This gives
    # every component the full 0-100 range (median ~50), so the averaged composite stays
    # dynamic rather than clustering near 50 the way the old z-score mapping did. The raw
    # series already orient so that a higher value = more greed (inverted signals — a
    # stronger pound, higher vol — are negated inside _fg_raw_series).
    raw = _fg_raw_series(prices)
    scored = {
        k: pd.Series(_score_series_trailing(v, _pct_rank_to_score, window=504))
        for k, v in raw.items()
    }

    def _latest_score(name):
        s = scored.get(name)
        return int(s.iloc[-1]) if s is not None and len(s) else 50

    def _latest_raw(name):
        s = raw.get(name)
        return float(s.iloc[-1]) if s is not None and len(s) else None

    # 1. FTSE Momentum — gap to the 125-day MA, percentile-ranked over 2y.
    mom = _latest_raw("momentum")
    components["momentum"] = {
        "score": _latest_score("momentum"),
        "label": "FTSE Momentum",
        "value": round(mom * 100, 2) if mom is not None else None,
    }

    # 2. Market Breadth — % of basket above its 50-day MA, percentile-ranked over 2y.
    br = _latest_raw("breadth")
    components["breadth"] = {
        "score": _latest_score("breadth"),
        "label": "Market Breadth",
        "value": round(br * 100, 1) if br is not None else None,
    }

    # 3. Currency — GBP/USD 60-day change, inverted then percentile-ranked over 2y. ~75% of
    # FTSE 100 revenue is overseas, so a weaker pound (which ranks high) flatters earnings.
    cur = _latest_raw("currency")  # already negated: -(60-day change)
    components["currency"] = {
        "score": _latest_score("currency"),
        "label": "Currency (GBP/USD)",
        "value": round(-cur * 100, 2) if cur is not None else None,
    }

    # 4. Safe Haven Demand — 20-day FTSE-vs-gilt return spread, percentile-ranked over 2y.
    sh = _latest_raw("safe_haven")
    components["safe_haven"] = {
        "score": _latest_score("safe_haven"),
        "label": "Safe Haven Demand",
        "value": round(sh * 100, 2) if sh is not None else None,
    }

    # 5. Realised Volatility — 20-day annualised vol, inverted then percentile-ranked over 2y.
    rv = _latest_raw("realised_vol")  # already negated: -(annualised vol)
    components["realised_vol"] = {
        "score": _latest_score("realised_vol"),
        "label": "Realised Vol",
        "value": round(-rv * 100, 1) if rv is not None else None,
    }

    # 6. New Highs / Lows — net 52-week highs minus lows, percentile-ranked over 2y. The
    # displayed value keeps the raw highs/lows counts from the breadth calc.
    breadth_data = _compute_breadth(prices)
    new_highs = breadth_data.get("new_highs", 0)
    new_lows = breadth_data.get("new_lows", 0)
    components["hl_ratio"] = {
        "score": _latest_score("hl_ratio"),
        "label": "New Highs / Lows",
        "value": f"{new_highs}/{new_lows}",
    }

    # Overall score = simple average
    scores = [c["score"] for c in components.values()]
    overall = round(sum(scores) / len(scores)) if scores else 50

    # Sentiment label
    if overall >= 75:
        sentiment = "Extreme Greed"
    elif overall >= 55:
        sentiment = "Greed"
    elif overall >= 45:
        sentiment = "Neutral"
    elif overall >= 25:
        sentiment = "Fear"
    else:
        sentiment = "Extreme Fear"

    # Trend: compare current score vs reading 3 cycles ago (before appending)
    if len(_fg_history) >= 3:
        trend = "rising" if overall > _fg_history[-3]["score"] else "falling"
    else:
        trend = "unknown"

    # Update history (keep last 4) — drives the trend read above.
    _fg_history.append(
        {
            "score": overall,
            "timestamp": datetime.now().isoformat(),
        }
    )
    if len(_fg_history) > 4:
        _fg_history.pop(0)

    return {
        "score": overall,
        "sentiment": sentiment,
        "trend": trend,
        "components": components,
        "as_of": as_of,
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
    basket_prices = [prices[t].dropna() for t in sector_tickers if t in prices.columns]
    if not basket_prices:
        return None
    min_len = min(len(p) for p in basket_prices)
    if min_len < window + 1:
        return None
    basket_ret = float(
        np.mean([(p.iloc[-1] / p.iloc[-(window + 1)]) - 1 for p in basket_prices])
    )
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
        rs_prior = _compute_rs_score(
            prices, tickers, bm_ticker, window=73
        )  # 10 days ago
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
            ma50 = float(col.iloc[-50:].mean())
            total += 1
            if float(col.iloc[-1]) > ma50:
                above += 1
        breadth = round(above / total, 4) if total else None

        results.append(
            {
                "sector": sector,
                "rs_score": rs_now,
                "trend": trend,
                "breadth": breadth,
                "signal": signal,
                "pct_change": _basket_pct_change(prices, tickers),
            }
        )

    results.sort(key=lambda x: (x["rs_score"] or 0), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


def _fetch_boe_gilt_yields():
    """Fetch UK nominal zero coupon gilt yields from Bank of England.
    - 5Y/10Y/20Y: BoE IADB API (single request, series IUDSNZC/IUDMNZC/IUDLNZC)
    - 2Y/30Y: BoE zip file (glcnominalddata.zip, sheet '4. spot curve')
    Returns {"snapshot": {2: float, 5: float, ...}}
    """
    import io, zipfile

    _today = datetime.now().strftime("%d/%b/%Y")
    IADB_URL = (
        "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
        f"?csv.x=yes&Datefrom=01/Jan/2021&Dateto={_today}"
        "&SeriesCodes=IUDSNZC,IUDMNZC,IUDLNZC&CSVF=TT&UsingCodes=Y&VPD=Y&VFD=N"
    )
    ZIP_URL = "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalddata.zip"
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
                    if col == "IUDSNZC":
                        col_map[j] = 5
                    elif col == "IUDMNZC":
                        col_map[j] = 10
                    elif col == "IUDLNZC":
                        col_map[j] = 20
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
    # Sheet structure: row 3 = maturity header ("years:", 0.5, 1, 1.5, 2, ...),
    # rows 0-4 are preamble, data starts row 5. Need both recent files for 2021-present.
    zip_data = {2: {}, 30: {}}
    try:
        import openpyxl

        r = requests.get(ZIP_URL, timeout=60, headers=HEADERS)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        xlsx_names = sorted([n for n in zf.namelist() if n.endswith(".xlsx")])
        if not xlsx_names:
            raise ValueError("No xlsx files found in zip")

        def _parse_sheet(wb_bytes):
            wb = openpyxl.load_workbook(
                io.BytesIO(wb_bytes), read_only=True, data_only=True
            )
            ws = wb["4. spot curve"]
            rows = list(ws.iter_rows(values_only=True))
            # Row 3 is the maturity header: ('years:', 0.5, 1.0, 1.5, 2.0, ...)
            header = rows[3] if len(rows) > 3 else rows[0]
            col_2y = next(
                (
                    i
                    for i, h in enumerate(header)
                    if isinstance(h, (int, float)) and abs(h - 2.0) < 0.01
                ),
                None,
            )
            col_30y = next(
                (
                    i
                    for i, h in enumerate(header)
                    if isinstance(h, (int, float)) and abs(h - 30.0) < 0.01
                ),
                None,
            )
            # Data starts at row 5
            for row in rows[5:]:
                if not row or row[0] is None:
                    continue
                try:
                    cell_date = row[0]
                    if hasattr(cell_date, "strftime"):
                        date_str = cell_date.strftime("%Y-%m-%d")
                    else:
                        dt = datetime.strptime(str(cell_date).strip(), "%Y-%m-%d")
                        date_str = dt.strftime("%Y-%m-%d")
                    if date_str < "2021-01-01":
                        continue
                    if (
                        col_2y is not None
                        and col_2y < len(row)
                        and row[col_2y] is not None
                    ):
                        try:
                            zip_data[2][date_str] = float(row[col_2y])
                        except (ValueError, TypeError):
                            pass
                    if (
                        col_30y is not None
                        and col_30y < len(row)
                        and row[col_30y] is not None
                    ):
                        try:
                            zip_data[30][date_str] = float(row[col_30y])
                        except (ValueError, TypeError):
                            pass
                except (ValueError, TypeError, AttributeError):
                    continue

        # Read all files that overlap 2021-present (last two files cover 2016-2024 and 2025+)
        for fname in xlsx_names[-2:]:
            try:
                _parse_sheet(zf.read(fname))
            except Exception as e:
                print(f"[market] BoE zip parse failed for {fname}: {e}")
    except Exception as e:
        print(f"[market] BoE zip gilt fetch failed: {e}")

    # ── Merge all series ──────────────────────────────────────────────────────
    all_series = {
        2: zip_data[2],
        5: iadb_data[5],
        10: iadb_data[10],
        20: iadb_data[20],
        30: zip_data[30],
    }

    if not any(all_series.values()):
        return {"snapshot": {}}

    # Snapshot: latest value per maturity
    snapshot = {}
    for maturity, rows_dict in all_series.items():
        if rows_dict:
            snapshot[maturity] = rows_dict[max(rows_dict.keys())]

    return {"snapshot": snapshot}


def _fetch_cnn_fg():
    """Fetch CNN Fear & Greed Index via the fear-and-greed PyPI package."""
    try:
        import fear_and_greed

        result = fear_and_greed.get()
        return {
            "value": round(float(result.value), 1),
            "description": result.description,
            "last_update": (
                result.last_update.isoformat() if result.last_update else None
            ),
        }
    except Exception as e:
        print(f"[market] CNN fear-greed fetch failed: {e}")
        return {"value": None, "description": None, "last_update": None}


# ── Fear & Greed daily history (UK reconstruction + US CNN backfill) ───────────
# The live UK index is computed from the *latest* reading of each component. To
# draw a rolling-year chart we reconstruct the same six components as daily
# series and score each day against its own trailing window — the historical
# analogue of the live calc. The US side is backfilled from CNN's graphdata
# endpoint (the same source the fear_and_greed package uses), which ships ~1.5y
# of daily values. Both are upserted into fear_greed_history (idempotent).

# F&G needs only the breadth basket + the FTSE / gilt / GBP-USD proxies — not the
# sector tickers — so the 2-year reconstruction fetch is lighter than the full
# proxy universe.
FG_HISTORY_TICKERS = list(
    dict.fromkeys(
        BREADTH_TICKERS
        + [BENCHMARK_TICKERS["FTSE 100"], GILT_ETF_TICKER, CROSS_ASSET_TICKERS["gbpusd"]]
    )
)

CNN_FG_HISTORY_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"


def _fetch_fg_prices_2y_frame():
    """Live Yahoo fetch of the F&G tickers (2y). Persists a disk snapshot on
    success. Module-level so the daily cron can force a fresh fetch."""
    import yfinance as yf  # deferred — only this fetch path needs it

    def _fetch_one(ticker):
        try:
            hist = yf.Ticker(ticker).history(period="2y", auto_adjust=True)
            if hist.empty:
                return ticker, None
            col = hist["Close"]
            if col.index.tz is not None:
                col.index = col.index.tz_localize(None)
            return ticker, col
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in FG_HISTORY_TICKERS}
        frames = {}
        for future in as_completed(futures):
            ticker, col = future.result()
            if col is not None:
                frames[ticker] = col
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames)
    _save_snapshot("fg_prices_2y", df)
    return df


def _get_fg_prices_2y():
    """2-year close history for the F&G tickers, cached. A 252-day output series
    needs ~2y of input once the 52-week-high/low and 125-day-MA lookbacks are
    consumed, so this is fetched separately from the shared 1-year _get_prices()."""
    return _cached_price_frame("fg_prices_2y", _fetch_fg_prices_2y_frame)


def warm_price_snapshots():
    """Force a fresh live fetch of the shared price frames (full proxy, sidebar
    subset, F&G 2y) and persist them to disk, so freshly-started web workers can
    seed their in-memory cache from a recent snapshot instead of paying a live
    Yahoo fetch on the first request.
    Called by the daily prices cron (run_prices.py) after EOD prices land. Goes
    straight to the fetchers (not the seeded cache) so it always writes FRESH
    data. Returns a small summary."""
    p = _fetch_prices_frame()
    sb = _fetch_sidebar_frame()
    fg = _fetch_fg_prices_2y_frame()
    return {
        "prices_cols": int(p.shape[1]) if hasattr(p, "shape") else 0,
        "sidebar_cols": int(sb.shape[1]) if hasattr(sb, "shape") else 0,
        "fg_cols": int(fg.shape[1]) if hasattr(fg, "shape") else 0,
    }


def _score_series_trailing(values, fn, window=252, min_obs=20):
    """Score each point of `values` with `fn(trailing_window, current_value)`,
    using only data up to and including that point (no lookahead). Mirrors the
    live calc, which scores the latest value against the trailing ~1-year window.
    Returns {Timestamp: score}."""
    out = {}
    v = values.dropna()
    n = len(v)
    for i in range(n):
        if i + 1 < min_obs:
            continue
        w = v.iloc[max(0, i + 1 - window) : i + 1]
        out[v.index[i]] = fn(w, float(v.iloc[i]))
    return out


def _fg_raw_series(prices):
    """Raw (pre-score) daily series for each Fear & Greed component, from a close-price
    DataFrame. Returns {name: pd.Series}. The single source of truth for the component
    inputs, shared by the live headline and the history reconstruction. Each series is
    oriented so a HIGHER value = more greed: momentum/breadth/safe_haven/hl_ratio are
    naturally that way, while the currency (GBP/USD change) and realised-vol series are
    negated so a weaker pound / a calmer market rank high. Callers then percentile-rank
    each series against its own trailing window via _pct_rank_to_score."""
    out = {}
    ftse_ticker = BENCHMARK_TICKERS["FTSE 100"]
    if ftse_ticker not in prices.columns:
        return out
    ftse = prices[ftse_ticker].dropna()

    # 1. Momentum — gap to the 125-day MA (above MA = greed).
    if len(ftse) >= 126:
        ma125 = ftse.rolling(125).mean()
        out["momentum"] = ((ftse - ma125) / ma125).dropna()

    # 2. Breadth — % of basket above its own 50-day MA.
    flags = {}
    for t in BREADTH_TICKERS:
        if t in prices.columns:
            col = prices[t].dropna()
            if len(col) >= 51:
                flags[t] = (col > col.rolling(50).mean()).astype(float)
    if flags:
        out["breadth"] = pd.DataFrame(flags).mean(axis=1).dropna()

    # 3. Currency — GBP/USD 60-day change, NEGATED so a weaker pound (greed) ranks high.
    gbp_ticker = CROSS_ASSET_TICKERS["gbpusd"]
    if gbp_ticker in prices.columns:
        out["currency"] = (-prices[gbp_ticker].dropna().pct_change(60)).dropna()

    # 4. Safe haven — 20-day total-return spread, FTSE vs gilt ETF (stocks winning = greed).
    if GILT_ETF_TICKER in prices.columns:
        gilt = prices[GILT_ETF_TICKER].dropna()
        out["safe_haven"] = (ftse.pct_change(20) - gilt.pct_change(20)).dropna()

    # 5. Realised vol — 20-day annualised vol of FTSE, NEGATED so a calmer market ranks high.
    if len(ftse) >= 22:
        lr = np.log(ftse / ftse.shift(1)).dropna()
        out["realised_vol"] = (-(lr.rolling(20).std() * np.sqrt(252))).dropna()

    # 6. New highs / lows — net 52-week highs minus lows as a share of the universe.
    # Computed per ticker on its own NaN-dropped series (each ticker trades a slightly
    # different set of days; rolling over the unioned index would leave every 252-window
    # NaN). Flags are masked to where the 252-day window is full, then summed across
    # tickers — sum/notna skip NaN, so the per-date universe is exactly the tickers with
    # ≥252 history on that date.
    high_flags = {}
    low_flags = {}
    for t in BREADTH_TICKERS:
        if t not in prices.columns:
            continue
        col = prices[t].dropna()
        if len(col) < 252:
            continue
        rmax = col.rolling(252).max()
        rmin = col.rolling(252).min()
        valid = rmax.notna()
        high_flags[t] = (col >= rmax * 0.99).astype(float).where(valid)
        low_flags[t] = (col <= rmin * 1.01).astype(float).where(valid)
    if high_flags:
        hf = pd.DataFrame(high_flags)
        lf = pd.DataFrame(low_flags)
        universe = hf.notna().sum(axis=1).replace(0, np.nan)
        out["hl_ratio"] = ((hf.sum(axis=1) - lf.sum(axis=1)) / universe).dropna()

    return out


def _compute_fear_greed_series(days=370):
    """Reconstruct the daily UK Fear & Greed score over the trailing `days`.
    Returns {date_str: score}. Each component is percentile-ranked against its own
    trailing two-year window (same as the live headline), then averaged. Only dates
    where all six components are available are emitted, for comparability."""
    prices = _get_fg_prices_2y()
    if prices.empty:
        return {}

    raw = _fg_raw_series(prices)
    if not raw:
        return {}
    comp = {
        k: pd.Series(_score_series_trailing(v, _pct_rank_to_score, window=504))
        for k, v in raw.items()
    }

    # Average across components, keeping only fully-populated days for comparability.
    frame = pd.DataFrame(comp).dropna()
    if frame.empty:
        return {}
    overall = frame.mean(axis=1).round()
    cutoff = overall.index.max() - pd.Timedelta(days=days)
    overall = overall[overall.index >= cutoff]
    return {ts.strftime("%Y-%m-%d"): int(v) for ts, v in overall.items()}



def _fetch_cnn_fg_history():
    """Daily US CNN Fear & Greed history from CNN's graphdata endpoint.
    Returns {date_str: value}."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    r = requests.get(CNN_FG_HISTORY_URL, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json().get("fear_and_greed_historical", {}).get("data", [])
    out = {}
    for pt in data:
        try:
            ts = float(pt["x"]) / 1000.0
            d = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            out[d] = round(float(pt["y"]), 1)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _upsert_fg_history(rows):
    """Upsert (date_str, uk_score, us_score) tuples into fear_greed_history.
    COALESCE keeps an existing value when the new one is NULL (e.g. a transient
    CNN fetch failure won't blank out previously-stored US values)."""
    if not rows:
        return 0
    pool = _db_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO fear_greed_history (date, uk_score, us_score) VALUES %s"
            " ON CONFLICT (date) DO UPDATE SET"
            "   uk_score = COALESCE(EXCLUDED.uk_score, fear_greed_history.uk_score),"
            "   us_score = COALESCE(EXCLUDED.us_score, fear_greed_history.us_score),"
            "   computed_at = now()",
            rows,
            page_size=500,
        )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _rebuild_fear_greed_history():
    """Recompute the trailing-year UK series + pull CNN's US history and upsert
    both. Idempotent and self-healing — safe to run daily. Returns a summary."""
    uk = _compute_fear_greed_series()
    us = {}
    try:
        us = _fetch_cnn_fg_history()
    except Exception as e:
        print(f"[market] CNN F&G history fetch failed: {e}")

    all_dates = sorted(set(uk) | set(us))
    rows = [(d, uk.get(d), us.get(d)) for d in all_dates]
    n = _upsert_fg_history(rows)
    _cache.pop("fg_history", None)
    return {"rows": n, "uk_points": len(uk), "us_points": len(us)}


@router.get("/fear-greed/history")
def fear_greed_history(response: Response):
    """Rolling-year daily UK vs US Fear & Greed. Reads the persisted table; if it
    is empty (first run before the cron has populated it), lazily rebuilds once."""
    # Daily series rebuilt by the cron — hold 1h at the edge so at most one request
    # per hour can hit the (expensive) lazy-rebuild fallback.
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
    def read():
        rows = _db_query(
            "SELECT date, uk_score, us_score FROM fear_greed_history"
            " WHERE date >= CURRENT_DATE - INTERVAL '370 days' ORDER BY date"
        )
        out = []
        for r in rows:
            d = r["date"]
            out.append(
                {
                    "date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
                    "uk": r["uk_score"],
                    "us": r["us_score"],
                }
            )
        return out

    def compute():
        data = read()
        if not data:
            try:
                _rebuild_fear_greed_history()
                data = read()
            except Exception as e:
                print(f"[market] F&G history lazy rebuild failed: {e}")
        return data

    # Rebuilt daily by the cron; the table read is cheap but hold an hour and
    # serve-stale-while-revalidating so a visit never blocks on the lazy rebuild.
    return _cached("fg_history", compute, ttl=CACHE_TTL_HOURLY, swr=True)


@router.get("/sidebar")
def sidebar(response: Response):
    # Polled by every open tab and identical for all users (no params). Cache
    # market-hours-aware: ~2 min while the LSE is open (the figures move intraday),
    # 1 h once closed (static until the next bell). The s-maxage header mirrors the
    # in-process TTL so that, behind any edge cache, the fleet of pollers collapses
    # to ~one function call per TTL globally.
    ttl = _live_ttl()
    response.headers["Cache-Control"] = (
        f"public, s-maxage={ttl}, stale-while-revalidate=3600"
    )

    def compute():
        # Benchmarks, sectors and VIX are intentionally LIVE: they read the raw
        # current-day bar (Yahoo's daily Close tracks the live price intraday) and
        # refresh on the fast market-hours TTL via _get_sidebar_prices() — a small
        # frame that omits the breadth tickers (those feed Fear & Greed only).
        # Unlike Fear & Greed / Breadth they are deliberately NOT trimmed to the
        # last completed session, so the % change is "since the previous close" and
        # moves through the trading day.
        prices = _get_sidebar_prices()
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
        vix_col = prices[VIX_TICKER].dropna() if VIX_TICKER in prices.columns else None
        vix_level = (
            round(float(vix_col.iloc[-1]), 2)
            if vix_col is not None and len(vix_col)
            else None
        )
        cnn_fg = _cached("cnn_fear_greed", _fetch_cnn_fg, swr=True)
        fg = _cached("fear_greed", _compute_fear_greed, swr=True)
        return {
            # When this payload was assembled. Cached with the rest, so it reflects
            # the data's TRUE age (last actual compute), not the request time —
            # under SWR a stale read carries the older as_of until the background
            # refresh lands. UTC ISO 8601; the frontend renders it relative.
            "as_of": datetime.now(timezone.utc).isoformat(),
            "benchmarks": benchmarks,
            "sectors": sectors,
            "vix": vix_level,
            "cnn_fear_greed": cnn_fg,
            "fear_greed": {
                "score": fg["score"],
                "sentiment": fg["sentiment"],
                "trend": fg["trend"],
            },
        }

    return _cached("sidebar", compute, ttl=ttl, swr=True)


@router.get("/rotation")
def rotation(response: Response):
    # Live intraday signal, but the in-process cache already tolerates 15-min
    # staleness — edge-cache it so cold starts don't re-run the yfinance pipeline.
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    return _cached("rotation", _compute_rotation, swr=True)


def _compute_breadth(prices=None):
    # `prices` lets a caller pass a pre-trimmed frame (the Fear & Greed calc
    # passes its own EOD-only frame, which we honour as-is). When called with no
    # arg (the Breadth tab and the sidebar) we read the LIVE frame — today's
    # in-progress bar included — for EVERY metric, so the % above 50-day MA dial,
    # the 52-week highs/lows and the advance/decline tallies all reflect the
    # current session and move together on the shared 15-minute refresh.
    if prices is None:
        prices = _get_prices()
    all_basket_tickers = BREADTH_TICKERS

    # % above 50-day MA.
    above_50 = ma_total = 0
    for t in all_basket_tickers:
        if t not in prices.columns:
            continue
        col = prices[t].dropna()
        if len(col) < 51:
            continue
        ma_total += 1
        if float(col.iloc[-1]) > float(col.iloc[-50:].mean()):
            above_50 += 1
    pct_above = round(above_50 / ma_total, 4) if ma_total else None

    # 52-week highs/lows.
    new_highs = new_lows = 0
    for t in all_basket_tickers:
        if t not in prices.columns:
            continue
        col = prices[t].dropna()
        if len(col) < 252:
            continue
        current = float(col.iloc[-1])
        high_52 = float(col.iloc[-252:].max())
        low_52 = float(col.iloc[-252:].min())
        if current >= high_52 * 0.99:
            new_highs += 1
        if current <= low_52 * 1.01:
            new_lows += 1

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
            cumulative += adv - dec
            ad_line.append(
                {
                    "date": prices.index[i].strftime("%Y-%m-%d"),
                    "value": cumulative,
                    "advances": adv,
                    "declines": dec,
                }
            )

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
        "below_50ma": ma_total - above_50,
        "hl_universe": sum(
            1
            for t in all_basket_tickers
            if t in prices.columns and len(prices[t].dropna()) >= 252
        ),
        "advances": today_adv,
        "declines": today_dec,
        "unchanged": today_unch,
        "new_highs": new_highs,
        "new_lows": new_lows,
        "hl_ratio": round(new_highs / new_lows, 2) if new_lows else None,
        "ad_line": ad_line,
    }


@router.get("/breadth")
def breadth(response: Response):
    # Live intraday, 15-min edge cache (matches the in-process cache staleness).
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    return _cached("breadth", _compute_breadth, swr=True)


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
    if not util_cols or len(gilt) < 20:
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
    brent = _cross_asset_item(prices, t["brent"])
    gold = _cross_asset_item(prices, t["gold"])
    zscore = _gilt_vs_utilities_zscore(prices)

    return {
        "gbpusd": gbpusd,
        "brent": brent,
        "gold": gold,
        "gilt_vs_utilities": {
            "zscore": zscore,
            "bias": (
                "Gilts expensive vs Utilities"
                if zscore is not None and zscore < -1
                else None
            ),
        },
    }


@router.get("/cross-asset")
def cross_asset(response: Response):
    # Live intraday, 15-min edge cache (matches the in-process cache staleness).
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    return _cached("cross_asset", _compute_cross_asset, swr=True)


def _ons_latest(url, period_key):
    """Fetch an ONS timeseries and return the latest + prior observation.
    ONS returns observations in ascending chronological order, so [-1] is latest.
    Returns {"value": float, "period": str, "prev": float | None} or None."""
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        obs = r.json().get(period_key, [])
        obs = [o for o in obs if o.get("value") not in (None, "")]
        if not obs:
            return None
        latest = obs[-1]
        prev = obs[-2] if len(obs) >= 2 else None
        return {
            "value": float(latest["value"]),
            "period": latest["date"],
            "prev": float(prev["value"]) if prev else None,
        }
    except Exception as e:
        print(f"[market] ONS fetch failed ({url}): {e}")
        return None


def _fetch_uk_macro():
    """Latest UK CPI (12-month inflation, monthly) and GDP quarter-on-quarter
    growth from the ONS timeseries API.  GDP tries the First Estimate (pn2,
    ~4-week lag) and falls back to the Quarterly National Accounts (qna,
    ~3-month lag) if pn2 returns nothing."""
    gdp = _ons_latest(ONS_GDP_QOQ_URL, "quarters")
    if gdp is None:
        print("[market] ONS GDP pn2 empty, falling back to qna")
        gdp = _ons_latest(ONS_GDP_QOQ_URL_FALLBACK, "quarters")
    return {
        "cpi": _ons_latest(ONS_CPI_URL, "months"),
        "gdp_qoq": gdp,
    }


@router.get("/uk-macro")
def uk_macro(response: Response):
    # ONS CPI/GDP — changes monthly at most. Hold a day at the edge.
    response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=86400"
    return _cached("uk_macro", _fetch_uk_macro, ttl=CACHE_TTL_DAILY, swr=True)


@router.get("/gilt-yields")
def gilt_yields(response: Response):
    # BoE yields update daily; the miss path fetches + parses an Excel file. Hold 1h.
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
    return _cached("gilt_yields", _fetch_boe_gilt_yields, ttl=CACHE_TTL_HOURLY, swr=True)


@router.get("/fear-greed")
def fear_greed(response: Response):
    # Live intraday, 15-min edge cache (matches the in-process cache staleness).
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    return _cached("fear_greed", _compute_fear_greed, swr=True)


def _compute_signals():
    """Generate signal log by running rotation + breadth and checking thresholds."""
    rotation_data = _compute_rotation()
    breadth_data = _compute_breadth()
    now = datetime.now().strftime("%d %b %H:%M")
    signals = []

    breadth_val = breadth_data.get("pct_above_50ma")
    if breadth_val is not None:
        if breadth_val > 0.65:
            signals.append(
                {
                    "timestamp": now,
                    "type": "ALERT",
                    "message": f"Breadth at {breadth_val*100:.0f}% — bullish threshold crossed",
                }
            )
        elif breadth_val < 0.40:
            signals.append(
                {
                    "timestamp": now,
                    "type": "ALERT",
                    "message": f"Breadth at {breadth_val*100:.0f}% — bearish threshold crossed",
                }
            )

    for s in rotation_data:
        if s["signal"] == "BUY":
            signals.append(
                {
                    "timestamp": now,
                    "type": "BUY",
                    "message": f"{s['sector']} RS {s['rs_score']:.2f} rising — momentum breakout",
                }
            )
        elif s["signal"] == "AVOID":
            signals.append(
                {
                    "timestamp": now,
                    "type": "AVOID",
                    "message": f"{s['sector']} RS {s['rs_score']:.2f} falling — underperforming market",
                }
            )

    # newest first (manual log entries are already ordered)
    return signals[:50]  # cap at 50 entries


@router.get("/signals")
def signals(response: Response):
    # = rotation + breadth; live intraday, 15-min edge cache.
    response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    return _cached("signals", _compute_signals, swr=True)
