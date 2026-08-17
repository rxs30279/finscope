import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta, timezone

import pytest

from results_calendar import (
    STALE_HOURS,
    _diary_key,
    _resolve_symbol,
    cross_check_events,
    current_week_start,
    drop_reported_dates,
    has_diary_table,
    parse_diary,
    source_status,
    week_url,
)


# A cut-down copy of the real Sharecast markup (week of 3 Aug 2026), keeping
# every structural feature the parser depends on: the eventdiaryBg table, a
# full-width section header row, five POSITIONAL day cells per section, an empty
# day rendered as <td><ul></ul></td>, entity-escaped names, trailing whitespace
# inside the anchor, and a section we deliberately ignore.
#
# The empty cells matter more here than they look: the day comes from cell
# position, so a fixture that omitted them would pass while the real page shifted
# every company by a day.
def _cell(*entries):
    lis = "".join(
        f'<li><a href="https://www.sharecast.com/equity/{slug}">{name}</a></li>'
        for slug, name in entries)
    return f"<td><ul>{lis}</ul></td>"


def _section(title, *days):
    cells = "".join(_cell(*d) for d in days)
    return (f"<tr><th colspan='5'><a id='{title}'></a><b>{title}</b></th></tr>"
            f"<tr>{cells}</tr>")


DIARY_HTML = (
    '<table class="eventdiaryBg table-xs"><thead><tr><th>Monday</th>'
    "<th>Tuesday</th><th>Wednesday</th><th>Thursday</th><th>Friday</th>"
    "</tr></thead><tbody>"
    + _section("Finals",
               [("Crimson_Tide", "Crimson Tide")],
               [("Filtronic", "Filtronic")],
               [],
               [("Diageo", "Diageo"), ("PZ_Cussons", "PZ Cussons")],
               [])
    + _section("Interims",
               [("FC_Investment_Trust", "F&amp;C Investment Trust")],
               [("CCEP", "Coca-Cola Europacific Partners (DI)"),
                ("Convatec", "Convatec Group  ")],
               [], [], [])
    + _section("AGMs",
               [("Some_AGM_Company", "Some AGM Company")],
               [], [], [], [])
    + "</tbody></table>"
)

WEEK = date(2026, 8, 3)


# ── parse_diary ───────────────────────────────────────────────────────────────


def test_parse_diary_maps_day_cells_to_dates():
    events = parse_diary(DIARY_HTML, WEEK)
    by_name = {e["source_name"]: e for e in events}
    assert by_name["Crimson Tide"]["event_date"] == date(2026, 8, 3)   # d1 = Monday
    assert by_name["Filtronic"]["event_date"] == date(2026, 8, 4)      # d2 = Tuesday
    assert by_name["Diageo"]["event_date"] == date(2026, 8, 6)         # d4 = Thursday


def test_parse_diary_reads_event_type_from_the_section_header():
    events = {e["source_name"]: e["event_type"] for e in parse_diary(DIARY_HTML, WEEK)}
    assert events["Diageo"] == "finals"
    assert events["F&C Investment Trust"] == "interims"


def test_parse_diary_ignores_non_results_sections():
    """AGMs, ex-dividends and dividend payments share the same table — the page
    answers "who reports", so only the results sections are kept."""
    names = {e["source_name"] for e in parse_diary(DIARY_HTML, WEEK)}
    assert "Some AGM Company" not in names


def test_parse_diary_unescapes_entities_and_trims():
    names = {e["source_name"] for e in parse_diary(DIARY_HTML, WEEK)}
    assert "F&C Investment Trust" in names          # &amp; decoded
    assert "Convatec Group" in names                # trailing whitespace trimmed


def test_parse_diary_skips_empty_days():
    """A day with no events renders as a bare <td>&nbsp;</td> with no headers
    attribute, so it must contribute nothing rather than shifting later days."""
    events = parse_diary(DIARY_HTML, WEEK)
    assert not [e for e in events if e["event_date"] == date(2026, 8, 5)]


def test_parse_diary_carries_the_source_id():
    events = {e["source_name"]: e["source_id"] for e in parse_diary(DIARY_HTML, WEEK)}
    assert events["Diageo"] == "Diageo"


def test_parse_diary_on_junk_returns_nothing_rather_than_raising():
    assert parse_diary("<html><body>nope</body></html>", WEEK) == []


def test_parse_diary_refuses_a_day_row_that_is_not_five_cells_wide():
    """The day is the cell's POSITION, so a row of the wrong width would shift
    every company onto the wrong day. Dropping the section is the safe failure —
    a wrong date is far worse than a missing one."""
    narrow = DIARY_HTML.replace("<td><ul></ul></td>", "", 1)
    names = {e["source_name"] for e in parse_diary(narrow, WEEK)}
    assert "Diageo" not in names          # the mangled Finals row is dropped
    assert "Convatec Group" in names      # later sections still parse


