"""Short-interest data: FCA short-position disclosures.

The UK short-selling disclosure regime changed on 13 July 2026:
  - Old regime (up to Fri 10 July): individual named holders disclosing net
    short positions >=0.5%, published daily as
    https://www.fca.org.uk/publication/data/short-positions-daily-update.xlsx
    ("current" + "historic" tabs). Frozen one-time archive -> short_position_holders.
  - New regime (from Mon 13 July): anonymised Aggregate Net Short Positions
    (ANSPs) per issuer -- sum of ALL positions >=0.2%, so not comparable to the
    old >=0.5% named feed. Published daily from 12pm UK (~2 working-day lag)
    as CSV/XLSX, "current" + "historic" lists -> short_positions_agg.

These two series must never be merged into one chart/number -- the thresholds
differ (0.5% named vs 0.2% aggregate).

Self-contained APIRouter module mirroring dividends.py (own connection pool,
query() helper, record_run() pipeline_runs stamp).
"""

from fastapi import APIRouter, Query, Response
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import re
import time
import logging
from datetime import date, timedelta
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter()

# ── DB — shared process-wide pool + query (see db.py). Re-exported under the
# module's historical names. ──────────────────────────────────────────────────
from db import query, get_pool as _get_pool


# ── Symbol / ISIN resolution ───────────────────────────────────────────────────
#
# company_metadata has no independent ISIN source -- yfinance's Ticker.isin was
# tried and abandoned: it scrapes an "experimental" businessinsider.com search
# endpoint that returns garbage (the same bogus string for multiple unrelated
# companies, blank for others). Instead the FCA's own disclosure rows already
# pair (ISIN, issuer name) for every company ever shorted, so a name-match
# "learns" the ISIN straight from that data and writes it back to
# company_metadata once -- a strictly better source since it's the exact ISIN
# the FCA itself keys on, with no extra network calls.

_NAME_SUFFIXES = re.compile(
    r"\b(PLC|GROUP|HOLDINGS?|LIMITED|LTD|& CO|AND CO)\b", re.IGNORECASE
)


