"""Forward results calendar — which UK companies report in a given week.

SOURCE: the Digital Look UK Company Diary. Server-rendered HTML, no JS, and
`start_date` accepts any Monday, past or future.

Why this source (measured 2026-08-07, don't re-litigate):
  * yfinance `Ticker.calendar` carries a FUTURE earnings date for only ~18% of
    our universe — FTSE 100 36%, FTSE 250 20%, SmallCap 10%, plain AIM 0%.
    Useless as a primary source for a page that is mostly small caps.
  * The RNS `notice_of_results` category resolved just 27 in-universe symbols in
    120 days, and the date sits in the announcement body, not the headline.
  * lse.co.uk and sharecast both 403 a direct fetch; Hargreaves' diary is
    JS-rendered with zero tables in the HTML.

Accuracy: over 5 back-tested weeks, diary dates agreed with when the results RNS
actually landed on 240 of 248 events (96.8%). The eight disagreements (CURY, QTX,
CPI, GTLY, PHP, ITV, SHEL x2) are companies that moved their date — which is
exactly why the cron re-scrapes daily instead of once a week.

MEASUREMENT TRAP, recorded because it nearly produced the wrong verdict: a naive
back-test scores this source at 79%, because 52 diary events had no corroborating
RNS. That is OUR gap, not theirs. `rns_announcements` is a FILTERED feed (~30
rows/day, not the full 300-600 wire) — Focusrite has 3 rows in all of history,
Pennon 2, Solid State 0. Absence from `rns_announcements` is never evidence that
an announcement did not happen.

The diary exposes no ticker (companies link by an internal `csi=` id), so rows
are matched to our universe by name. See `_resolve_symbol` for why that is worth
~70% and why the remainder is fine to lose.

COVERAGE, as distinct from accuracy: the 96.8% above scores only diary events
that EXIST. The diary also drops companies outright, including blue chips —
Aviva's 14 Aug 2026 interims appeared in no diary week between 20 Jul and 31 Aug,
though the same source carried Aviva for Aug 2025 interims and Mar 2026 finals.
Nothing in the pipeline could flag that; a missing row looks like a quiet day.
`fetch_index_earnings_dates` backfills the FTSE 100 from yfinance for exactly
this failure mode. See that docstring for why it is a supplement, not a source.
"""

import os
import re
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import connection, query
from shorts import _normalise_name

router = APIRouter(prefix="/api/results-calendar", tags=["results-calendar"])

_BASE_URL = ("https://companyresearch.digitallook.com/cgi-bin/dlmedia/"
             "event_diary.cgi?action=market_diary&start_date=")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# How many weeks ahead the cron keeps warm. The diary thins out fast — the week
# after next typically has ~65 events vs ~215 for the current week — so there is
# little value in going deeper, and every extra week is another page fetch.
WEEKS_AHEAD = int(os.getenv("RESULTS_CALENDAR_WEEKS_AHEAD", "3"))

# Diary section headings we treat as "this company reports". The diary also
# carries AGMs, ex-dividend dates, dividend payment dates, annual reports, GMs
# and drilling reports; those are deliberately excluded — the page answers
# "who reports this week", not "what corporate admin happens this week".
_EVENT_TYPES = {
    "Finals": "finals",
    "Interims": "interims",
    "Q1": "q1",
    "Q2": "q2",
    "Q3": "q3",
    "Q4": "q4",
    "Trading Announcements": "trading_update",
}

_EVENT_LABELS = {
    "finals": "Full-year results",
    "interims": "Interim results",
    "q1": "Q1 results",
    "q2": "Q2 results",
    "q3": "Q3 results",
    "q4": "Q4 results",
    "trading_update": "Trading update",
    # yfinance gives a date and nothing else — no interim/final distinction — so
    # cross-check rows get a deliberately vague label rather than a guessed one.
    "results": "Results",
}

# ── FTSE 100 cross-check ──────────────────────────────────────────────────────

# Which index to backfill. Deliberately just the FTSE 100: yfinance's forward
# coverage measured 84/100 there but ~20% for the FTSE 250 and 0% for plain AIM,
# so widening it buys almost nothing and costs a request per symbol.
YF_INDEX = os.getenv("RESULTS_CALENDAR_YF_INDEX", "FTSE 100")

# Set to "0" to fall back to diary-only.
YF_CROSS_CHECK = os.getenv("RESULTS_CALENDAR_YF_CROSSCHECK", "1") != "0"