def test_parse_diary_does_not_leak_a_section_across_rows():
    """A header describes the row immediately after it. If an unexpected row
    intervenes, the companies below must not inherit the previous section's
    event type."""
    spliced = DIARY_HTML.replace(
        "<tr><th colspan='5'><a id='Interims'></a>",
        "<tr><td>stray</td></tr><tr><th colspan='5'><a id='Interims'></a>")
    events = {e["source_name"]: e["event_type"] for e in parse_diary(spliced, WEEK)}
    assert events.get("Convatec Group") == "interims"


# ── week addressing ───────────────────────────────────────────────────────────
#
# The week containing today is served ONLY at the bare URL; asking for it by date
# returns a page with no table, exactly like an out-of-range week. That makes
# this the difference between a full current week and an empty one.

BARE = "https://www.sharecast.com/company_diary"


def test_the_live_week_is_requested_without_a_date():
    assert week_url(date(2026, 8, 17), today=date(2026, 8, 17)) == BARE


def test_any_day_inside_the_live_week_still_means_the_bare_url():
    for day in range(17, 24):   # Mon 17 Aug through Sun 23 Aug
        assert week_url(date(2026, 8, 17), today=date(2026, 8, day)) == BARE


def test_other_weeks_are_requested_by_date():
    assert week_url(date(2026, 8, 24), today=date(2026, 8, 17)) == f"{BARE}/2026-08-24"
    assert week_url(date(2026, 8, 10), today=date(2026, 8, 17)) == f"{BARE}/2026-08-10"


def test_the_weekend_display_week_is_addressed_by_date_not_bare():
    """From Saturday the page shows the week AHEAD, but the source still counts
    the calendar week as current — so the displayed week is a dated fetch. Keying
    this off current_week_start() instead of the real week would ask for next
    week at the bare URL and silently get this week's companies."""
    saturday = date(2026, 8, 22)
    assert current_week_start(saturday) == date(2026, 8, 24)
    assert week_url(date(2026, 8, 24), today=saturday) == f"{BARE}/2026-08-24"
    assert week_url(date(2026, 8, 17), today=saturday) == BARE


# ── distinguishing a dead source from a quiet week ────────────────────────────


def test_a_page_with_a_diary_table_is_available():
    assert has_diary_table(DIARY_HTML) is True


def test_the_tableless_page_is_not_mistaken_for_a_quiet_week():
    """Both the outage and the out-of-window responses are a normal 200 page of
    ~94KB with all the furniture and no table. Parsing it yields zero events,
    which is indistinguishable from a genuinely quiet week — hence the explicit
    check rather than relying on the event count."""
    furniture = "<html><body><div class='nav'>Company diary</div></body></html>"
    assert has_diary_table(furniture) is False
    assert parse_diary(furniture, WEEK) == []


# ── name resolution ───────────────────────────────────────────────────────────

INDEX = {
    "DIAGEO": ("DGE.L", "Diageo plc"),
    "COCA COLA EUROPACIFIC PARTNERS": ("CCEP.L", "Coca-Cola Europacific Partners PLC"),
    "F AND C INVESTMENT TRUST": ("FCIT.L", "F&C Investment Trust Ord"),
    "PANTHEON INTERNATIONAL": ("PIN.L", "Pantheon International Ord"),
}


def test_resolves_a_plain_name():
    assert _resolve_symbol("Diageo", INDEX)[0] == "DGE.L"


def test_resolves_through_a_depositary_interest_suffix():
    """The diary carries listing-vehicle noise our names never have; without
    stripping it, CCEP/HSX/XPP/BUR all fall out of the calendar."""
    assert _resolve_symbol("Coca-Cola Europacific Partners (DI)", INDEX)[0] == "CCEP.L"


def test_resolves_ampersand_spelled_out():
    assert _resolve_symbol("F&C Investment Trust", INDEX)[0] == "FCIT.L"


def test_unknown_name_resolves_to_nothing_rather_than_a_guess():
    """Fuzzy matching was tried and rejected — it confidently paired Tekcapital
    with CAPD.L and DSW Capital with SFOR.L. A wrong logo is worse than none."""
    assert _resolve_symbol("Tekcapital", INDEX) == (None, None)
    assert _resolve_symbol("Fragrant Prosperity Holdings Limited (DI)", INDEX) == (None, None)


