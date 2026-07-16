"""
FinScope — LSE-Screened Universe Refresh
========================================
Extends the universe beyond the four HL-scraped FTSE tiers with every UK
company listed in London worth >= £50M, sourced from the LSE price-explorer
JSON API (the same data behind londonstockexchange.com/live-markets/...).

Covers the two gap classes the FTSE tiers structurally miss:
  * AIM names outside the AIM 100            -> ftse_index 'AIM'
  * Main Market names outside the FTSE UK
    index series (e.g. WISE after its primary
    listing moved to NYSE)                    -> ftse_index 'Main (non-index)'

Inclusion rules (agreed 2026-07-16):
  * EQUITY lines on AIM or the Main Market
  * incorporated UK-ish: ISIN prefix GB / JE / GG / IM
    (Irish CDIs deliberately excluded; other foreign secondaries too)
  * sterling-quoted (GBX/GBP — screens out GDR/USD secondary lines)
  * ordinary shares only — pref/CCDS/PIBS lines are screened out by the LSE
    instrument-line name (they carry the issuer's real fundamentals on
    yfinance, so only the line name gives them away)
  * not a fund/trust/VCT by name, and passes the yfinance vet at insert time:
    quoteType EQUITY, a live price, and real operations (employees or revenue —
    rejects closed-end funds, preference-share lines, CCDS and shells)
  * market cap >= £50M to enter; existing rows kept until < £40M (hysteresis so
    names hovering at the line don't churn through destructive purges)

Ownership (migration 017): this job owns universe_source='lse_screen' rows
only. hl_index rows are the quarterly HL refresh's (which *demotes* names that
leave the FTSE tiers to lse_screen so this job can keep them with history
intact); manual rows are never touched by either job.

Exit paths for owned rows that stop qualifying — destruction only when the
name is really gone:
  * absent from the LSE feed entirely      -> PURGE (delisted / taken over)
  * eligible but < £40M (hysteresis exit)  -> PURGE (agreed cap-floor design)
  * still listed but fails the rules       -> DEACTIVATE (is_active=false,
    (foreign ISIN, non-sterling, fund name)   history kept) — so a demoted
    Irish-ISIN ex-constituent (the Flutter case) is retired, not erased, and
    reactivates via the relabel path if the rules later admit it.

New names are inserted with financials_updated back-dated on a spread over the
past FIN_STAGGER_DAYS (biggest caps oldest), so a bulk first run interleaves
with updater.py's 25/day rotation instead of starving existing names for weeks
(plain NULL would jump the whole batch to the front of the queue).

Usage (run from backend/):
    python refresh_lse_universe.py            # dry run — report only, no writes
    python refresh_lse_universe.py --apply    # apply changes
    python refresh_lse_universe.py --apply --max-purge 30

Intended cadence: monthly Dokploy cron (the HL job stays quarterly). Safe to
re-run; inserts are idempotent upserts. In --apply mode, if more than
--max-purge lse_screen rows (default 15) would be purged+deactivated, both are
skipped (inserts/relabels still applied) and the run exits non-zero — guards
against a partial or degraded LSE fetch (e.g. ISINs missing from the payload)
mass-retiring real stocks, on top of per-market MIN_EXPECTED floors.
"""

import re
import sys
import time
import logging
from datetime import date, timedelta

import psycopg2.extras
import yfinance as yf
from curl_cffi import requests as cr