def _normalise_name(name):
    if not name:
        return ""
    n = name.upper()
    n = _NAME_SUFFIXES.sub("", n)
    n = re.sub(r"[^A-Z0-9 ]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _build_universe_index():
    """company_metadata rows for matching, plus a normalised-name lookup."""
    universe = query("SELECT symbol, name, isin FROM company_metadata WHERE is_active")
    by_isin = {r["isin"]: r["symbol"] for r in universe if r["isin"]}
    by_name = {_normalise_name(r["name"]): r["symbol"] for r in universe if r["name"]}
    return by_isin, by_name


def _resolve_symbol(isin, issuer_name, by_isin, by_name, cur=None):
    """Resolve an FCA (isin, issuer_name) pair to a company_symbol.

    Match order: (1) isin already on file; (2) normalised-name match, in which
    case -- if a cursor is given -- the isin is learned back onto
    company_metadata (only fills NULLs) so later rows/runs hit the fast path.
    """
    if isin and isin in by_isin:
        return by_isin[isin]
    norm = _normalise_name(issuer_name)
    if norm and norm in by_name:
        symbol = by_name[norm]
        if isin and cur is not None:
            cur.execute(
                "UPDATE company_metadata SET isin = %s WHERE symbol = %s AND isin IS NULL",
                (isin, symbol),
            )
            by_isin[isin] = symbol  # subsequent rows in this run hit the fast path too
        return symbol
    return None


# ── Ingestion: daily ANSP series (new regime) ─────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0"}

_FCA_ANSP_PAGE = (
    "https://www.fca.org.uk/markets/short-selling/notification-disclosure-net-short-positions"
)


def _discover_ansp_urls():
    """Scrape the FCA ANSP page for the current/historic aggregate file links.

    Env overrides short-circuit discovery -- the real URLs only exist once the
    FCA publishes under the new regime (from 13 July 2026).
    """
    current_override = os.environ.get("FCA_ANSP_CURRENT_URL")
    historic_override = os.environ.get("FCA_ANSP_HISTORIC_URL")
    if current_override or historic_override:
        return current_override, historic_override

    import requests

    r = requests.get(_FCA_ANSP_PAGE, timeout=20, headers=_HEADERS)
    r.raise_for_status()
    hrefs = re.findall(r'href="([^"]+)"', r.text)

    current_url = None
    historic_url = None
    for href in hrefs:
        low = href.lower()
        if not (low.endswith(".csv") or low.endswith(".xlsx")):
            continue
        if "current" in low and "aggregate" in low.replace("-", "").replace("_", ""):
            current_url = href
        elif "current" in low:
            current_url = current_url or href
        if "historic" in low:
            historic_url = historic_url or href

    def _absolutize(u):
        if not u:
            return None
        return u if u.startswith("http") else f"https://www.fca.org.uk{u}"

    return _absolutize(current_url), _absolutize(historic_url)


def _to_date(val):
    """Coerce an FCA date cell to a datetime.date, or None.

    The CSVs carry dd/mm/yyyy strings ('19/06/2026'); XLSX cells may already be
    datetimes. Parsed here (dayfirst) rather than passed raw to Postgres, whose
    default MDY DateStyle would reject 19/06/2026 and silently swap 01/07/2026.
    """
    import pandas as pd

    if val is None:
        return None
    ts = pd.to_datetime(val, dayfirst=True, errors="coerce")
    return None if pd.isna(ts) else ts.date()


def _read_ansp_table(url, fallback_disclosure_date=None):
    """Download + parse one ANSP file (CSV preferred, XLSX fallback) into rows.

    Returns a list of dicts with keys: issuer_name, isin, ansp_pct, position_date,
    disclosure_date. Matches columns loosely on substrings; the first real
    publication (Mon 13 July 2026) uses:
      current:  ISIN / Name of Company / Aggregated net short position (%) /
                Position date (of latest position date notified)
      historic: same + Date the aggregated net short position became historical

    The current file has no publication-date column, so callers pass
    fallback_disclosure_date (the scrape date) to key that day's snapshot.
    """
    import pandas as pd
    import requests

    resp = requests.get(url, timeout=30, headers=_HEADERS)
    resp.raise_for_status()

    import io

    buf = io.BytesIO(resp.content)
    if url.lower().endswith(".csv"):
        df = pd.read_csv(buf)
    else:
        df = pd.read_excel(buf, engine="openpyxl")

    cols = {c: c.strip().lower() for c in df.columns}
    df = df.rename(columns=cols)

    def _find(*substrs):
        for c in df.columns:
            if all(s in c for s in substrs):
                return c
        return None

    col_issuer = _find("name of issuer") or _find("name of company") or _find("issuer") or _find("company")
    col_isin = _find("isin")
    col_pct = _find("net short") or _find("aggregate")
    col_posdate = _find("position date")
    col_discdate = _find("disclosure") or _find("publication") or _find("historical")

    rows = []
    for _, row in df.iterrows():
        isin = str(row.get(col_isin, "")).strip() if col_isin else ""
        issuer = str(row.get(col_issuer, "")).strip() if col_issuer else ""
        if not isin or not issuer:
            continue
        pct = row.get(col_pct) if col_pct else None
        if pct is not None and pd.isna(pct):
            pct = None
        pos_date = _to_date(row.get(col_posdate)) if col_posdate else None
        disc_date = _to_date(row.get(col_discdate)) if col_discdate else None
        if disc_date is None:
            disc_date = fallback_disclosure_date or pos_date

        rows.append(
            {
                "isin": isin,
                "issuer_name": issuer,
                "ansp_pct": float(pct) if pct is not None else None,
                "position_date": pos_date,
                "disclosure_date": disc_date,
            }
        )
    return rows


def refresh_shorts():
    """Daily job: discover + ingest the current + historic ANSP files."""
    t0 = time.time()

    current_url, historic_url = _discover_ansp_urls()
    if not current_url and not historic_url:
        raise RuntimeError("could not discover ANSP file URLs (page scrape + env overrides both empty)")

    by_isin, by_name = _build_universe_index()

    all_rows = []
    # Current file carries no publication date -- key today's snapshot on the
    # scrape date so the daily series accumulates one row per issuer per day.
    # Historic rows key on their own "became historical" column.
    for url, fallback in ((current_url, date.today()), (historic_url, None)):
        if not url:
            continue
        all_rows.extend(_read_ansp_table(url, fallback_disclosure_date=fallback))

    n_written = 0
    n_unresolved = 0
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        for r in all_rows:
            if r["ansp_pct"] is None or not r["disclosure_date"]:
                continue
            symbol = _resolve_symbol(r["isin"], r["issuer_name"], by_isin, by_name, cur)
            if symbol is None:
                n_unresolved += 1
            cur.execute(
                """
                INSERT INTO short_positions_agg
                    (isin, disclosure_date, issuer_name, ansp_pct, position_date, company_symbol)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (isin, disclosure_date) DO UPDATE SET
                    issuer_name    = EXCLUDED.issuer_name,
                    ansp_pct       = EXCLUDED.ansp_pct,
                    position_date  = EXCLUDED.position_date,
                    company_symbol = EXCLUDED.company_symbol
                """,
                (r["isin"], r["disclosure_date"], r["issuer_name"], r["ansp_pct"], r["position_date"], symbol),
            )
            n_written += 1
        conn.commit()
    finally:
        pool.putconn(conn)

    return {
        "rows_written": n_written,
        "unresolved_isins": n_unresolved,
        "source_url": current_url or historic_url,
        "duration_seconds": round(time.time() - t0, 1),
    }


# ── Ingestion: one-time named-holder archive (old regime) ────────────────────

_OLD_REGIME_URL = "https://www.fca.org.uk/publication/data/short-positions-daily-update.xlsx"


def backfill_holder_archive(path_or_url=None):
    """One-time: parse the pre-13-July individual-positions XLSX into short_position_holders.

    Safe to re-run (upsert), but this is meant to run exactly once as a
    snapshot before the FCA archives the old feed.
    """
    import pandas as pd

    source = path_or_url or _OLD_REGIME_URL
    t0 = time.time()

    if source.startswith("http"):
        import requests
        import io

        resp = requests.get(source, timeout=60, headers=_HEADERS)
        resp.raise_for_status()
        book = pd.read_excel(io.BytesIO(resp.content), sheet_name=None, engine="openpyxl")
    else:
        book = pd.read_excel(source, sheet_name=None, engine="openpyxl")

    by_isin, by_name = _build_universe_index()

    n_written = 0
    n_unresolved = 0
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        for sheet_name, df in book.items():
            is_current = "current" in sheet_name.lower()
            is_historic = "historic" in sheet_name.lower()
            if not is_current and not is_historic:
                continue

            cols = {c: c.strip().lower() for c in df.columns}
            df = df.rename(columns=cols)

            def _find(*substrs):
                for c in df.columns:
                    if all(s in c for s in substrs):
                        return c
                return None

            col_holder = _find("position holder") or _find("holder")
            col_issuer = _find("name of share issuer") or _find("issuer")
            col_isin = _find("isin")
            col_pct = _find("net short")
            col_posdate = _find("position date")

            for _, row in df.iterrows():
                isin = str(row.get(col_isin, "")).strip() if col_isin else ""
                holder = str(row.get(col_holder, "")).strip() if col_holder else ""
                issuer = str(row.get(col_issuer, "")).strip() if col_issuer else ""
                if not isin or not holder or not issuer:
                    continue
                pct = row.get(col_pct) if col_pct else None
                pos_date = row.get(col_posdate) if col_posdate else None
                if pct is None or not pos_date:
                    continue

                symbol = _resolve_symbol(isin, issuer, by_isin, by_name, cur)
                if symbol is None:
                    n_unresolved += 1

                cur.execute(
                    """
                    INSERT INTO short_position_holders
                        (isin, holder_name, position_date, net_short_pct, issuer_name, is_current, company_symbol)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (isin, holder_name, position_date) DO UPDATE SET
                        net_short_pct  = EXCLUDED.net_short_pct,
                        issuer_name    = EXCLUDED.issuer_name,
                        is_current     = EXCLUDED.is_current,
                        company_symbol = EXCLUDED.company_symbol
                    """,
                    (isin, holder, pos_date, float(pct), issuer, is_current, symbol),
                )
                n_written += 1
        conn.commit()
    finally:
        pool.putconn(conn)

    return {
        "rows_written": n_written,
        "unresolved_isins": n_unresolved,
        "source": source,
        "duration_seconds": round(time.time() - t0, 1),
    }


def record_run(status: str, detail: dict):
    """Stamp pipeline_runs so healthcheck.py can tell the daily job ran
    (migration 008 convention, see refresh_index_membership.py)."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
            VALUES ('shorts_refresh', NOW(), %s, %s)
            ON CONFLICT (pipeline) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                status      = EXCLUDED.status,
                detail      = EXCLUDED.detail
            """,
            (status, psycopg2.extras.Json(detail)),
        )
        conn.commit()
    finally:
        pool.putconn(conn)