def test_diary_key_strips_bond_and_gdr_decoration():
    assert _diary_key("Amaroq Ltd. Npv (DI)") == "AMAROQ"
    assert _diary_key("Atalaya Mining Copper, S.A. (CDI)") == "ATALAYA MINING COPPER"


# ── week arithmetic ───────────────────────────────────────────────────────────
#
# The displayed week turns over on SATURDAY: Mon-Fri you see the week you are in,
# and from Saturday you see the week ahead.


@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 8, 3), date(2026, 8, 3)),    # Monday    -> this week
        (date(2026, 8, 5), date(2026, 8, 3)),    # Wednesday -> this week
        (date(2026, 8, 7), date(2026, 8, 3)),    # Friday    -> still this week
        (date(2026, 8, 8), date(2026, 8, 10)),   # SATURDAY  -> rolls to next week
        (date(2026, 8, 9), date(2026, 8, 10)),   # Sunday    -> next week
        (date(2026, 8, 10), date(2026, 8, 10)),  # Monday    -> that same week
    ],
)
def test_current_week_start_rolls_over_on_saturday(today, expected):
    assert current_week_start(today) == expected


def test_current_week_start_always_returns_a_monday():
    for offset in range(28):
        d = date(2026, 8, 1)
        d = date.fromordinal(d.toordinal() + offset)
        assert current_week_start(d).weekday() == 0


def test_friday_and_saturday_differ_by_a_whole_week():
    """The rollover is the feature — guards against an off-by-one that would make
    the page flip on Sunday or Monday instead."""
    friday = current_week_start(date(2026, 8, 7))
    saturday = current_week_start(date(2026, 8, 8))
    assert (saturday - friday).days == 7


# ── FTSE 100 cross-check ──────────────────────────────────────────────────────
#
# The diary omits companies outright — it dropped Aviva's 14 Aug 2026 interims
# from every week between 20 Jul and 31 Aug — and a missing row is
# indistinguishable from a quiet day. These cover the merge rules; the network
# call itself (fetch_index_earnings_dates) is not unit-tested.

WEEK_10_AUG = date(2026, 8, 10)


def _diary_row(symbol, day, event_type="interims"):
    return {"event_date": date(2026, 8, day), "week_start": WEEK_10_AUG,
            "event_type": event_type, "source_name": symbol, "source_id": "1",
            "symbol": symbol, "company_name": None, "source": "diary"}


def test_cross_check_adds_a_company_the_diary_omitted():
    """The Aviva case, which is the whole reason this exists."""
    extra = cross_check_events({"AV.L": date(2026, 8, 14)}, WEEK_10_AUG, [])
    assert len(extra) == 1
    assert extra[0]["symbol"] == "AV.L"
    assert extra[0]["event_date"] == date(2026, 8, 14)
    assert extra[0]["source"] == "yfinance"
    # No interim/final distinction is available, so it must not invent one.
    assert extra[0]["event_type"] == "results"


def test_cross_check_defers_to_the_diary_on_the_same_day():
    extra = cross_check_events({"IHG.L": date(2026, 8, 11)}, WEEK_10_AUG,
                               [_diary_row("IHG.L", 11)])
    assert extra == []


def test_cross_check_defers_to_the_diary_on_a_DIFFERENT_day():
    """The rule is per-WEEK, not per-day. get_week only dedups within a single
    day, so a disagreeing yfinance date would put the same logo in two columns
    and read as two separate announcements. The diary is the better date source,
    so it wins outright."""
    extra = cross_check_events({"IHG.L": date(2026, 8, 13)}, WEEK_10_AUG,
                               [_diary_row("IHG.L", 11)])
    assert extra == []


def test_cross_check_ignores_dates_outside_the_week():
    dates = {"BNZL.L": date(2026, 9, 1), "MNG.L": date(2026, 8, 3)}
    assert cross_check_events(dates, WEEK_10_AUG, []) == []


def test_cross_check_drops_weekend_dates():
    """The grid has five columns; a Saturday date would be written and never
    rendered."""
    assert cross_check_events({"AV.L": date(2026, 8, 15)}, WEEK_10_AUG, []) == []


def test_cross_check_does_not_defer_to_an_unresolved_diary_row():
    """An unmatched diary row has symbol=None. It must not swallow the whole
    cross-check by matching every symbol."""
    unresolved = dict(_diary_row("AV.L", 14), symbol=None)
    extra = cross_check_events({"AV.L": date(2026, 8, 14)}, WEEK_10_AUG, [unresolved])
    assert [e["symbol"] for e in extra] == ["AV.L"]


