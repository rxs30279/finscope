"""
FinScope — Quarterly Index Membership Refresh
=============================================
Reconciles the `company_metadata` universe against the *current* constituents of
the four indices we track, so the screener stays in step with the FTSE quarterly
reshuffle (effective the 3rd Friday of Mar/Jun/Sep/Dec).

Source of truth: Hargreaves Lansdown's stock-market-summary pages — one
consistent EPIC+Name table per index, covering all four tiers:

    FTSE 100        https://www.hl.co.uk/shares/stock-market-summary/ftse-100
    FTSE 250        .../ftse-250
    FTSE SmallCap   .../ftse-small-cap
    FTSE AIM 100    .../ftse-aim-100

(The legacy build_company_list.py / build_aim100_list.py used hand-pasted ticker
blobs from Wikipedia / the LSE heatmap / HL. This fetches the same lists live.)

For each constituent the EPIC is mapped to its Yahoo symbol and reconciled:

  * NEW     — in the index, not in the DB  -> INSERT (metadata from yfinance),
              is_active=true, financials_updated=NULL so updater.py picks it up
              first on its next run.
  * MOVED   — already in the DB but its index tier changed -> UPDATE ftse_index
              (and reactivate if it had been deactivated).
  * DROPPED — in the DB but no longer in *any* tracked index -> hard DELETE.
              Removed from company_metadata and from every dependent table
              (financials, prices, analyst snapshots, news, RNS, scores) in a
              single transaction per symbol. Permanent: a name that later
              re-enters an index is re-added fresh and refetched from scratch.

Usage (run from backend/):
    python refresh_index_membership.py            # dry run — report only, no writes
    python refresh_index_membership.py --apply    # apply changes
    python refresh_index_membership.py --apply --max-purge 40
                                                  # raise the unattended purge cap

Safe to re-run; every write is idempotent (ON CONFLICT upserts). In --apply mode,
if more than --max-purge symbols (default 25) would be purged, the purges are
skipped (new/moved still applied) and the run exits non-zero — a second guard,
after the per-index MIN_EXPECTED floors, against a partial HL fetch mass-deleting
real stocks on an unattended cron run.
"""

import os
import re
import sys
import time
import logging
from io import StringIO

