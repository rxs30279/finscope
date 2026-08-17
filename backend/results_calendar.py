"""Forward results calendar — which UK companies report in a given week.

SOURCE: the Sharecast UK Company Diary. Server-rendered HTML, no JS.

WHY NOT DIGITAL LOOK, the original source: it went dark on 2026-08-16. Every host
on its estate (www / companyresearch / companyresearch2 .digitallook.com, all one
IP) 302-redirects to static.digitallook.com/maintenance.html, with no date, no
ETA and no stated reason. It is a deliberate maintenance mode, not a crash, and
not us being blocked — a fetch from an unrelated network gets the same redirect.
Do NOT go hunting for a param or User-Agent fix; that was ruled out by probing
the root, a nonsense path, past weeks that had previously scraped fine, and both
schemes. Note the redirect is invisible to `urllib`, which follows it silently:
the "849-byte error page" that every URL appeared to return WAS the maintenance
page all along.

Why Sharecast (measured 2026-08-17 against the two weeks we still held Digital
Look rows for, don't re-litigate):
  * Coverage BEATS Digital Look: 70 vs 68 in-universe symbols for the week of
    3 Aug, 33 vs 32 for 10 Aug. It adds MYI/OXB/SDG/SRAD/TRIG and drops
    CABP/HWG/VTY (genuinely absent, not a name-match failure), so both sources
    have holes and Sharecast's are fewer.
  * Dates agree with Digital Look on 97 of 97 shared symbols, same day.
  * Accuracy vs our own results RNS: 79 exact, 0 within a day, 0 wrong.
  * It CARRIES AVIVA on 14 Aug as "Interims" — the FTSE 100 omission that forced
    the yfinance cross-check into existence in the first place.
  * Section labels are identical to Digital Look's, so `_EVENT_TYPES` transferred
    unchanged. The two are the same underlying data product, re-skinned.

MEASUREMENT TRAP, recorded because it nearly produced the wrong verdict on the
original source evaluation: scoring a diary against `rns_announcements` naively
understates it badly, because plenty of real events have no corroborating RNS.
That is OUR gap, not the source's. `rns_announcements` is a FILTERED feed (~30
rows/day, not the full 300-600 wire) — Focusrite has 3 rows in all of history,
Pennon 2, Solid State 0. Absence from `rns_announcements` is never evidence that
an announcement did not happen. Only PRESENCE is evidence.

The diary exposes no ticker (companies link by a name slug), so rows are matched
to our universe by name. See `_resolve_symbol` for why that is worth ~70% and why
the remainder is fine to lose.

COVERAGE, as distinct from accuracy: an accuracy score only ever grades events
that EXIST. Both diaries drop companies outright, including blue chips, and
nothing in the pipeline can flag that — a missing row looks exactly like a quiet
day. `fetch_index_earnings_dates` backfills the FTSE 100 from yfinance for that
failure mode; see its docstring for why it is a supplement, not a source. It is
kept even though Sharecast covers Aviva, because the failure mode it guards has
not gone away, only got rarer.

OUTAGE BEHAVIOUR, learned the hard way when Digital Look vanished: `refresh`
rewrites each week DELETE-then-INSERT, so a silently-empty scrape wiped four
weeks of good rows and left the page blank. The cron did exit 1, but only after
the delete — it alerted without protecting anything. Now a week is left ALONE
unless the scrape actually returned something, and `_fetch_week` raises
`DiaryUnavailable` when the page arrives without a diary table at all, which is
the shape both outages took. See `refresh` and `source_status`.
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

_BASE_URL = "https://www.sharecast.com/company_diary"


class DiaryUnavailable(RuntimeError):
    """The page came back without a diary table at all.

    Distinct from "the table was there and held no results", which is a real,
    quiet week. This is the shape of every failure observed so far — an outage,
    a week outside the serving window, or a layout change — and `refresh` treats
    it as "know nothing, touch nothing" rather than as an empty week.
    """

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

# How close a yfinance date may sit to a results announcement the company has
# ALREADY made before we treat it as an echo of that announcement rather than a
# forecast of the next one. See drop_reported_dates for the measurements.
REPORTED_WINDOW_DAYS = int(os.getenv("RESULTS_CALENDAR_REPORTED_WINDOW_DAYS", "30"))

# RNS categories that mean "this company has reported". Trading updates are
# deliberately excluded: a company can legitimately issue one a fortnight after
# its finals, and treating that as a report would suppress real forward dates.
_RESULTS_CATEGORIES = ("final_results", "interim_results", "quarterly")

# How long the diary may go without writing a row before the page says so. The
# cron runs daily, so this is two missed runs plus slack — long enough that a
# single failed run does not cry wolf, short enough to catch a real outage on its
# second day.
STALE_HOURS = int(os.getenv("RESULTS_CALENDAR_STALE_HOURS", "36"))

# ── Parsing ───────────────────────────────────────────────────────────────────
#
# One table, `class="eventdiaryBg"`, with a five-column Mon-Fri thead. Its body
# alternates: a full-width section header row (<th colspan='5'>...<b>Finals</b>),
# then one row of exactly five <td> day cells, each holding a <ul> of company
# links (<a href=".../equity/Some_Slug">Name</a>).
#
# The day comes from CELL POSITION, not from an attribute — unlike Digital Look,
# which labelled cells `headers="dN nN"`. That is safe here only because empty
# days still render as <td><ul></ul></td> rather than being omitted, so the five
# cells always line up with Monday-Friday. The `len(cells) != 5` guard below is
# what keeps a layout change from silently shifting every company by a day, which
# is a far worse failure than dropping the week.

_TABLE_RE = re.compile(r'<table[^>]*class="[^"]*eventdiaryBg[^"]*"[^>]*>(.*?)</table>', re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_SECTION_RE = re.compile(r"<th[^>]*colspan=['\"]5['\"][^>]*>.*?<b>(.*?)</b>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_ITEM_RE = re.compile(r'href="[^"]*/equity/([^"]+)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    """Strip tags and unescape the handful of entities the diary emits."""
    s = _TAG_RE.sub("", raw)
    for a, b in (("&amp;", "&"), ("&nbsp;", " "), ("&#39;", "'"),
                 ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def has_diary_table(html: str) -> bool:
    """Whether the page carries a diary table at all.

    The out-of-window and outage responses are both a normal-looking 200 page of
    roughly 94KB with the surrounding furniture and no table, so this is the only
    way to tell "nothing scheduled" from "nothing served".
    """
    return _TABLE_RE.search(html) is not None


def parse_diary(html: str, week_start: date) -> list[dict]:
    """Parse one diary week into event dicts. Pure — no network, no DB."""
    table = _TABLE_RE.search(html)
    if not table:
        return []
    events = []
    section = None
    for row in _ROW_RE.findall(table.group(1)):
        header = _SECTION_RE.search(row)
        if header:
            section = _text(header.group(1))
            continue
        if section is None:
            continue
        cells = _CELL_RE.findall(row)
        # Consume the section either way: a header always describes the next day
        # row, so leaving it set would attribute the FOLLOWING section's
        # companies to this one if anything unexpected sits between them.
        event_type, section = _EVENT_TYPES.get(section), None
        if len(cells) != 5 or not event_type:
            continue
        for offset, cell in enumerate(cells):
            event_date = week_start + timedelta(days=offset)
            for slug, raw_name in _ITEM_RE.findall(cell):
                name = _text(raw_name)
                if name:
                    events.append({
                        "event_date": event_date,
                        "week_start": week_start,
                        "event_type": event_type,
                        "source_name": name,
                        # The source's own key for the company. A name slug here
                        # where Digital Look had a numeric csi id; the column is
                        # free text and only ever used for tracing.
                        "source_id": slug,
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


def week_url(week_start: date, today: Optional[date] = None) -> str:
    """The diary URL for one week.

    GOTCHA, and the reason this is not just an f-string: the week containing
    today is served ONLY at the bare `/company_diary`. Asking for it by date —
    `/company_diary/2026-08-17` on 17 Aug — returns the furniture-only page with
    no table, exactly like an out-of-range week. Getting this wrong silently
    empties the single most important week on the page.

    Note this keys off the REAL calendar week, not `current_week_start()`. Those
    differ every weekend: from Saturday the page displays the week ahead, which
    the source still considers a future week and addresses by date.

    Serving window, probed 2026-08-17: roughly the current week -2 to +8. Outside
    it the page renders without a table. The cron only ever asks for the current
    week plus `WEEKS_AHEAD`, so it stays well inside.
    """
    today = today or datetime.now(timezone.utc).date()
    live_week = today - timedelta(days=today.weekday())
    return _BASE_URL if week_start == live_week else f"{_BASE_URL}/{week_start.isoformat()}"


def _fetch_week(week_start: date, timeout: int = 30,
                today: Optional[date] = None) -> str:
    """Fetch one diary week, or raise DiaryUnavailable if it has no table.

    Raising rather than returning a tableless page is what lets `refresh` tell a
    dead source from a quiet week. Digital Look's outage was invisible precisely
    because it looked like a successful fetch that happened to parse to nothing.
    """
    url = week_url(week_start, today)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    if not has_diary_table(body):
        raise DiaryUnavailable(
            f"no diary table at {url} ({len(body)} bytes) — source down, week "
            f"outside its serving window, or the layout changed")
    return body


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


def recent_results_dates(today: Optional[date] = None,
                         window_days: int = REPORTED_WINDOW_DAYS) -> dict[str, date]:
    """symbol -> the day of its most recent results RNS, within `window_days`.

    Feeds `drop_reported_dates`. Looking back exactly `window_days` from today is
    sufficient rather than arbitrary: the filter only ever compares against a
    yfinance date that already passed the `>= today` test, so a report older than
    that can never fall inside the window of any surviving date.

    This reads PRESENCE in `rns_announcements`, which is sound even though the
    feed is filtered (see the module docstring). A results RNS we did capture is
    proof the company reported; one we missed just means no suppression, which
    leaves the old behaviour. The failure mode is fail-open by construction.
    """
    today = today or datetime.now(timezone.utc).date()
    rows = query(
        """SELECT symbol, max(published_at)::date AS reported
             FROM rns_announcements
            WHERE symbol IS NOT NULL
              AND category = ANY(%s)
              AND published_at >= %s
            GROUP BY symbol""",
        (list(_RESULTS_CATEGORIES), today - timedelta(days=window_days)),
    )
    return {r["symbol"]: r["reported"] for r in rows}


def drop_reported_dates(yf_dates: dict[str, date], last_reported: dict[str, date],
                        window_days: int = REPORTED_WINDOW_DAYS) -> dict[str, date]:
    """Strip yfinance dates that are an echo of results already announced. Pure.

    `fetch_index_earnings_dates` documents Yahoo leaving the field pointing at the
    date a company just reported, which the `>= today` filter catches. What that
    filter cannot catch is the same field drifting FORWARDS after the event, and
    it does:
      * AV.L reported interims on Fri 14 Aug 2026 at 06:00. Yahoo then moved its
        Earnings Date to 17 Aug, so the Sunday cron planted Aviva on the Monday of
        the following week — a second logo for a result that had already landed.
      * IGG.L reported half-year results on 30 Jul 2026. Yahoo moved it to 19 Aug.
    Both dates are in the future when read, so nothing upstream rejects them, and
    the diary carries neither company, so `cross_check_events` has nothing to
    defer to either.

    The comparison is date-to-REPORT, not date-to-today, so the verdict does not
    depend on which day the cron happens to run. A UK company does not publish two
    sets of results inside a month — the tightest legitimate spacing is a
    quarterly reporter at ~90 days — so a predicted date sitting within
    `window_days` of one it already filed is the echo, not the next cycle.
    """
    return {
        symbol: d
        for symbol, d in yf_dates.items()
        if not (symbol in last_reported
                and 0 <= (d - last_reported[symbol]).days <= window_days)
    }


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
            yf_dates: Optional[dict[str, date]] = None,
            last_reported: Optional[dict[str, date]] = None) -> dict:
    """Scrape the current display week plus `weeks_ahead` more and upsert.

    Deleting a week's rows before re-inserting is what lets a MOVED date
    disappear: an upsert alone would leave the company sitting on its old day
    forever. Each week is replaced inside one transaction so the page never
    reads a half-written week.

    A week is only rewritten when the scrape actually returned something to write.
    If the fetch raises, or parses to zero events while the stored week still
    holds diary rows, the week is SKIPPED untouched and reported as such. Without
    that, a source outage does not merely stall the page, it empties it — which is
    what happened on 2026-08-16 (see the module docstring). A week with no stored
    diary rows is still rewritten on an empty parse, because that is
    indistinguishable from a genuinely quiet week and is how a new week enters.

    The yfinance cross-check is fetched ONCE and reused for every week — its
    dates are absolute, not per-week, and re-querying 100 tickers per week would
    quadruple the cost for identical answers. Pass `yf_dates` to inject a fixture
    or `{}` to skip the network entirely; `last_reported` is likewise injectable
    and otherwise read from `recent_results_dates`.

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

    if yf_dates:
        if last_reported is None:
            last_reported = recent_results_dates(today=today)
        kept = drop_reported_dates(yf_dates, last_reported)
        for symbol in sorted(set(yf_dates) - set(kept)):
            print(f"[results_calendar] yfinance {symbol} {yf_dates[symbol]} dropped "
                  f"— already reported {last_reported[symbol]}")
        yf_dates = kept

    # How many diary rows each week is currently holding. Read up front, in one
    # query, because the guard below has to know what it would be destroying
    # BEFORE the DELETE runs.
    stored_diary = {r["week_start"]: r["c"] for r in query(
        "SELECT week_start, count(*) AS c FROM results_calendar "
        "WHERE source = 'diary' AND week_start = ANY(%s) GROUP BY week_start",
        (weeks,))}

    total = matched = extra_total = 0
    per_week = []
    skipped = []
    for week in weeks:
        try:
            html = _fetch_week(week, today=today)
        except Exception as exc:
            # A week we could not read is a week we know nothing about, so it
            # must not be rewritten from an empty parse. DiaryUnavailable lands
            # here too: a tableless page is no more informative than a timeout.
            print(f"[results_calendar] {week}: fetch failed, week left untouched "
                  f"— {type(exc).__name__}: {exc}")
            skipped.append(week.isoformat())
            per_week.append({"week_start": week.isoformat(), "events": 0,
                             "matched": 0, "cross_check": 0, "skipped": "fetch_failed"})
            continue

        events = parse_diary(html, week)
        if not events and stored_diary.get(week):
            print(f"[results_calendar] {week}: diary parsed 0 events but "
                  f"{stored_diary[week]} rows are stored — week left untouched")
            skipped.append(week.isoformat())
            per_week.append({"week_start": week.isoformat(), "events": 0,
                             "matched": 0, "cross_check": 0, "skipped": "empty_parse"})
            continue

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
        # Deliberately keyed off the DIARY count alone — see the note above. A
        # week skipped to protect its stored rows still counts as zero here, so
        # an outage that freezes the page is still reported as a failure.
        "status": "ok" if total else "empty",
        "weeks": per_week,
        "events": total,
        "matched": matched,
        "cross_check": extra_total,
        "skipped": skipped,
        "match_pct": round(100 * matched / total, 1) if total else 0.0,
    }