def test_cross_check_rows_carry_the_fields_the_insert_needs():
    """refresh() feeds these straight into a named-parameter INSERT, so a missing
    key is a KeyError mid-transaction rather than a caught failure."""
    extra = cross_check_events({"AV.L": date(2026, 8, 14)}, WEEK_10_AUG, [])
    assert set(extra[0]) == {"event_date", "week_start", "event_type",
                             "source_name", "source_id", "symbol",
                             "company_name", "source"}
    assert extra[0]["week_start"] == WEEK_10_AUG


# ── suppressing already-reported yfinance dates ───────────────────────────────
#
# Yahoo does not only leave the field stale in the past (which `>= today` catches)
# — it drifts it FORWARDS once a company reports, and a forward date passes every
# check upstream. Both cases below are the real observed rows.


def test_drops_a_date_echoing_results_that_already_landed():
    """AV.L reported interims 14 Aug 2026; Yahoo then said 17 Aug and the Sunday
    cron put Aviva on the calendar a second time."""
    kept = drop_reported_dates({"AV.L": date(2026, 8, 17)},
                               {"AV.L": date(2026, 8, 14)})
    assert kept == {}


def test_drops_an_echo_weeks_after_the_event():
    """IGG.L reported 30 Jul 2026; Yahoo drifted to 19 Aug, 20 days later."""
    kept = drop_reported_dates({"IGG.L": date(2026, 8, 19)},
                               {"IGG.L": date(2026, 7, 30)})
    assert kept == {}


def test_keeps_a_genuine_next_cycle():
    """A quarterly reporter's next date is ~90 days out and must survive."""
    kept = drop_reported_dates({"SHEL.L": date(2026, 10, 29)},
                               {"SHEL.L": date(2026, 7, 30)})
    assert kept == {"SHEL.L": date(2026, 10, 29)}


def test_keeps_a_symbol_with_no_recent_results_rns():
    """`rns_announcements` is a filtered feed, so an absent report must mean no
    suppression — the filter has to fail OPEN or it silently empties the page."""
    assert drop_reported_dates({"PRU.L": date(2026, 8, 27)}, {}) == {
        "PRU.L": date(2026, 8, 27)}


def test_keeps_a_date_before_the_report():
    """Only a date at or after the announcement is an echo of it. A negative gap
    means the report is the NEXT event, not the one being repeated."""
    kept = drop_reported_dates({"XYZ.L": date(2026, 8, 3)},
                               {"XYZ.L": date(2026, 8, 20)})
    assert kept == {"XYZ.L": date(2026, 8, 3)}


def test_window_boundary_is_inclusive():
    kept = drop_reported_dates({"A.L": date(2026, 8, 31), "B.L": date(2026, 9, 1)},
                               {"A.L": date(2026, 8, 1), "B.L": date(2026, 8, 1)},
                               window_days=30)
    assert set(kept) == {"B.L"}


# ── outage guard ──────────────────────────────────────────────────────────────
#
# When Digital Look went dark it answered every URL with a 200 that parsed to
# zero events. refresh() rewrites DELETE-then-INSERT, so it wiped four weeks of
# good rows and left the page blank; the run did exit 1, but only after the
# delete. Two independent defences now exist and both are pinned here: _fetch_week
# raises DiaryUnavailable on a tableless page, AND a week is never destroyed by a
# scrape that brought nothing back.

# A table that renders but carries no results sections — a genuinely quiet week,
# or a source that has purged one. Parses to zero events WITHOUT raising, so it
# exercises the second defence rather than the first.
EMPTY_WEEK_HTML = ('<table class="eventdiaryBg"><tbody>'
                   + _section("AGMs", [("X", "Some AGM Company")], [], [], [], [])
                   + "</tbody></table>")


class _FakeCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(sql.strip().split()[0].upper())


class _FakeConn:
    def __init__(self, log):
        self.log = log
        self.autocommit = True

    def cursor(self):
        return _FakeCursor(self.log)

    def commit(self):
        self.log.append("COMMIT")


@pytest.fixture
def refresh_env(monkeypatch):
    """Stub every DB touchpoint in refresh() and hand back the statement log.

    `stored` is the diary row count refresh() will believe the week already
    holds — the single input the guard turns on.
    """
    import contextlib

    import results_calendar as rc

    log = []

    def install(stored, html=EMPTY_WEEK_HTML, raises=None):
        def fake_query(sql, params=None):
            if "results_calendar" in sql:
                return ([{"week_start": WEEK_10_AUG, "c": stored}] if stored else [])
            return [{"symbol": "DGE.L", "name": "Diageo plc"}]

        def fake_fetch(week, timeout=30, today=None):
            if raises:
                raise raises
            return html

        @contextlib.contextmanager
        def fake_connection():
            yield _FakeConn(log)

        monkeypatch.setattr(rc, "query", fake_query)
        monkeypatch.setattr(rc, "_fetch_week", fake_fetch)
        monkeypatch.setattr(rc, "connection", fake_connection)
        return log

    return install