import pandas as pd
import psycopg2
import psycopg2.extras
import yfinance as yf
from curl_cffi import requests as cr
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("refresh_index_membership.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}

# index label (as stored in company_metadata.ftse_index) -> HL page slug
INDEXES = {
    "FTSE 100": "ftse-100",
    "FTSE 250": "ftse-250",
    "FTSE SmallCap": "ftse-small-cap",
    "FTSE AIM 100": "ftse-aim-100",
}

# Refuse to apply if a fetch comes back implausibly short — guards against an HL
# layout change silently emptying an index and mass-deactivating real stocks.
MIN_EXPECTED = {
    "FTSE 100": 90,
    "FTSE 250": 230,
    "FTSE SmallCap": 120,
    "FTSE AIM 100": 90,
}

HL_BASE = "https://www.hl.co.uk/shares/stock-market-summary"


# ── ticker mapping ────────────────────────────────────────────────────────────

def to_yf_symbol(epic: str) -> str:
    """Map an HL EPIC to its Yahoo Finance symbol.

    Handles the LSE quirks generically (no hand-maintained override table):
      * dual-class suffix:  BT.A -> BT-A.L
      * trailing dot:       AV. / RR. / UU. -> AV.L / RR.L / UU.L
      * plain codes:        III -> III.L,  3IN -> 3IN.L
    """
    e = str(epic).strip().upper()
    e = re.sub(r"\.([A-Z])$", r"-\1", e)  # BT.A -> BT-A
    e = e.rstrip(".")                      # AV. -> AV
    return e + ".L"


# ── HL fetch ──────────────────────────────────────────────────────────────────

def _page_table(url: str):
    """Return the EPIC/Name DataFrame on one HL page, or None."""
    r = cr.get(url, impersonate="chrome", timeout=25)
    if r.status_code != 200:
        log.warning(f"  HL {r.status_code}: {url}")
        return None
    best = None
    for t in pd.read_html(StringIO(r.text)):
        cols = [str(c) for c in t.columns]
        if "EPIC" in cols and "Name" in cols:
            sub = t[["EPIC", "Name"]].dropna()
            # keep only real EPIC codes (drops the "Page: 1 2 Next" junk rows)
            sub = sub[sub["EPIC"].astype(str).str.match(r"^[A-Z0-9.&-]{1,7}$")]
            if best is None or len(sub) > len(best):
                best = sub
    return best


def fetch_index(slug: str) -> dict:
    """Fetch all constituents for one HL index slug as {yf_symbol: name}.

    HL paginates at ~110/page and clamps past-the-end pages to a repeat of the
    last valid page, so we stop as soon as a page repeats the previous one.
    """
    base = f"{HL_BASE}/{slug}"
    out, prev = {}, None
    for pg in range(1, 9):
        url = base if pg == 1 else f"{base}?page={pg}"
        df = _page_table(url)
        if df is None or len(df) == 0:
            break
        epics = set(df["EPIC"])
        if prev is not None and epics == prev:
            break  # clamped repeat -> past the last page
        for _, row in df.iterrows():
            out[to_yf_symbol(row["EPIC"])] = str(row["Name"]).strip()
        prev = epics
        time.sleep(0.3)
    return out


def fetch_all_constituents() -> dict:
    """{yf_symbol: (index_label, name)} across all four indices.

    Indices are mutually exclusive tiers, so each symbol gets one label. Aborts
    (returns None) if any index looks suspiciously short.
    """
    merged = {}
    ok = True
    for label, slug in INDEXES.items():
        d = fetch_index(slug)
        n = len(d)
        floor = MIN_EXPECTED[label]
        flag = "" if n >= floor else f"  !! BELOW FLOOR {floor}"
        log.info(f"  {label:14s} {n:>3d} constituents{flag}")
        if n < floor:
            ok = False
        for sym, name in d.items():
            merged[sym] = (label, name)
    if not ok:
        log.error("One or more indices returned too few constituents — aborting "
                  "to avoid mass-deactivating real stocks. No changes written.")
        return None
    return merged


# ── DB ────────────────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def load_db_universe(conn) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol, ftse_index, is_active FROM company_metadata")
    return {r["symbol"]: (r["ftse_index"], r["is_active"]) for r in cur.fetchall()}


def fetch_metadata(symbol: str) -> dict:
    """yfinance company metadata for a brand-new constituent."""
    info = yf.Ticker(symbol).info or {}
    name = info.get("longName") or info.get("shortName")
    return {
        "name": name,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange", "LSE"),
        "currency": info.get("currency", "GBp"),
        "financial_currency": info.get("financialCurrency"),
        "country": info.get("country", "United Kingdom"),
        "description": (info.get("longBusinessSummary") or "")[:2000] or None,
        "full_time_employees": info.get("fullTimeEmployees"),
        "website": info.get("website"),
    }


def insert_new(conn, symbol: str, index_label: str, fallback_name: str):
    meta = fetch_metadata(symbol)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO company_metadata
            (symbol, name, sector, industry, exchange, currency, financial_currency,
             country, description, full_time_employees, website, ftse_index,
             is_active, empty_fetch_count, financials_updated)
        VALUES
            (%(symbol)s, %(name)s, %(sector)s, %(industry)s, %(exchange)s,
             %(currency)s, %(financial_currency)s, %(country)s, %(description)s,
             %(full_time_employees)s, %(website)s, %(ftse_index)s,
             true, 0, NULL)
        ON CONFLICT (symbol) DO UPDATE SET
            ftse_index        = EXCLUDED.ftse_index,
            is_active         = true,
            empty_fetch_count = 0
        """,
        {
            "symbol": symbol,
            "name": meta["name"] or fallback_name,
            "sector": meta["sector"],
            "industry": meta["industry"],
            "exchange": meta["exchange"],
            "currency": meta["currency"],
            "financial_currency": meta["financial_currency"],
            "country": meta["country"],
            "description": meta["description"],
            "full_time_employees": meta["full_time_employees"],
            "website": meta["website"],
            "ftse_index": index_label,
        },
    )
    conn.commit()
    return meta["name"] or fallback_name


def update_moved(conn, symbol: str, index_label: str):
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE company_metadata
        SET ftse_index = %s, is_active = true, empty_fetch_count = 0
        WHERE symbol = %s
        """,
        (index_label, symbol),
    )
    conn.commit()


def discover_child_tables(conn):
    """[(table, symbol_column)] for every base table (not view) keyed by symbol,
    excluding company_metadata itself. Discovered at runtime so new tables are
    purged automatically and the ttm_financials *view* is skipped."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.table_name, c.column_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND c.column_name IN ('symbol', 'company_symbol')
          AND t.table_type = 'BASE TABLE'
          AND c.table_name <> 'company_metadata'
        ORDER BY c.table_name
        """
    )
    return cur.fetchall()


