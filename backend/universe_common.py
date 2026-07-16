"""Shared plumbing for the two universe-refresh jobs.

refresh_index_membership.py (HL FTSE tiers, quarterly) and
refresh_lse_universe.py (LSE price-explorer screen) both need the same DB
config, EPIC/TIDM -> Yahoo mapping, new-company metadata fetch, child-table
purge machinery and pipeline_runs stamping. Kept import-side-effect-free so
either job can configure its own logging.
"""

import logging
import os
import re
import sys

import psycopg2
import psycopg2.extras
import yfinance as yf
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def to_yf_symbol(epic: str) -> str:
    """Map an HL EPIC / LSE TIDM to its Yahoo Finance symbol.

    Handles the LSE quirks generically (no hand-maintained override table):
      * dual-class suffix:  BT.A -> BT-A.L
      * trailing dot:       AV. / RR. / UU. -> AV.L / RR.L / UU.L
      * plain codes:        III -> III.L,  3IN -> 3IN.L
    """
    e = str(epic).strip().upper()
    e = re.sub(r"\.([A-Z])$", r"-\1", e)  # BT.A -> BT-A
    e = e.rstrip(".")                      # AV. -> AV
    return e + ".L"


def fetch_metadata(symbol: str, info: dict = None) -> dict:
    """yfinance company metadata for a brand-new constituent.

    Pass `info` when the caller already holds the symbol's yf .info dict (the
    LSE job's vet fetches it) so each new name costs one yfinance call, not two.
    """
    if info is None:
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


def upsert_company(conn, symbol: str, meta: dict, ftse_index: str, source: str,
                   financials_updated=None):
    """Insert-or-refresh one company row on behalf of a refresh job.

    On conflict the row is relabelled, reactivated and its ownership taken over
    by the calling job — EXCEPT 'manual' rows, whose universe_source is
    preserved: they are the operator's and must never re-enter either job's
    auto-purge lifecycle (migration 017), even when they show up in an index or
    the LSE screen. financials_updated is only set on fresh inserts; an existing
    row keeps its slot in updater.py's rotation.
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO company_metadata
            (symbol, name, sector, industry, exchange, currency, financial_currency,
             country, description, full_time_employees, website, ftse_index,
             universe_source, is_active, empty_fetch_count, financials_updated)
        VALUES
            (%(symbol)s, %(name)s, %(sector)s, %(industry)s, %(exchange)s,
             %(currency)s, %(financial_currency)s, %(country)s, %(description)s,
             %(full_time_employees)s, %(website)s, %(ftse_index)s,
             %(universe_source)s, true, 0, %(financials_updated)s)
        ON CONFLICT (symbol) DO UPDATE SET
            ftse_index        = EXCLUDED.ftse_index,
            universe_source   = CASE WHEN company_metadata.universe_source = 'manual'
                                     THEN 'manual'
                                     ELSE EXCLUDED.universe_source END,
            is_active         = true,
            empty_fetch_count = 0
        """,
        {**meta, "symbol": symbol, "ftse_index": ftse_index,
         "universe_source": source, "financials_updated": financials_updated},
    )
    conn.commit()


def arg_int(flag: str, default: int) -> int:
    """Read `--flag N` from sys.argv, exiting non-zero on a malformed value."""
    if flag in sys.argv:
        try:
            return int(sys.argv[sys.argv.index(flag) + 1])
        except (IndexError, ValueError):
            log.error(f"{flag} requires an integer value")
            sys.exit(2)
    return default


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


def record_run(conn, pipeline: str, status: str, detail: dict):
    """Stamp pipeline_runs so healthcheck.py can tell the job ran — a
    zero-change apply leaves no other DB trace (migration 008)."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
        VALUES (%s, NOW(), %s, %s)
        ON CONFLICT (pipeline) DO UPDATE SET
            last_run_at = EXCLUDED.last_run_at,
            status      = EXCLUDED.status,
            detail      = EXCLUDED.detail
        """,
        (pipeline, status, psycopg2.extras.Json(detail)),
    )
    conn.commit()