def _refresh_one_week():
    import results_calendar as rc
    return rc.refresh(weeks_ahead=0, today=WEEK_10_AUG, yf_dates={})


def test_empty_scrape_leaves_a_populated_week_untouched(refresh_env):
    log = refresh_env(stored=56)
    result = _refresh_one_week()
    assert "DELETE" not in log
    assert result["skipped"] == [WEEK_10_AUG.isoformat()]
    assert result["weeks"][0]["skipped"] == "empty_parse"


def test_a_skipped_week_still_reports_empty_so_the_cron_exits_nonzero(refresh_env):
    """Frozen is better than blank, but it is not healthy — it must keep paging."""
    refresh_env(stored=56)
    assert _refresh_one_week()["status"] == "empty"


def test_empty_scrape_still_rewrites_a_week_holding_no_diary_rows(refresh_env):
    """A genuinely quiet week, and how a new week enters the window, are both
    indistinguishable from this — so the guard must not fire on them."""
    log = refresh_env(stored=0)
    result = _refresh_one_week()
    assert "DELETE" in log
    assert result["skipped"] == []


def test_a_failed_fetch_never_rewrites_the_week(refresh_env):
    """A week we could not read is a week we know nothing about."""
    log = refresh_env(stored=0, raises=OSError("connection reset"))
    result = _refresh_one_week()
    assert "DELETE" not in log
    assert result["weeks"][0]["skipped"] == "fetch_failed"


def test_an_unavailable_diary_protects_even_a_week_with_nothing_stored(refresh_env):
    """The gap the empty-parse guard alone cannot close. During the Digital Look
    outage the affected weeks had already been blanked, so `stored` was 0 and
    nothing stopped the next run writing them empty again — and a NEW week
    entering the window would hit the same hole every time. DiaryUnavailable is
    what makes the protection independent of what happens to be stored."""
    import results_calendar as rc

    log = refresh_env(stored=0, raises=rc.DiaryUnavailable("no diary table"))
    result = _refresh_one_week()
    assert "DELETE" not in log
    assert result["skipped"] == [WEEK_10_AUG.isoformat()]


def test_a_good_scrape_still_rewrites_the_week(refresh_env):
    log = refresh_env(stored=56, html=DIARY_HTML)
    result = _refresh_one_week()
    assert "DELETE" in log
    assert result["skipped"] == []
    assert result["status"] == "ok"


# ── source health ─────────────────────────────────────────────────────────────
#
# With the diary down the grid renders five "Nothing scheduled" columns, which
# reads as a quiet week rather than an outage. `stale` is what lets the page say
# which of the two it is.

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)   # a Monday
THIS_WEEK = date(2026, 8, 17)


def _status(week, hours_ago, now=NOW):
    last = None if hours_ago is None else now - timedelta(hours=hours_ago)
    return source_status(week, last, now=now)


def test_a_recent_scrape_is_not_stale():
    assert _status(THIS_WEEK, 6)["stale"] is False


def test_a_silent_diary_goes_stale():
    assert _status(THIS_WEEK, STALE_HOURS + 1)["stale"] is True


def test_one_missed_run_does_not_cry_wolf():
    """The cron is daily, so a 25-hour-old scrape is one hiccup, not an outage."""
    assert _status(THIS_WEEK, 25)["stale"] is False


def test_never_having_scraped_counts_as_stale():
    assert _status(THIS_WEEK, None)["stale"] is True


def test_a_past_week_is_never_stale():
    """Nothing refreshes a week once it has gone by, so flagging it would put a
    permanent warning on every archive view."""
    assert _status(date(2026, 8, 3), STALE_HOURS + 100)["stale"] is False


def test_a_future_week_inside_the_window_can_go_stale():
    assert _status(date(2026, 8, 31), STALE_HOURS + 1)["stale"] is True


def test_status_reports_the_age_the_banner_prints():
    st = _status(THIS_WEEK, 48)
    assert st["age_hours"] == 48.0
    assert st["diary_last_success"] == (NOW - timedelta(hours=48)).isoformat()


def test_status_is_json_safe_when_nothing_was_ever_scraped():
    """It goes straight out of a FastAPI response, so a datetime here is a 500."""
    st = _status(THIS_WEEK, None)
    assert st["diary_last_success"] is None
    assert st["age_hours"] is None
