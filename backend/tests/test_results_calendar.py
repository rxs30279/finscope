import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import pytest

from results_calendar import (
    _diary_key,
    _resolve_symbol,
    cross_check_events,
    current_week_start,
    parse_diary,
)


# A cut-down copy of the real diary markup (week of 3 Aug 2026), keeping every
# structural feature the parser depends on: a section header row, day cells keyed
# by "dN nN", an empty day rendered as a bare <td>, entity-escaped names, a
# trailing space inside the anchor, and a section we deliberately ignore.
DIARY_HTML = """
<tr><th headers="d1 d2 d3 d4 d5" id="n2" colspan="5"><a id="l2"></a><b>Finals</b></th></tr>
<tr><td headers="d1 n2" valign="top"><ul class="eventdiaryList">
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=11319&amp;username=&amp;ac=">Crimson Tide</a></li>
</ul></td><td headers="d2 n2" valign="top"><ul class="eventdiaryList">
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=10194&amp;username=&amp;ac=">Filtronic</a></li>
</ul></td><td>&nbsp;</td><td headers="d4 n2" valign="top"><ul class="eventdiaryList">
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=10033&amp;username=&amp;ac=">Diageo</a></li>
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=13078&amp;username=&amp;ac=">PZ Cussons</a></li>
</ul></td><td>&nbsp;</td></tr>
<tr><th headers="d1 d2 d3 d4 d5" id="n1" colspan="5"><a id="l1"></a><b>Interims</b></th></tr>
<tr><td headers="d1 n1" valign="top"><ul class="eventdiaryList">
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=10192&amp;username=&amp;ac=">F&amp;C Investment Trust</a></li>
</ul></td><td headers="d2 n1" valign="top"><ul class="eventdiaryList">
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=54782155&amp;username=&amp;ac=">Coca-Cola Europacific Partners (DI)</a></li>
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=54196834&amp;username=&amp;ac=">Convatec Group  </a></li>
</ul></td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
<tr><th headers="d1 d2 d3 d4 d5" id="n4" colspan="5"><a id="l4"></a><b>AGMs</b></th></tr>
<tr><td headers="d1 n4" valign="top"><ul class="eventdiaryList">
<li><a href="/cgi-bin/dlmedia/security.cgi?csi=99999&amp;username=&amp;ac=">Some AGM Company</a></li>
</ul></td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>
"""

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
    assert events["Diageo"] == "10033"


def test_parse_diary_on_junk_returns_nothing_rather_than_raising():
    assert parse_diary("<html><body>nope</body></html>", WEEK) == []


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