# ── API ──────────────────────────────────────────────────────────────────────


def _empty_shape(symbol):
    return {
        "symbol": symbol,
        "current_pct": None,
        "disclosure_date": None,
        "change_1m": None,
        "history": [],
        "holders_archive": [],
    }


@router.get("/api/shorts")
def shorts(symbol: str = Query(...), response: Response = None):
    """Short-interest summary for one company -- feeds the Health tab's
    short-interest section. Returns the empty shape (not 404) for companies
    with no disclosed short positions (the /api/dividends convention)."""
    if response is not None:
        response.headers["Cache-Control"] = (
            "public, s-maxage=21600, stale-while-revalidate=86400"
        )

    isin_rows = query("SELECT isin FROM company_metadata WHERE symbol = %s", (symbol,))
    isin = isin_rows[0]["isin"] if isin_rows else None

    # 2y cap: change_1m only needs ~30d of lookback, so this is just keeping
    # the ever-accumulating daily series from growing the response unbounded.
    history_floor = date.today() - timedelta(days=730)

    agg_rows = []
    if isin:
        agg_rows = query(
            "SELECT disclosure_date, ansp_pct FROM short_positions_agg"
            " WHERE isin = %s AND disclosure_date >= %s ORDER BY disclosure_date ASC",
            (isin, history_floor),
        )
    if not agg_rows:
        agg_rows = query(
            "SELECT disclosure_date, ansp_pct FROM short_positions_agg"
            " WHERE company_symbol = %s AND disclosure_date >= %s ORDER BY disclosure_date ASC",
            (symbol, history_floor),
        )

    holder_rows = []
    if isin:
        holder_rows = query(
            "SELECT holder_name, net_short_pct, position_date, is_current"
            " FROM short_position_holders WHERE isin = %s"
            " ORDER BY is_current DESC, net_short_pct DESC",
            (isin,),
        )
    if not holder_rows:
        holder_rows = query(
            "SELECT holder_name, net_short_pct, position_date, is_current"
            " FROM short_position_holders WHERE company_symbol = %s"
            " ORDER BY is_current DESC, net_short_pct DESC",
            (symbol,),
        )

    if not agg_rows and not holder_rows:
        return _empty_shape(symbol)

    current_pct = None
    disclosure_date = None
    change_1m = None
    if agg_rows:
        latest = agg_rows[-1]
        current_pct = float(latest["ansp_pct"])
        disclosure_date = str(latest["disclosure_date"])

        month_ago = latest["disclosure_date"] - timedelta(days=30)
        prior = [r for r in agg_rows if r["disclosure_date"] <= month_ago]
        if prior:
            change_1m = round(current_pct - float(prior[-1]["ansp_pct"]), 4)

    return {
        "symbol": symbol,
        "current_pct": current_pct,
        "disclosure_date": disclosure_date,
        "change_1m": change_1m,
        "history": [
            {"date": str(r["disclosure_date"]), "pct": float(r["ansp_pct"])}
            for r in agg_rows
        ],
        "holders_archive": [
            {
                "holder": r["holder_name"],
                "pct": float(r["net_short_pct"]),
                "date": str(r["position_date"]),
                "is_current": r["is_current"],
            }
            for r in holder_rows
        ],
    }