def purge(conn, child_tables, symbol: str):
    """Hard-delete a symbol from every child table, then company_metadata, in one
    transaction. annual/quarterly FKs are satisfied by deleting children first."""
    cur = conn.cursor()
    try:
        for table, col in child_tables:
            cur.execute(f"DELETE FROM {table} WHERE {col} = %s", (symbol,))
        cur.execute("DELETE FROM company_metadata WHERE symbol = %s", (symbol,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── reconcile ─────────────────────────────────────────────────────────────────

DEFAULT_MAX_PURGE = 25  # a normal quarterly reshuffle drops ~10-20 across the four tiers


def _arg_int(flag: str, default: int) -> int:
    if flag in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(flag) + 1])
        except (IndexError, ValueError):
            log.error(f"{flag} requires an integer value")
            sys.exit(2)
    return default


def main():
    apply = "--apply" in sys.argv
    max_purge = _arg_int("--max-purge", DEFAULT_MAX_PURGE)
    mode = "APPLY" if apply else "DRY RUN"
    log.info(f"=== Index membership refresh ({mode}) ===")

    log.info("Fetching current constituents from Hargreaves Lansdown...")
    fetched = fetch_all_constituents()
    if fetched is None:
        sys.exit(1)
    log.info(f"  Total unique constituents: {len(fetched)}")

    conn = get_conn()
    db = load_db_universe(conn)

    fset, dset = set(fetched), set(db)
    new = sorted(fset - dset)
    dropped = sorted(dset - fset)
    moved = sorted(s for s in (fset & dset) if fetched[s][0] != db[s][0])

    print("\n" + "=" * 60)
    print(f"  Index Membership Reconciliation ({mode})")
    print("=" * 60)
    print(f"  Fetched constituents : {len(fset)}")
    print(f"  Current in database  : {len(dset)}")
    print(f"  New                  : {len(new)}")
    print(f"  Moved (tier change)  : {len(moved)}")
    print(f"  Dropped              : {len(dropped)}")
    print("=" * 60)

    if new:
        print(f"\n  NEW ({len(new)}):")
        for s in new:
            print(f"    + {s:10s} {fetched[s][0]:14s} {fetched[s][1]}")
    if moved:
        print(f"\n  MOVED ({len(moved)}):")
        for s in moved:
            print(f"    ~ {s:10s} {db[s][0]} -> {fetched[s][0]}")
    child_tables = discover_child_tables(conn)
    if dropped:
        print(f"\n  DROPPED ({len(dropped)}) - left all tracked indices, will be PURGED:")
        for s in dropped:
            print(f"    - {s:10s} (was {db[s][0]})")
        print(f"\n  Purge removes each from: company_metadata + "
              f"{', '.join(t for t, _ in child_tables)}")

    if not apply:
        print("\n  Dry run - no changes written. Re-run with --apply to commit.\n")
        conn.close()
        return

    print("\n  Applying changes...")
    for s in new:
        try:
            name = insert_new(conn, s, fetched[s][0], fetched[s][1])
            log.info(f"    + inserted {s} ({fetched[s][0]}) - {name}")
            time.sleep(0.3)
        except Exception as e:
            log.error(f"    ! insert failed {s}: {e}")
    for s in moved:
        update_moved(conn, s, fetched[s][0])
        log.info(f"    ~ moved {s}: {db[s][0]} -> {fetched[s][0]}")
    purged = 0
    purges_blocked = len(dropped) > max_purge
    if purges_blocked:
        log.error(f"    ! {len(dropped)} dropped exceeds --max-purge {max_purge} — "
                  f"purges SKIPPED (new/moved still applied). Review the list and "
                  f"re-run with --max-purge {len(dropped)} if it's genuine.")
    else:
        for s in dropped:
            try:
                purge(conn, child_tables, s)
                purged += 1
                log.info(f"    - purged {s} (left all indices)")
            except Exception as e:
                log.error(f"    ! purge failed {s}: {e}")

    conn.close()
    print(f"\n  Done. +{len(new)} new, ~{len(moved)} moved, -{purged} purged.")
    print("  New constituents will get financials on the next updater.py run.\n")
    if purges_blocked:
        sys.exit(1)


if __name__ == "__main__":
    main()
