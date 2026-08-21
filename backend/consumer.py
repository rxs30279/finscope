"""UK consumer indicators for the /markets 'Consumer' tab.

Four free, keyless sources feed one long table (consumer_series): ONS
timeseries JSON (saving ratio, retail sales), the Bank of England Interactive
Database CSV (consumer credit, mortgage approvals, household money holdings),
OECD SDMX (consumer confidence history), and a scrape of the GfK/NIQ press
release (consumer confidence headline). Kept separate from market.py — that
module owns the price-frame cache, Fear & Greed, breadth, rotation and gilts,
none of which this shares.

Every source URL, series code and parse quirk below was verified live on
2026-08-21; see docs/superpowers/plans/2026-08-21-consumer-data-tab.md for the
full research trail if a source ever needs re-diagnosing.
"""
import csv
import io
import re
import threading
import time
from datetime import date, datetime, timezone

import psycopg2.extras
import requests
from fastapi import APIRouter, Response

from db import query as _db_query, get_pool as _db_pool

router = APIRouter(prefix="/api/consumer", tags=["consumer"])

# ── In-memory cache — same single-flight + SWR shape as market.py's _cached,
# kept separate so this module's one entry doesn't share a namespace/TTL with
# market.py's many. ──────────────────────────────────────────────────────────
_cache: dict = {}
CACHE_TTL_DAILY = 86400  # 24 hours — every source here changes monthly at most
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
    with _locks_guard:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _run():
        try:
            data = fn()
            if data is not None:
                _cache[key] = (data, time.time())
        except Exception as e:
            print(f"[consumer] background refresh failed for {key}: {e}")
        finally:
            with _locks_guard:
                _refreshing.discard(key)

    threading.Thread(target=_run, name=f"consumer-refresh-{key}", daemon=True).start()


def _cached(key: str, fn, ttl: int = CACHE_TTL_DAILY, swr: bool = False):
    now = time.time()
    entry = _cache.get(key)
    if entry is not None and now - entry[1] < ttl:
        return entry[0]
    if entry is not None and swr:
        _maybe_refresh_async(key, fn)
        return entry[0]
    lock = _key_lock(key)
    with lock:
        entry = _cache.get(key)
        if entry is not None and time.time() - entry[1] < ttl:
            return entry[0]
        data = fn()
        _cache[key] = (data, time.time())
        return data


# ── Series catalogue — single source of truth for what exists ─────────────────
# "source" picks the fetcher; "chart_only" series (OECD confidence) get a
# history array but no headline card — the GfK card is the confidence card.
SERIES = {
    "gfk_confidence":     {"label": "Consumer Confidence (GfK)",  "unit": "index", "source": "gfk"},
    "oecd_confidence":    {"label": "Consumer Confidence (OECD)", "unit": "index", "source": "oecd", "chart_only": True},
    "saving_ratio":       {"label": "Household Saving Ratio",     "unit": "%",     "source": "ons"},
    "retail_sales_mom":   {"label": "Retail Sales (MoM)",         "unit": "%",     "source": "ons"},
    "consumer_credit":    {"label": "Consumer Credit Growth",     "unit": "%",     "source": "boe"},
    "mortgage_approvals": {"label": "Mortgage Approvals",         "unit": "count", "source": "boe"},
    "household_money":    {"label": "Household Money Holdings",   "unit": "%",     "source": "boe"},
}

_MONTHS = {m.upper(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
)}


def _period_to_date(period: str, freq: str) -> date:
    """Normalise a source-specific period label to its period-START date, so
    monthly and quarterly series can share one time axis. `freq` is one of
    "Q" (ONS quarterly, "2026 Q1"), "M" (ONS monthly, "2026 JUL"), "BOE" (BoE
    CSV, "30 Jun 2026" — a period END, normalised back to month start), or
    "OECD" (SDMX, "2026-06")."""
    if freq == "Q":
        m = re.match(r"^(\d{4})\s+Q(\d)$", period)
        year, q = int(m.group(1)), int(m.group(2))
        return date(year, (q - 1) * 3 + 1, 1)
    if freq == "M":
        m = re.match(r"^(\d{4})\s+([A-Z]{3})$", period)
        year, mon = int(m.group(1)), _MONTHS[m.group(2)]
        return date(year, mon, 1)
    if freq == "BOE":
        d = datetime.strptime(period, "%d %b %Y").date()
        return date(d.year, d.month, 1)
    if freq == "OECD":
        year, mon = period.split("-")
        return date(int(year), int(mon), 1)
    raise ValueError(f"unknown freq: {freq}")