# Pause between symbol lookups. 100 symbols ≈ 40s added to a daily cron.
YF_DELAY = float(os.getenv("RESULTS_CALENDAR_YF_DELAY", "0.3"))

# ── Parsing ───────────────────────────────────────────────────────────────────
#
# The diary is one table: a section header row (<th id="nN">Finals</th>) followed
# by a row of five day cells (<td headers="dN nN">) each holding a <ul> of
# company links. Day index comes from the `dN` header reference, so an empty day
# rendering as a bare <td>&nbsp;</td> simply contributes nothing.

_SECTION_RE = re.compile(r'<th[^>]*id="(n\d+)"[^>]*>.*?<b>(.*?)</b>', re.S)
_CELL_RE = re.compile(r'<td headers="(d[1-5]) (n\d+)"[^>]*>(.*?)</td>', re.S)
_ITEM_RE = re.compile(r'security\.cgi\?csi=(\d+)[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    """Strip tags and unescape the handful of entities the diary emits."""
    s = _TAG_RE.sub("", raw)
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&#39;", "'"),
                 ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def parse_diary(html: str, week_start: date) -> list[dict]:
    """Parse one diary week into event dicts. Pure — no network, no DB."""
    sections = {sid: _text(name) for sid, name in _SECTION_RE.findall(html)}
    events = []
    for day, sid, cell in _CELL_RE.findall(html):
        event_type = _EVENT_TYPES.get(sections.get(sid, ""))
        if not event_type:
            continue
        event_date = week_start + timedelta(days=int(day[1]) - 1)
        for csi, raw_name in _ITEM_RE.findall(cell):
            name = _text(raw_name)
            if name:
                events.append({
                    "event_date": event_date,
                    "week_start": week_start,
                    "event_type": event_type,
                    "source_name": name,
                    "source_id": csi,
                })
    return events


# ── Name resolution ───────────────────────────────────────────────────────────
#
# Raw name matching against company_metadata lands 54%. Two cheap normalisations
# take it to ~70%, and the rest is genuinely not ours (bonds, GDRs, micro-cap
# AIM), so it is correct to lose.
#
# Deliberately NOT done: fuzzy/difflib matching. It was tried and produced
# confident false pairs — Tekcapital->CAPD.L, Aeorema Communications->GAMA.L,
# DSW Capital->SFOR.L. A wrong logo on the wrong day is worse than no logo.

# Listing-vehicle and incorporation noise. A trailing \b is wrong here: after an
# abbreviation's final "." there is no word boundary, so "S.A. (CDI)" would keep
# its "S A". The negative lookahead matches the dotted and undotted forms alike.
_DIARY_NOISE = re.compile(
    r"\((?:DI|CDI|Reg\.?\s*S|each\s+repr[^)]*)\)"
    r"|\b(?:GDR|ADR|NPV|Ltd|Limited|AG|SA|NV|Inc|plc|S\.\s*A|N\.\s*V)\.?(?![A-Za-z])"
    r"|\bEur\s*[\d.]+",
    re.IGNORECASE,
)

# Share-class tails our universe names carry and the diary does not
# ("PANTHEON INTERNATIONAL ORD" vs "Pantheon International").
_OUR_TAIL = re.compile(r"\b(ORD|SHS|NPV)\b.*$")


def _diary_key(name: str) -> str:
    return _normalise_name(re.sub(r"\s+", " ", _DIARY_NOISE.sub(" ", name)).strip(" .,"))


def build_universe_index() -> dict[str, tuple[str, str]]:
    """normalised name -> (symbol, our name), for resolving diary rows.

    Keys per company: the shared normalisation, that with the ORD/SHS tail
    dropped, the same noise-stripping applied to diary names, and a space-stripped
    variant of each (word spacing differs between sources — the same fallback
    shorts.py needs for FCA files).

    The noise-stripping has to run on BOTH sides or it is worse than useless:
    strip "AG" from the diary's "Coca-Cola HBC AG (CDI)" while our own name is
    still "COCA COLA HBC AG" and the two can never meet.

    Ambiguous keys are dropped rather than resolved arbitrarily, so a collision
    can never mislink a logo onto the wrong company.
    """
    index: dict[str, tuple[str, str] | None] = {}
    for row in query("SELECT symbol, name FROM company_metadata WHERE is_active"):
        if not row["name"]:
            continue
        base = _normalise_name(row["name"])
        if not base:
            continue
        value = (row["symbol"], row["name"])
        # _diary_key must see the RAW name: it strips dotted abbreviations
        # ("S.A.", "N.V."), and _normalise_name has already turned those into
        # bare letters by the time `base` exists. Running it on `base` silently
        # does nothing and drops Atalaya Mining Copper, S.A. off the calendar.
        keys = {base, _diary_key(row["name"])}
        keys |= {re.sub(r"\s+", " ", _OUR_TAIL.sub("", k)).strip() for k in list(keys)}
        keys |= {k.replace(" ", "") for k in list(keys)}
        keys.discard("")
        for key in keys:
            if len(key) < 3:
                continue
            if index.get(key, value) != value:
                index[key] = None  # ambiguous — refuse to guess
            else:
                index[key] = value
    return {k: v for k, v in index.items() if v is not None}


def _resolve_symbol(name: str, index: dict) -> tuple[Optional[str], Optional[str]]:
    for key in (_normalise_name(name), _diary_key(name)):
        if not key:
            continue
        hit = index.get(key) or index.get(key.replace(" ", ""))
        if hit:
            return hit
    return None, None


# ── Week arithmetic ───────────────────────────────────────────────────────────


def current_week_start(today: Optional[date] = None) -> date:
    """The Monday of the week the page should currently be showing.

    The view rolls over on SATURDAY: from Saturday onwards you see the week
    ahead, and Mon-Fri you see the week you are actually in. Equivalently, the
    Monday that follows the most recent Saturday — which is this week's Monday
    Mon-Fri, and next week's from Sat/Sun.
    """
    today = today or datetime.now(timezone.utc).date()
    # Monday=0 ... Saturday=5, Sunday=6
    return today - timedelta(days=today.weekday()) + (
        timedelta(days=7) if today.weekday() >= 5 else timedelta(0)
    )


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ── Ingestion ─────────────────────────────────────────────────────────────────


def _fetch_week(week_start: date, timeout: int = 30) -> str:
    req = urllib.request.Request(
        _BASE_URL + week_start.isoformat(), headers={"User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_index_earnings_dates(index: str = YF_INDEX,
                               today: Optional[date] = None) -> dict[str, date]:
    """symbol -> next earnings date, for one index, from yfinance. Network-bound.

    A SUPPLEMENT to the diary, never a replacement — it only covers large caps,
    and it carries no event type. What it is good for is the diary's blind spot:
    a company the diary never lists at all.

    Measured over the FTSE 100 on 2026-08-14:
      * 84/100 carry a date. Of the 59 already elapsed, 37 were judgeable against
        our results RNS: 35 exact day, 2 within a day, 0 wrong by more than a day
        (18 predate the RNS feed, 4 had no corroborating RNS — see the filtered-
        feed trap in the module docstring, those are UNKNOWN and not misses).
      * Where the diary also had a forward date, the two agreed 6 times out of 6.

    GOTCHA that makes the `>= today` filter load-bearing: once a company reports,
    Yahoo leaves the field pointing at the date it just REPORTED rather than
    clearing it. 59 of those 84 dates were in the past. Publishing unfiltered
    would put two thirds of the index on days that have already been and gone.

    Failures are swallowed per symbol: this is a best-effort enrichment and must
    never take the diary refresh down with it.
    """
    import yfinance as yf  # deferred — heaviest import, only this path needs it

    today = today or datetime.now(timezone.utc).date()
    symbols = [r["symbol"] for r in query(
        "SELECT symbol FROM company_metadata WHERE is_active AND ftse_index = %s "
        "ORDER BY symbol", (index,))]

    out: dict[str, date] = {}
    failures = 0
    for symbol in symbols:
        try:
            raw = (yf.Ticker(symbol).calendar or {}).get("Earnings Date") or []
            # Yahoo occasionally returns a two-element ESTIMATED range instead of
            # a confirmed day. Taking the earliest future element keeps the
            # behaviour defined; none of the FTSE 100 did this when measured.
            future = sorted(d for d in raw if isinstance(d, date) and d >= today)
            if future:
                out[symbol] = future[0]
        except Exception as exc:
            failures += 1
            print(f"[results_calendar] yfinance skip {symbol}: "
                  f"{type(exc).__name__}: {exc}")
        time.sleep(YF_DELAY)

    print(f"[results_calendar] yfinance {index}: {len(out)} forward dates "
          f"from {len(symbols)} symbols ({failures} errors)")
    return out


def cross_check_events(yf_dates: dict[str, date], week_start: date,
                       diary_events: list[dict]) -> list[dict]:
    """Rows to ADD to one week from the yfinance dates. Pure — no network, no DB.

    THE DIARY WINS. If it placed a company anywhere in this week, its row is kept
    and the yfinance date is dropped, even when the two disagree — the diary is
    the more accurate source on dates and knows the event type. The rule is
    per-week rather than per-day on purpose: `get_week` only dedups within a
    single day (`DISTINCT ON (event_date, symbol)`), so a yfinance row landing on
    a different day of the same week would render the same logo twice in one
    grid, which reads as two separate results announcements.

    Dates outside Monday-Friday of this week are dropped: the page has five
    columns and nothing would render a Saturday.
    """
    placed = {e["symbol"] for e in diary_events if e.get("symbol")}
    week_end = week_start + timedelta(days=4)
    return [
        {
            "event_date": d,
            "week_start": week_start,
            "event_type": "results",
            # yfinance is keyed by ticker, so the ticker IS the source's natural
            # key here — the diary's equivalent of a printed company name.
            "source_name": symbol,
            "source_id": None,
            "symbol": symbol,
            "company_name": None,  # filled from company_metadata by the caller
            "source": "yfinance",
        }
        for symbol, d in sorted(yf_dates.items())
        if symbol not in placed and week_start <= d <= week_end
    ]


def refresh(weeks_ahead: int = WEEKS_AHEAD, today: Optional[date] = None,
            yf_dates: Optional[dict[str, date]] = None) -> dict:
    """Scrape the current display week plus `weeks_ahead` more and upsert.

    Deleting a week's rows before re-inserting is what lets a MOVED date
    disappear: an upsert alone would leave the company sitting on its old day
    forever. Each week is replaced inside one transaction so the page never
    reads a half-written week.

    The yfinance cross-check is fetched ONCE and reused for every week — its
    dates are absolute, not per-week, and re-querying 100 tickers per week would
    quadruple the cost for identical answers. Pass `yf_dates` to inject a fixture
    or `{}` to skip the network entirely.

    That the cross-check writes into the same DELETE/INSERT transaction is not
    incidental: rows written outside it would be wiped by the next week rewrite.
    """
    start = current_week_start(today)
    weeks = [start + timedelta(weeks=i) for i in range(weeks_ahead + 1)]
    index = build_universe_index()
    names = {row["symbol"]: row["name"] for row in
             query("SELECT symbol, name FROM company_metadata WHERE is_active")}

    if yf_dates is None:
        if YF_CROSS_CHECK:
            try:
                yf_dates = fetch_index_earnings_dates(today=today)
            except Exception as exc:
                # An enrichment must never sink the primary source.
                print(f"[results_calendar] yfinance cross-check unavailable — "
                      f"{type(exc).__name__}: {exc}")
                yf_dates = {}
        else:
            yf_dates = {}

    total = matched = extra_total = 0
    per_week = []
    for week in weeks:
        events = parse_diary(_fetch_week(week), week)
        for e in events:
            e["symbol"], e["company_name"] = _resolve_symbol(e["source_name"], index)
            e["source"] = "diary"

        # Counted before the cross-check is mixed in, so `status` and the match
        # rate still describe the DIARY. Otherwise a working cross-check would
        # mask a total diary outage and the run would exit 0 on a broken scrape.
        diary_count = len(events)
        hit = sum(1 for e in events if e["symbol"])

        extra = cross_check_events(yf_dates, week, events)
        for e in extra:
            e["company_name"] = names.get(e["symbol"])
        events += extra

        with connection() as conn:
            # Pooled connections come back from db.query() with autocommit ON,
            # so this must be set explicitly or the DELETE commits on its own and
            # a failure mid-rewrite leaves the week blank on the live page.
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute("DELETE FROM results_calendar WHERE week_start = %s", (week,))
                for e in events:
                    cur.execute(
                        """INSERT INTO results_calendar
                             (event_date, week_start, event_type, source_name,
                              source_id, symbol, company_name, source)
                           VALUES (%(event_date)s, %(week_start)s, %(event_type)s,
                                   %(source_name)s, %(source_id)s, %(symbol)s,
                                   %(company_name)s, %(source)s)
                           ON CONFLICT (event_date, event_type, source_name)
                           DO UPDATE SET symbol = EXCLUDED.symbol,
                                         company_name = EXCLUDED.company_name,
                                         source = EXCLUDED.source,
                                         fetched_at = NOW()""",
                        e,
                    )
            conn.commit()
            # Hand it back the way the pool's other borrowers expect to find it.
            # (db.query() re-asserts this anyway, and psycopg2's putconn rolls
            # back an aborted transaction, so a failure above is safe too.)
            conn.autocommit = True

        total += diary_count
        matched += hit
        extra_total += len(extra)
        per_week.append({"week_start": week.isoformat(),
                         "events": diary_count, "matched": hit,
                         "cross_check": len(extra)})

    return {
        # Deliberately keyed off the DIARY count alone — see the note above.
        "status": "ok" if total else "empty",
        "weeks": per_week,
        "events": total,
        "matched": matched,
        "cross_check": extra_total,
        "match_pct": round(100 * matched / total, 1) if total else 0.0,
    }


# ── API ───────────────────────────────────────────────────────────────────────


@router.get("")
def get_week(week: Optional[str] = Query(None, description="Any date in the week; defaults to the current display week")):
    """Companies reporting in one week, grouped by weekday.

    Only universe-matched rows are returned — the page renders company logos and
    links to /company/[symbol], neither of which exists without a ticker. The
    count of everything else is still reported as `unmatched`, so the page can
    be honest that the week is bigger than the grid shows.
    """
    if week:
        try:
            week_start = _monday(date.fromisoformat(week))
        except ValueError:
            raise HTTPException(400, "week must be an ISO date (YYYY-MM-DD)")
    else:
        week_start = current_week_start()

    # DISTINCT ON collapses a company listed under two sections for the same day
    # -- the diary files Caledonia Mining and Atalaya under BOTH "Interims" and
    # "Q2", which are the same event described twice, and would otherwise render
    # the logo twice in one column. The keeper is the most specific description:
    # a full-year/interim result outranks a quarterly, which outranks a trading
    # update. A company reporting on two DIFFERENT days keeps both rows.
    rows = query(
        """SELECT DISTINCT ON (r.event_date, r.symbol)
                  r.event_date, r.event_type, r.symbol, r.source,
                  COALESCE(r.company_name, r.source_name) AS name,
                  cm.sector, cm.ftse_index
             FROM results_calendar r
             LEFT JOIN company_metadata cm ON cm.symbol = r.symbol
            WHERE r.week_start = %s AND r.symbol IS NOT NULL
            ORDER BY r.event_date, r.symbol,
                     CASE r.event_type
                       WHEN 'finals'   THEN 1
                       WHEN 'interims' THEN 2
                       WHEN 'q1' THEN 3 WHEN 'q2' THEN 3
                       WHEN 'q3' THEN 3 WHEN 'q4' THEN 3
                       WHEN 'results'  THEN 4
                       ELSE 5
                     END""",
        (week_start,),
    )
    unmatched = query(
        "SELECT count(*) AS c FROM results_calendar WHERE week_start = %s AND symbol IS NULL",
        (week_start,),
    )[0]["c"]

    # One bucket per weekday, always all five, so the grid keeps its shape on a
    # quiet week instead of collapsing to three columns.
    days = []
    for i in range(5):
        day = week_start + timedelta(days=i)
        days.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "companies": [
                {
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "event_type": r["event_type"],
                    "event_label": _EVENT_LABELS.get(r["event_type"], r["event_type"]),
                    "sector": r["sector"],
                    "ftse_index": r["ftse_index"],
                    # Which source put this company on this day. Not rendered —
                    # it is here so a wrong date can be traced without a DB query.
                    "source": r["source"],
                }
                for r in rows if r["event_date"] == day
            ],
        })

    freshness = query(
        "SELECT max(fetched_at) AS f FROM results_calendar WHERE week_start = %s",
        (week_start,),
    )[0]["f"]

    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=4)).isoformat(),
        "prev_week": (week_start - timedelta(weeks=1)).isoformat(),
        "next_week": (week_start + timedelta(weeks=1)).isoformat(),
        "is_current_week": week_start == current_week_start(),
        "total": len(rows),
        "unmatched": unmatched,
        "updated_at": freshness.isoformat() if freshness else None,
        "days": days,
    }