from universe_common import (
    arg_int,
    discover_child_tables,
    fetch_metadata,
    get_conn,
    purge,
    record_run,
    to_yf_symbol,
    upsert_company,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("refresh_lse_universe.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── LSE price-explorer API ────────────────────────────────────────────────────
# The grid component of /live-markets/market-data-dashboard/price-explorer.
# Its componentId is stable page config (from /api/v1/pages); if the fetch ever
# starts returning no grid, re-derive it from that endpoint.
_API = "https://api.londonstockexchange.com/api/v1/components/refresh"
_COMPONENT_ID = "block_content:9524a5dd-7053-4f7a-ac75-71d12db796b4"
_HEADERS = {
    "origin": "https://www.londonstockexchange.com",
    "referer": "https://www.londonstockexchange.com/live-markets/market-data-dashboard/price-explorer",
}

MARKETS = ("AIM", "MAINMARKET")
# Abort if a market comes back implausibly short — a partial fetch must never
# drive purges (mirrors the HL job's MIN_EXPECTED).
MIN_EXPECTED = {"AIM": 400, "MAINMARKET": 700}

CAP_IN = 50_000_000    # new names must be at least this big
CAP_OUT = 40_000_000   # existing lse_screen names kept until they fall below this
FIN_STAGGER_DAYS = 30  # bulk inserts spread over this window in updater's rotation
UKISH_ISIN = ("GB", "JE", "GG", "IM")
LABELS = {"AIM": "AIM", "MAINMARKET": "Main (non-index)"}

DEFAULT_MAX_PURGE = 15

# Name-level fund screen — first line of defence; the yfinance vet catches the
# innocently named ones (BioPharma Credit, Volta Finance, ...).
_FUND_NAME_RE = re.compile(
    r"\b(INVESTMENT TRUST|INV TRUST|TRUST PLC|VCT|FUND|FUNDS|PRIVATE EQUITY|"
    r"OPPORTUNITIES|SMALLER COMPANIES|INCOME & GROWTH|INCOME PLC|SPLIT|"
    r"ENHANCED INCOME|RENEWABLES INFRASTRUCTURE|INFRASTRUCTURE INCOME)\b", re.I)

# Instrument-line screen on the LSE `name` field ("8 5/8% NON-CUM STLG PRF #1",
# "CORE CAPITAL DEFERRED SHS (MIN 250 CCDS)"): preference shares, CCDS and PIBS
# are EQUITY-category lines of real operating companies, so the yfinance vet
# sees the issuer's genuine employees/revenue and passes them — the line name
# is the only place the security type shows.
_SECURITY_LINE_RE = re.compile(
    r"\b(PRF|PREF|PREFERENCE|CCDS|PIBS|NON[ -]?CUM|CORE CAPITAL)\b", re.I)

# Lines the rules can't reject but that must not enter the universe. Reason is
# logged; revisit when circumstances change.
SKIP_SYMBOLS = {
    "EVR.L": "EVRAZ — listing suspended since 2022 (sanctions), stale price/cap",
    # Investment vehicles that pass the yfinance vet on real fundamentals
    # (operator-reviewed 2026-07-16):
    "IIG.L": "Intuitive Investments Group — AIM investment company",
    "CGL.L": "Castelnau Group — holding/investment vehicle",
    "BOOK.L": "Literacy Capital — private-equity investment trust",
    "PSDL.L": "Phoenix Spree Deutschland — property fund in wind-down",
    "DUKE.L": "Duke Capital — hybrid-capital investment vehicle",
    "JZCP.L": "JZ Capital Partners — closed-end private-equity fund",
    "MOH.L": "MOH Nippon — property investment vehicle",
    "VUL.L": "Vulcan Two Group — holding vehicle",
    "LDG.L": "Logistics Development Group — investment vehicle despite the freight label",
    "HOME.L": "Home REIT — accounting-scandal history, financials unreliable",
}


def _find_grid(o):
    if isinstance(o, dict):
        if isinstance(o.get("content"), list) and o.get("totalElements") is not None:
            return o
        for v in o.values():
            g = _find_grid(v)
            if g is not None:
                return g
    elif isinstance(o, list):
        for v in o:
            g = _find_grid(v)
            if g is not None:
                return g
    return None


def _total_pages(grid: dict, page_size: int = 100) -> int:
    """Page count for the grid, derived from totalElements when the response
    omits totalPages — a missing key must not silently truncate the fetch to
    one page (which would then trip the MIN_EXPECTED floor and abort the run)."""
    pages = grid.get("totalPages")
    if pages is None:
        pages = -(-(grid.get("totalElements") or 0) // page_size)
    return max(pages, 1)


def fetch_market(market: str) -> list:
    """All EQUITY rows for one LSE market, paginated."""
    rows, page = [], 0
    while True:
        params = f"markets={market}&categories=EQUITY&page={page}&size=100"
        payload = {
            "path": "live-markets/market-data-dashboard/price-explorer",
            "parameters": params.replace("=", "%3D").replace("&", "%26"),
            "components": [{"componentId": _COMPONENT_ID, "parameters": params}],
        }
        r = cr.post(_API, json=payload, impersonate="chrome", timeout=30,
                    headers=_HEADERS)
        r.raise_for_status()
        grid = _find_grid(r.json())
        if grid is None:
            raise RuntimeError(f"no instrument grid in LSE response ({market} p{page})")
        rows.extend(grid["content"])
        if not grid["content"] or page >= _total_pages(grid) - 1:
            return rows
        page += 1
        time.sleep(0.3)


def fetch_all() -> list:
    """Both markets tagged with their market, or None if any looks truncated."""
    out, ok = [], True
    for market in MARKETS:
        rows = fetch_market(market)
        floor = MIN_EXPECTED[market]
        flag = "" if len(rows) >= floor else f"  !! BELOW FLOOR {floor}"
        log.info(f"  {market:11s} {len(rows):>4d} equity lines{flag}")
        if len(rows) < floor:
            ok = False
        for x in rows:
            x["_market"] = market
        out.extend(rows)
    if not ok:
        log.error("One or more LSE markets returned too few rows — aborting so a "
                  "partial fetch can't drive purges. No changes written.")
        return None
    return out


# ── classification ────────────────────────────────────────────────────────────

def classify(raw_rows: list) -> dict:
    """{yf_symbol: {label, name, cap, tidm}} for every line that qualifies for
    the wider universe on the LSE data alone (cap floor applied by the caller —
    entry and exit thresholds differ).

    Multi-line issuers (dual class, multi-currency quotes) collapse to their
    biggest sterling line so each company appears once.
    """
    by_name = {}
    for x in raw_rows:
        tidm = x.get("tidm")
        name = (x.get("issuername") or "").strip()
        cap = x.get("marketcapitalization") or 0
        isin = (x.get("isin") or "").upper()
        if not tidm or not name:
            continue
        if isin[:2] not in UKISH_ISIN:
            continue
        if x.get("currency") not in ("GBX", "GBP"):
            continue
        if _FUND_NAME_RE.search(name):
            continue
        if _SECURITY_LINE_RE.search(x.get("name") or ""):
            continue  # pref/CCDS/PIBS line, not the issuer's ordinary shares
        prev = by_name.get(name)
        if prev is None or cap > prev["cap"]:
            by_name[name] = {"tidm": tidm, "name": name, "cap": cap,
                             "label": LABELS[x["_market"]]}
    out = {}
    for c in by_name.values():
        sym = to_yf_symbol(c["tidm"])
        if sym in SKIP_SYMBOLS:
            log.info(f"  skipping {sym}: {SKIP_SYMBOLS[sym]}")
            continue
        out[sym] = c
    return out


def vet_new(symbol: str) -> tuple:
    """(ok, reason, info) — insert-time yfinance vet for a would-be addition.

    Rejects what the LSE data can't distinguish: closed-end funds with operating
    -company names, preference-share lines, CCDS, shells, dead tickers.
    """
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as e:
        return False, f"yfinance error: {e}", {}
    if info.get("quoteType") != "EQUITY":
        return False, f"quoteType={info.get('quoteType')}", info
    if info.get("regularMarketPrice") is None and info.get("previousClose") is None:
        return False, "no price data", info
    if (info.get("industry") or "") == "Closed-End Fund":
        return False, "closed-end fund", info
    employees = info.get("fullTimeEmployees") or 0
    revenue = info.get("totalRevenue") or 0
    if employees <= 0 and revenue <= 0:
        return False, "no employees and no revenue (fund/pref/shell?)", info
    # Debt/lending funds (BioPharma Credit class) report revenue (interest
    # income) but yfinance leaves their sector/industry blank and they have no
    # staff — a real operating company has at least one of the three.
    if employees <= 0 and not info.get("industry") and not info.get("sector"):
        return False, "no industry/sector and no employees (fund?)", info
    return True, "", info


def insert_new(conn, symbol: str, cand: dict, info: dict, financials_updated):
    """Insert a vetted addition under lse_screen ownership. `info` is the yf
    .info dict vet_new already fetched — reused so each new name costs one
    yfinance call, not two. financials_updated is the caller's stagger date
    (see FIN_STAGGER_DAYS)."""
    meta = fetch_metadata(symbol, info)
    meta["name"] = meta["name"] or cand["name"].title()
    upsert_company(conn, symbol, meta, cand["label"], "lse_screen",
                   financials_updated=financials_updated)
    return meta["name"]


def relabel(conn, symbol: str, label: str):
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE company_metadata
        SET ftse_index = %s, is_active = true, empty_fetch_count = 0
        WHERE symbol = %s
        """,
        (label, symbol),
    )
    conn.commit()


def deactivate(conn, symbol: str):
    """Retire a row without destroying history: still listed on the LSE but no
    longer passing the inclusion rules (foreign ISIN after a re-domicile,
    non-sterling line, fund-name match). is_active=false takes it out of the
    active pipelines; the relabel path reactivates it if it qualifies again."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE company_metadata SET is_active = false WHERE symbol = %s",
        (symbol,),
    )
    conn.commit()


# ── reconcile ─────────────────────────────────────────────────────────────────

def c_keep(cand: dict) -> bool:
    """Exit-threshold check for names already in the universe."""
    return cand["cap"] >= CAP_OUT


def reconcile(eligible: dict, db: dict, feed_syms: set) -> tuple:
    """(new, relabels, to_deactivate, to_purge) — pure so the lifecycle rules
    are unit-testable.

    db is {symbol: {ftse_index, universe_source, is_active}} for ALL rows;
    only lse_screen rows are owned (and thus retire-able) here. feed_syms is
    every symbol present in the raw LSE feed, before any inclusion rule —
    it separates "really gone" (purge) from "listed but no longer qualifies"
    (deactivate, history kept)."""
    owned = {s for s, r in db.items() if r["universe_source"] == "lse_screen"}
    new = sorted(
        s for s, c in eligible.items()
        if s not in db and c["cap"] >= CAP_IN
    )
    relabels = sorted(
        s for s in owned
        if s in eligible and c_keep(eligible[s])
        and (db[s]["ftse_index"] != eligible[s]["label"] or not db[s]["is_active"])
    )
    to_deactivate = sorted(
        s for s in owned
        if s not in eligible and s in feed_syms and db[s]["is_active"]
    )
    to_purge = sorted(
        s for s in owned
        if (s not in eligible and s not in feed_syms)
        or (s in eligible and not c_keep(eligible[s]))
    )
    return new, relabels, to_deactivate, to_purge


def main():
    apply = "--apply" in sys.argv
    max_purge = arg_int("--max-purge", DEFAULT_MAX_PURGE)
    mode = "APPLY" if apply else "DRY RUN"
    log.info(f"=== LSE universe refresh ({mode}) ===")

    log.info("Fetching AIM + Main Market equities from the LSE API...")
    raw = fetch_all()
    if raw is None:
        sys.exit(1)
    eligible = classify(raw)
    log.info(f"  {len(eligible)} UK sterling non-fund companies after classification")
    # Every symbol the feed carries at all (pre-rules): a row missing from this
    # set is really gone (purge); one present but ineligible is only retired.
    feed_syms = {to_yf_symbol(x["tidm"]) for x in raw if x.get("tidm")}

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT symbol, ftse_index, universe_source, is_active "
                "FROM company_metadata")
    db = {r["symbol"]: r for r in cur.fetchall()}
    owned = {s for s, r in db.items() if r["universe_source"] == "lse_screen"}

    new, relabels, to_deactivate, to_purge = reconcile(eligible, db, feed_syms)

    print("\n" + "=" * 60)
    print(f"  LSE Universe Reconciliation ({mode})")
    print("=" * 60)
    print(f"  Eligible from LSE     : {len(eligible)}")
    print(f"  Owned (lse_screen)    : {len(owned)}")
    print(f"  New (>= £50M, vetted at apply): {len(new)}")
    print(f"  Relabel               : {len(relabels)}")
    print(f"  Deactivate (listed, ineligible): {len(to_deactivate)}")
    print(f"  Purge (gone / < £40M) : {len(to_purge)}")
    print("=" * 60)

    if new:
        print(f"\n  NEW ({len(new)}):")
        for s in new:
            c = eligible[s]
            print(f"    + {s:10s} {c['label']:18s} £{c['cap']/1e6:>8,.0f}M  {c['name'][:44]}")
    if relabels:
        print(f"\n  RELABEL ({len(relabels)}):")
        for s in relabels:
            print(f"    ~ {s:10s} {db[s]['ftse_index']} -> {eligible[s]['label']}")
    if to_deactivate:
        print(f"\n  DEACTIVATE ({len(to_deactivate)}) - still listed but fail the "
              f"inclusion rules; history kept:")
        for s in to_deactivate:
            print(f"    - {s:10s} (was {db[s]['ftse_index']})")
    if to_purge:
        print(f"\n  PURGE ({len(to_purge)}) - no longer qualify:")
        for s in to_purge:
            why = "below £40M" if s in eligible else "absent from LSE feed"
            print(f"    - {s:10s} (was {db[s]['ftse_index']}; {why})")

    if not apply:
        print("\n  Dry run - no changes written. Re-run with --apply to commit.\n")
        conn.close()
        return

    print("\n  Applying changes...")
    inserted, vetoed = 0, 0
    # Biggest caps first, back-dated deepest into the stagger window, so they
    # get financials soonest while the batch interleaves with (rather than
    # starves) the existing rotation.
    inserts = sorted(new, key=lambda s: -eligible[s]["cap"])
    for i, s in enumerate(inserts):
        try:
            ok, reason, info = vet_new(s)
            if not ok:
                vetoed += 1
                log.info(f"    x vetoed {s}: {reason}")
                time.sleep(0.4)
                continue
            backdate = date.today() - timedelta(
                days=FIN_STAGGER_DAYS * (len(inserts) - i) // len(inserts))
            name = insert_new(conn, s, eligible[s], info, backdate)
            inserted += 1
            log.info(f"    + inserted {s} ({eligible[s]['label']}) - {name}")
            time.sleep(0.4)
        except Exception as e:
            log.error(f"    ! insert failed {s}: {e}")
    for s in relabels:
        relabel(conn, s, eligible[s]["label"])
        log.info(f"    ~ relabelled {s}: {db[s]['ftse_index']} -> {eligible[s]['label']}")

    purged, deactivated = 0, 0
    # Deactivations are reversible but a degraded feed (e.g. ISINs missing from
    # the payload) would mass-produce them, so they share the purge cap.
    retiring = len(to_purge) + len(to_deactivate)
    purges_blocked = retiring > max_purge
    if purges_blocked:
        log.error(f"    ! {len(to_purge)} purges + {len(to_deactivate)} deactivations "
                  f"exceeds --max-purge {max_purge} — both SKIPPED (inserts/relabels "
                  f"applied). Review and re-run with --max-purge {retiring} if genuine.")
    else:
        for s in to_deactivate:
            try:
                deactivate(conn, s)
                deactivated += 1
                log.info(f"    - deactivated {s} (listed but ineligible; history kept)")
            except Exception as e:
                log.error(f"    ! deactivation failed {s}: {e}")
        child_tables = discover_child_tables(conn)
        for s in to_purge:
            try:
                purge(conn, child_tables, s)
                purged += 1
                log.info(f"    - purged {s} (no longer qualifies)")
            except Exception as e:
                log.error(f"    ! purge failed {s}: {e}")

    record_run(
        conn,
        "lse_universe_refresh",
        "purges_blocked" if purges_blocked else "ok",
        {"eligible": len(eligible), "new": len(new), "inserted": inserted,
         "vetoed": vetoed, "relabelled": len(relabels),
         "deactivated": deactivated, "purged": purged},
    )
    conn.close()
    print(f"\n  Done. +{inserted} inserted ({vetoed} vetoed), "
          f"~{len(relabels)} relabelled, -{deactivated} deactivated, -{purged} purged.")
    print("  New names get financials as the updater rotation reaches them.\n")
    if purges_blocked:
        sys.exit(1)


if __name__ == "__main__":
    main()