# ── A. ONS timeseries JSON ─────────────────────────────────────────────────────
_ONS_PATHS = {
    # TRAP: the saving ratio also resolves at .../nrjs/qna, which 200s but is
    # frozen at 2016 Q3. `ukea` is the live dataset — do not "simplify" this.
    "saving_ratio": ("economy/grossdomesticproductgdp/timeseries/nrjs/ukea", "quarters", "Q"),
    # TRAP: retail sales live under businessindustryandtrade/, not economy/
    # (which 404s).
    "retail_sales_mom": ("businessindustryandtrade/retailindustry/timeseries/j5ec/drsi", "months", "M"),
}


def _fetch_ons_series(series: str) -> list:
    path, period_key, freq = _ONS_PATHS[series]
    url = f"https://www.ons.gov.uk/{path}/data"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        obs = r.json().get(period_key, [])
        rows = []
        for o in obs:
            v = o.get("value")
            if v in (None, ""):
                continue
            period = o["date"]
            rows.append((period, _period_to_date(period, freq), float(v)))
        return rows
    except Exception as e:
        print(f"[consumer] ONS fetch failed for {series} ({url}): {e}")
        return []


# ── B. Bank of England Interactive Database (CSV) ──────────────────────────────
_BOE_CODES = {
    "consumer_credit": "LPMB4TC",       # consumer credit, 1m growth %
    "mortgage_approvals": "LPMVTVX",    # mortgage approvals for house purchase, count
    "household_money": "LPMVVHW",       # households' money holdings (M4ex), 12m growth %
}

_BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"