# ── Source health ─────────────────────────────────────────────────────────────


def diary_last_success() -> Optional[datetime]:
    """When the diary last wrote a row, for any week. None if it never has.

    This is the last SUCCESSFUL scrape, and no extra bookkeeping is needed to
    know it: rows are only written when a week parsed to something, weeks are
    never pruned once written, and the outage guard in `refresh` means a failed
    run cannot touch `fetched_at` at all. A separate run marker would only
    duplicate what the rows already say.

    Reads diary rows alone on purpose. The yfinance cross-check keeps writing
    happily through a diary outage — that is the whole point of it — so a max
    over every row would report the calendar as fresh while its primary source
    was down, which is exactly the lie this exists to stop.
    """
    rows = query("SELECT max(fetched_at) AS f FROM results_calendar "
                 "WHERE source = 'diary'")
    return rows[0]["f"] if rows else None


def source_status(week_start: date, last_success: Optional[datetime],
                  now: Optional[datetime] = None) -> dict:
    """Whether the page can vouch for `week_start`. Pure — no DB, no network.

    Only weeks the cron actually maintains can go stale. A past week is a
    historical record that nothing refreshes by design, so flagging it would be
    permanent noise on every archive view.

    `stale` is the flag the banner needs, and it exists because a blank grid is
    ambiguous in the worst possible direction: the module docstring's warning
    that "a missing row looks like a quiet day" applies to the whole page at
    once when the source is down. Silence has to be distinguishable from
    "nothing scheduled" or the page states a confident falsehood.
    """
    now = now or datetime.now(timezone.utc)
    maintained = week_start >= current_week_start(now.date())
    age_hours = ((now - last_success).total_seconds() / 3600
                 if last_success else None)
    return {
        "diary_last_success": last_success.isoformat() if last_success else None,
        "stale": maintained and (age_hours is None or age_hours > STALE_HOURS),
        "stale_after_hours": STALE_HOURS,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
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
        # Whether the primary source is still answering. `updated_at` cannot
        # carry this: it is a max over the week's rows including the yfinance
        # cross-check, which stays fresh right through a diary outage.
        "source_status": source_status(week_start, diary_last_success()),
        "days": days,
    }
