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

  * NEW     — in the index, not in this job's universe -> INSERT (metadata from
              yfinance), is_active=true, financials_updated=NULL so updater.py
              picks it up first on its next run. If the symbol already exists
              under the LSE screen, ownership is promoted to hl_index; if it
              exists as a 'manual' row it is only relabelled — manual ownership
              is never taken over (manual = never auto-purged, migration 017).
  * MOVED   — already in the DB but its index tier changed -> UPDATE ftse_index
              (and reactivate if it had been deactivated).
  * DROPPED — no longer in *any* tracked index -> DEMOTED, not deleted:
              universe_source flips to 'lse_screen' and ftse_index is
              immediately relabelled ('AIM' for ex-AIM-100, otherwise
              'Main (non-index)') so index filters, the FTSE 100 breadth basket
              and cap bucketing stop counting it the moment it leaves.
              refresh_lse_universe.py then decides on its next run whether it
              still qualifies for the wider universe (correcting the label if
              needed) or is really gone (purge). Keeps history (prices, RNS,
              financials) for stocks that merely fell out of the FTSE tiers —
              the way WISE.L was lost in 2026.

Only hl_index rows can be demoted here (migration 017); lse_screen and manual
rows are excluded from the reconciliation sets.

Usage (run from backend/):
    python refresh_index_membership.py            # dry run — report only, no writes
    python refresh_index_membership.py --apply    # apply changes
    python refresh_index_membership.py --apply --max-purge 40
                                                  # raise the unattended demotion cap

Safe to re-run; every write is idempotent (ON CONFLICT upserts). In --apply mode,
if more than --max-purge symbols (default 25) would be demoted, the demotions are
skipped (new/moved still applied) and the run exits non-zero — a second guard,
after the per-index MIN_EXPECTED floors, against a partial HL fetch mass-demoting
real stocks on an unattended cron run.
"""

import sys
import time
import logging
from io import StringIO

import pandas as pd
import psycopg2.extras
from curl_cffi import requests as cr

from universe_common import (
    arg_int,
    fetch_metadata,
    get_conn,
    record_run,
    to_yf_symbol,
    upsert_company,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("refresh_index_membership.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

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

def load_db_universe(conn) -> tuple:
    """(hl, other) — hl: this job's rows ({symbol: (ftse_index, is_active)});
    other: {symbol: ftse_index} for lse_screen/manual rows. Only hl rows are
    reconciled (demoted/moved), but the NEW classification needs `other` so a
    manual row that enters an index is relabelled rather than having its
    ownership stolen (migration 017: manual = never auto-purged)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol, ftse_index, is_active, universe_source "
                "FROM company_metadata")
    hl, other = {}, {}
    for r in cur.fetchall():
        if r["universe_source"] == "hl_index":
            hl[r["symbol"]] = (r["ftse_index"], r["is_active"])
        else:
            other[r["symbol"]] = {"ftse_index": r["ftse_index"],
                                  "source": r["universe_source"]}
    return hl, other


def insert_new(conn, symbol: str, index_label: str, fallback_name: str):
    meta = fetch_metadata(symbol)
    meta["name"] = meta["name"] or fallback_name
    upsert_company(conn, symbol, meta, index_label, "hl_index")
    return meta["name"]


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


def demote_to_lse_screen(conn, symbol: str, old_label: str):
    """Hand a symbol that left all tracked indices to the LSE-screen job.

    Non-destructive: all history is kept. ftse_index is relabelled in the same
    statement — the four tiers are Main Market except AIM 100 — so nothing
    downstream (index filters, the FTSE 100 breadth basket, cap bucketing)
    keeps treating the name as a constituent during the gap until the monthly
    LSE run. refresh_lse_universe.py owns the row from here — its next run
    corrects the label if needed (e.g. a SmallCap exit that moved to AIM), or
    purges/deactivates it if it no longer qualifies for the wider universe."""
    new_label = "AIM" if old_label == "FTSE AIM 100" else "Main (non-index)"
    cur = conn.cursor()
    cur.execute(
        "UPDATE company_metadata SET universe_source = 'lse_screen', "
        "ftse_index = %s WHERE symbol = %s",
        (new_label, symbol),
    )
    conn.commit()


# ── reconcile ─────────────────────────────────────────────────────────────────

DEFAULT_MAX_PURGE = 25  # a normal quarterly reshuffle drops ~10-20 across the four tiers


def main():
    apply = "--apply" in sys.argv
    max_purge = arg_int("--max-purge", DEFAULT_MAX_PURGE)
    mode = "APPLY" if apply else "DRY RUN"
    log.info(f"=== Index membership refresh ({mode}) ===")

    log.info("Fetching current constituents from Hargreaves Lansdown...")
    fetched = fetch_all_constituents()
    if fetched is None:
        sys.exit(1)
    log.info(f"  Total unique constituents: {len(fetched)}")

    conn = get_conn()
    db, other = load_db_universe(conn)

    fset, dset = set(fetched), set(db)
    # A 'manual' row that shows up in an index is only relabelled — its
    # ownership must stay manual (never auto-purged), so it is not NEW.
    manual_moves = sorted(
        s for s in fset - dset
        if other.get(s, {}).get("source") == "manual"
        and other[s]["ftse_index"] != fetched[s][0]
    )
    new = sorted(s for s in fset - dset
                 if other.get(s, {}).get("source") != "manual")
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
    if manual_moves:
        print(f"\n  MANUAL RELABEL ({len(manual_moves)}) - in an index but "
              f"manually owned; label updated, ownership untouched:")
        for s in manual_moves:
            print(f"    ~ {s:10s} {other[s]['ftse_index']} -> {fetched[s][0]}")
    if dropped:
        print(f"\n  DROPPED ({len(dropped)}) - left all tracked indices, will be "
              f"DEMOTED to the LSE screen (refresh_lse_universe.py relabels or purges):")
        for s in dropped:
            print(f"    - {s:10s} (was {db[s][0]})")

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
    for s in manual_moves:
        update_moved(conn, s, fetched[s][0])
        log.info(f"    ~ relabelled manual {s}: {other[s]['ftse_index']} -> "
                 f"{fetched[s][0]} (ownership stays manual)")
    demoted = 0
    demotions_blocked = len(dropped) > max_purge
    if demotions_blocked:
        log.error(f"    ! {len(dropped)} dropped exceeds --max-purge {max_purge} — "
                  f"demotions SKIPPED (new/moved still applied). Review the list and "
                  f"re-run with --max-purge {len(dropped)} if it's genuine.")
    else:
        for s in dropped:
            try:
                demote_to_lse_screen(conn, s, db[s][0])
                demoted += 1
                log.info(f"    - demoted {s} to lse_screen (left all indices)")
            except Exception as e:
                log.error(f"    ! demotion failed {s}: {e}")

    record_run(
        conn,
        "index_refresh",
        "demotions_blocked" if demotions_blocked else "ok",
        {"new": len(new), "moved": len(moved), "manual_relabelled": len(manual_moves),
         "demoted": demoted, "dropped": len(dropped), "universe": len(fset)},
    )
    conn.close()
    print(f"\n  Done. +{len(new)} new, ~{len(moved)} moved, -{demoted} demoted.")
    print("  New constituents will get financials on the next updater.py run.\n")
    if demotions_blocked:
        sys.exit(1)


if __name__ == "__main__":
    main()