def _fetch_boe_series(series: str) -> list:
    code = _BOE_CODES[series]
    # One code per request: a single unrecognised code makes the whole response
    # an HTML "Invalid series code" page, so a valid code in the same batch as
    # a stale/renamed one would silently return nothing.
    params = {
        "csv.x": "yes",
        "Datefrom": "01/Jan/1993",
        "Dateto": datetime.now(timezone.utc).strftime("%d/%b/%Y"),
        "SeriesCodes": code,
        "UsingCodes": "Y",
        "CSVF": "TN",
        "VPD": "Y",
        "VFD": "N",
    }
    try:
        r = requests.get(_BOE_URL, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        body = r.text
        if not body.startswith("DATE,"):
            print(f"[consumer] BoE fetch for {series} ({code}) did not return CSV — likely an invalid code")
            return []
        rows = []
        reader = csv.reader(io.StringIO(body))
        next(reader)  # header
        for row in reader:
            if len(row) < 2 or not row[1]:
                continue
            period = row[0]
            rows.append((period, _period_to_date(period, "BOE"), float(row[1])))
        return rows
    except Exception as e:
        print(f"[consumer] BoE fetch failed for {series} ({code}): {e}")
        return []


# ── C. OECD SDMX — consumer confidence history ─────────────────────────────────
_OECD_URL = (
    "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,/"
    "GBR.M.CCICP...AA...H?startPeriod=1990-01&format=jsondata"
)


def _fetch_oecd_confidence() -> list:
    try:
        r = requests.get(_OECD_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        d = r.json()
        # SDMX-JSON keys each observation by an INDEX, and the index order is not
        # chronological — map through the time dimension's value list or dates
        # come back scrambled.
        tv = d["data"]["structures"][0]["dimensions"]["observation"][0]["values"]
        series = d["data"]["dataSets"][0]["series"]
        rows = []
        for _key, s in series.items():
            for i, o in s["observations"].items():
                period = tv[int(i)]["id"]
                rows.append((period, _period_to_date(period, "OECD"), float(o[0])))
        rows.sort(key=lambda t: t[1])
        return rows
    except Exception as e:
        print(f"[consumer] OECD fetch failed: {e}")
        return []


# ── D. GfK / NIQ Consumer Confidence Barometer (scrape) ────────────────────────
_GFK_INDEX_URL = "https://nielseniq.com/global/en/news-center/"
_GFK_LINK_RE = re.compile(r"news-center/(\d{4})/([a-z0-9-]+)")
_GFK_SCORE_RE = re.compile(
    r"Overall Index Score\s+(?:was|is|has)?[^.]*?\bto\s+(-?\d+)\s+in\s+([A-Z][a-z]+)"
)


def _strip_html(html: str) -> str:
    t = re.sub(r"(?s)<(script|style|head)\b.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def _fetch_gfk_confidence() -> list:
    """At most one point (the current month). Must never raise — GfK has no
    historical archive, so a scrape break just means the card shows '—'; the
    OECD chart is independent and stays unaffected."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        idx = requests.get(_GFK_INDEX_URL, timeout=20, headers=headers)
        idx.raise_for_status()
        seen = []
        for m in _GFK_LINK_RE.finditer(idx.text):
            url = f"https://nielseniq.com/global/en/news-center/{m.group(1)}/{m.group(2)}/"
            if url not in seen:
                seen.append(url)
        for url in seen[:10]:
            try:
                page = requests.get(url, timeout=20, headers=headers)
                page.raise_for_status()
            except Exception:
                continue
            text = _strip_html(page.text)
            m = _GFK_SCORE_RE.search(text)
            if not m:
                continue
            value, month_name = int(m.group(1)), m.group(2)
            year = int(re.search(r"/(\d{4})/", url).group(1))
            try:
                d = datetime.strptime(f"{month_name} {year}", "%B %Y").date()
            except ValueError:
                continue
            period = f"{month_name} {year}"
            return [(period, d, float(value))]
        return []
    except Exception as e:
        print(f"[consumer] GfK fetch failed: {e}")
        return []


_FETCHERS = {
    "gfk_confidence": lambda: _fetch_gfk_confidence(),
    "oecd_confidence": lambda: _fetch_oecd_confidence(),
    "saving_ratio": lambda: _fetch_ons_series("saving_ratio"),
    "retail_sales_mom": lambda: _fetch_ons_series("retail_sales_mom"),
    "consumer_credit": lambda: _fetch_boe_series("consumer_credit"),
    "mortgage_approvals": lambda: _fetch_boe_series("mortgage_approvals"),
    "household_money": lambda: _fetch_boe_series("household_money"),
}


# ── Upsert + rebuild ────────────────────────────────────────────────────────────
def _upsert_series(rows: list) -> int:
    """rows: list of (series, date, period, value). Plain EXCLUDED.value (no
    COALESCE) — unlike fear_greed_history, a failed fetcher contributes an empty
    list rather than NULL rows, so there's nothing to protect, and ONS/BoE
    revisions must overwrite the stored value."""
    if not rows:
        return 0
    pool = _db_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO consumer_series (series, date, period, value) VALUES %s"
            " ON CONFLICT (series, date) DO UPDATE SET"
            "   value = EXCLUDED.value,"
            "   period = EXCLUDED.period,"
            "   fetched_at = now()",
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


def rebuild_consumer_series() -> dict:
    """Fetch every series and upsert. Never raises for a partial failure — a
    dead source is reported in `failed`, not allowed to take down the others."""
    all_rows = []
    failed = []
    for series, fetch in _FETCHERS.items():
        try:
            points = fetch()
        except Exception as e:
            print(f"[consumer] fetcher raised for {series}: {e}")
            points = []
        if not points:
            failed.append(series)
            continue
        all_rows.extend((series, d, period, value) for period, d, value in points)
    n = _upsert_series(all_rows)
    _cache.pop("consumer", None)
    return {"series": len(_FETCHERS) - len(failed), "rows": n, "failed": failed}


# ── /api/consumer endpoint ──────────────────────────────────────────────────────
def _build_consumer() -> dict:
    def read():
        rows = _db_query("SELECT series, date, period, value FROM consumer_series ORDER BY series, date")
        by_series: dict = {}
        for r in rows:
            by_series.setdefault(r["series"], []).append(r)
        if not by_series:
            return None
        cards = []
        for series, meta in SERIES.items():
            if meta.get("chart_only"):
                continue
            pts = by_series.get(series, [])
            latest = pts[-1] if pts else None
            prev = pts[-2] if len(pts) >= 2 else None
            cards.append({
                "series": series,
                "label": meta["label"],
                "unit": meta["unit"],
                "value": latest["value"] if latest else None,
                "prev": prev["value"] if prev else None,
                "period": latest["period"] if latest else None,
            })
        history = {
            series: [
                {"date": r["date"].strftime("%Y-%m-%d"), "value": r["value"]}
                for r in pts
            ]
            for series, pts in by_series.items()
        }
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "cards": cards,
            "history": history,
        }

    def compute():
        data = read()
        if data is None:
            try:
                rebuild_consumer_series()
                data = read()
            except Exception as e:
                print(f"[consumer] lazy rebuild failed: {e}")
        return data or {"as_of": datetime.now(timezone.utc).isoformat(), "cards": [], "history": {}}

    return compute()


@router.get("")
def consumer(response: Response):
    # Rebuilt daily by the cron; every source here moves monthly at most.
    response.headers["Cache-Control"] = "public, s-maxage=86400, stale-while-revalidate=86400"
    return _cached("consumer", _build_consumer, ttl=CACHE_TTL_DAILY, swr=True)
