"""Story-of-the-week pick — selection rule, floors and the snapshot window.

DB access is mocked (landing_story.query / .connection), so these run without a
database. The numbers are the real 22 July 2026 batch the storyboard was built
from: BOOT scored 85 negative and gapped -15.7%, GNC scored 80 positive and
gapped +7.3%, MUL scored 85 positive and went nowhere on 13,769 shares.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

import landing_story


def _cand(**kw):
    """A candidate row in the shape _CANDIDATE_SQL returns."""
    base = dict(
        id=1, symbol="BOOT.L", company_name="Henry Boot",
        headline="Trading Statement", url="http://x",
        published_at=datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
        category="trading_update", keyword_hits=["neg:2"],
        llm_score=85,
        llm_thesis="FY2026 profit significantly below market expectations.",
        llm_sentiment="negative",
        sector="Real Estate", ftse_index="FTSE SmallCap",
        market_cap=220_000_000,
        event_date=date(2026, 7, 22),
        event_open=Decimal("140.0"), event_close=Decimal("154.0"),
        event_volume=1_200_000,
        prev_close=Decimal("166.0"),
        gap_pct=Decimal("-15.66"),
    )
    base.update(kw)
    return base


_GNC = dict(
    id=2, symbol="GNC.L", company_name="Greencore",
    headline="Q3 Trading Update", llm_score=80,
    llm_thesis="Guidance upgraded, ahead of consensus.", llm_sentiment="positive",
    category="trading_update", keyword_hits=["pos:2"],
    event_open=Decimal("238.0"), event_close=Decimal("240.6"),
    prev_close=Decimal("221.8"), gap_pct=Decimal("7.30"),
    event_volume=900_000,
)


# ── selection ─────────────────────────────────────────────────────────────────
def test_picks_largest_agreeing_gap_not_highest_score():
    # Both qualify; BOOT's -15.7% beats GNC's +7.3% even though they tie/lose on
    # score ordering elsewhere. SQL already returns |gap| DESC, so the first
    # survivor wins.
    rows = [_cand(), _cand(**_GNC)]
    with patch.object(landing_story, "query", return_value=rows):
        pick = landing_story.select_candidate()
    assert pick["symbol"] == "BOOT.L"
    assert pick["direction"] == "negative"
    assert pick["gap_pct"] == -15.66


def test_rejects_sentiment_disagreement():
    # A "positive" score whose stock gapped DOWN is not proof of anything — the
    # block is a claim about the score's direction, so disagreement disqualifies.
    disagreeing = _cand(
        llm_sentiment="positive", llm_thesis="Upside beat, ahead of consensus.",
        keyword_hits=["pos:2"], category="trading_update",
    )
    with patch.object(landing_story, "query", return_value=[disagreeing, _cand(**_GNC)]):
        pick = landing_story.select_candidate()
    assert pick["symbol"] == "GNC.L"


def test_rejects_neutral_calls():
    neutral = _cand(llm_sentiment="neutral", llm_thesis="", keyword_hits=[],
                    category="trading_update")
    with patch.object(landing_story, "query", return_value=[neutral]):
        assert landing_story.select_candidate() is None


def test_rejects_thin_turnover():
    # The real Mulberry case: score 85, but 13,769 shares at 137p is ~£19k of
    # turnover. One trade is not the market repricing anything.
    mul = _cand(
        id=3, symbol="MUL.L", company_name="Mulberry", llm_score=85,
        event_volume=13_769, event_close=Decimal("140.0"),
        event_open=Decimal("150.0"), prev_close=Decimal("137.0"),
        gap_pct=Decimal("9.49"),
        llm_sentiment="positive", llm_thesis="Upside beat.", keyword_hits=["pos:2"],
    )
    with patch.object(landing_story, "query", return_value=[mul, _cand(**_GNC)]):
        pick = landing_story.select_candidate()
    assert pick["symbol"] == "GNC.L"


def test_rejects_sub_floor_market_cap():
    tiny = _cand(market_cap=20_000_000)
    with patch.object(landing_story, "query", return_value=[tiny, _cand(**_GNC)]):
        assert landing_story.select_candidate()["symbol"] == "GNC.L"
    # missing financials are treated as failing the floor, not passing it
    unknown = _cand(market_cap=None)
    with patch.object(landing_story, "query", return_value=[unknown]):
        assert landing_story.select_candidate() is None


def test_rejects_takeover_bids():
    # Mitie, 21 Jul 2026: recommended cash acquisition, scored 95, gapped +41%.
    # It would win the |gap| ranking outright — and prove nothing. A bid moving a
    # stock is not the ranker reading an announcement well, and bids would crowd
    # out the trading-statement calls the block exists to show.
    bid = _cand(
        id=4, symbol="MTO.L", company_name="Mitie Group", llm_score=95,
        category="acquisition", keyword_hits=["pos:3"],
        llm_sentiment="positive", llm_thesis="Recommended cash offer at a 44.7% premium.",
        event_open=Decimal("213.0"), event_close=Decimal("210.0"),
        prev_close=Decimal("151.0"), gap_pct=Decimal("41.06"),
        event_volume=55_000_000,
    )
    with patch.object(landing_story, "query", return_value=[bid, _cand(**_GNC)]):
        assert landing_story.select_candidate()["symbol"] == "GNC.L"
    # every M&A flavour the classifier emits is covered
    for cat in ("firm_offer", "possible_offer", "recommended_offer", "ma_update"):
        with patch.object(landing_story, "query", return_value=[_cand(**{**bid, "category": cat})]):
            assert landing_story.select_candidate() is None, cat


def test_rejects_limp_gap():
    limp = _cand(gap_pct=Decimal("-1.20"), event_open=Decimal("164.0"))
    with patch.object(landing_story, "query", return_value=[limp]):
        assert landing_story.select_candidate() is None


def test_thin_week_skips_without_writing():
    # Nothing qualifies → the previous row stays live and nothing is written.
    with patch.object(landing_story, "query", return_value=[]), \
         patch.object(landing_story, "connection") as conn:
        result = landing_story.pick_story()
    assert result["status"] == "skipped"
    conn.assert_not_called()  # no DB connection is even opened


# ── price convention (regression guard) ───────────────────────────────────────
def test_entry_is_the_announcement_day_open_not_the_next():
    """RNS drops ~07:00, before the 08:00 open, so the news is priced into THAT
    session. Entering the NEXT day starts the clock after the reaction and
    flattens the whole signal — the off-by-one found in the rns_score_perf work.
    Guarded structurally because the convention lives in SQL."""
    sql = landing_story._CANDIDATE_SQL
    # event bar: on or after the announcement date, earliest
    assert "p.date >= (r.published_at AT TIME ZONE 'Europe/London')::date" in sql
    # baseline: the last close BEFORE that bar
    assert "p.date < ev.date" in sql
    # showcase._next_open takes the day AFTER the story — never the helper here
    assert not hasattr(landing_story, "_next_open")


def test_only_pre_open_announcements_qualify():
    sql = landing_story._CANDIDATE_SQL
    assert "(r.published_at AT TIME ZONE 'Europe/London')::time < %s::time" in sql
    assert landing_story.LANDING_MAX_PUBLISH_TIME == "08:00"


def test_already_picked_stories_are_excluded():
    assert "NOT EXISTS (SELECT 1 FROM landing_story ls WHERE ls.rns_id = r.id)" \
        in landing_story._CANDIDATE_SQL


# ── snapshot window ───────────────────────────────────────────────────────────
def test_ohlc_window_puts_the_event_bar_at_event_idx():
    before = [  # DESC from SQL, event day first
        {"date": date(2026, 7, 22), "open": 140.0, "high": 163.7, "low": 133.5, "close": 154.0},
        {"date": date(2026, 7, 21), "open": 168.5, "high": 168.5, "low": 159.7, "close": 166.0},
        {"date": date(2026, 7, 20), "open": 163.0, "high": 169.0, "low": 161.0, "close": 169.0},
        {"date": date(2026, 7, 17), "open": 166.5, "high": 168.5, "low": 162.5, "close": 162.5},
    ]
    after = [
        {"date": date(2026, 7, 23), "open": 157.0, "high": 157.0, "low": 148.0, "close": 152.5},
        {"date": date(2026, 7, 24), "open": 151.0, "high": 154.0, "low": 149.0, "close": 151.0},
    ]
    with patch.object(landing_story, "query", side_effect=[before, after]):
        ohlc, event_idx = landing_story._ohlc_window("BOOT.L", date(2026, 7, 22))

    assert [b[0] for b in ohlc] == ["17", "20", "21", "22", "23", "24"]
    assert event_idx == 3
    assert ohlc[event_idx] == ["22", 140.0, 163.7, 133.5, 154.0]
    # the bar before the event is the gap baseline the chart shades from
    assert ohlc[event_idx - 1][4] == 166.0


def test_ohlc_window_survives_a_short_leading_history():
    """A recent listing has fewer than pad sessions before the event — the index
    must follow the rows actually returned, not the requested pad."""
    before = [
        {"date": date(2026, 7, 22), "open": 140.0, "high": 163.7, "low": 133.5, "close": 154.0},
        {"date": date(2026, 7, 21), "open": 168.5, "high": 168.5, "low": 159.7, "close": 166.0},
    ]
    with patch.object(landing_story, "query", side_effect=[before, []]):
        ohlc, event_idx = landing_story._ohlc_window("NEW.L", date(2026, 7, 22))
    assert event_idx == 1
    assert ohlc[event_idx][0] == "22"


# ── write + read ──────────────────────────────────────────────────────────────
def test_pick_story_snapshots_the_row():
    cur = MagicMock()
    cur.rowcount = 1
    conn = MagicMock()
    conn.cursor.return_value = cur
    ctx = MagicMock()
    ctx.__enter__.return_value = conn

    with patch.object(landing_story, "select_candidate",
                      return_value={**_cand(), "direction": "negative", "gap_pct": -15.66}), \
         patch.object(landing_story, "_ohlc_window",
                      return_value=([["22", 140.0, 163.7, 133.5, 154.0]], 0)), \
         patch.object(landing_story, "_wire_stats",
                      return_value={"total": 122, "survived": 31, "top": 4, "sample": []}), \
         patch.object(landing_story, "connection", return_value=ctx):
        result = landing_story.pick_story()

    assert result["status"] == "ok"
    assert result["symbol"] == "BOOT.L"
    assert result["gap_pct"] == -15.66
    assert result["wire"] == "122 -> 31 -> 4"
    params = cur.execute.call_args[0][1]
    assert params[0] == 1              # rns_id
    assert params[1] == "BOOT.L"
    assert "ON CONFLICT (rns_id) DO NOTHING" in cur.execute.call_args[0][0]


# ── the opening funnel ────────────────────────────────────────────────────────
def test_wire_stats_counts_the_morning_not_the_day():
    """The funnel is about the pre-open wire, so both the counts and the ticker
    sample must be bounded by the same 08:00 cutoff the pick itself uses."""
    counts = [{"total": 122, "survived": 31, "top": 4}]
    sample = [{"t": "07:00", "ticker": "RR.", "headline": "Transaction in Own Shares"},
              {"t": "07:00", "ticker": None, "headline": "Issue of Debt"}]
    with patch.object(landing_story, "query", side_effect=[counts, sample]) as q:
        wire = landing_story._wire_stats(datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc))

    assert (wire["total"], wire["survived"], wire["top"]) == (122, 31, 4)
    # a missing ticker becomes an empty string, never the literal "None"
    assert wire["sample"] == [["07:00", "RR.", "Transaction in Own Shares"],
                              ["07:00", "", "Issue of Debt"]]
    for call in q.call_args_list:
        assert "(published_at AT TIME ZONE 'Europe/London')::time < %s::time" in call[0][0]
        assert landing_story.LANDING_MAX_PUBLISH_TIME in call[0][1]


def test_wire_stats_survives_an_empty_morning():
    with patch.object(landing_story, "query", side_effect=[[], []]):
        wire = landing_story._wire_stats(datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc))
    assert wire == {"total": 0, "survived": 0, "top": 0, "sample": []}


def test_current_story_is_json_ready():
    row = {
        "symbol": "BOOT.L", "company_name": "Henry Boot",
        "headline": "Trading Statement", "url": "http://x",
        "published_at": datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
        "llm_score": 85, "llm_sentiment": "negative",
        "llm_thesis": "Profit below expectations.",
        "sector": "Real Estate", "ftse_index": "FTSE SmallCap",
        "prev_close": Decimal("166.0"), "event_open": Decimal("140.0"),
        "event_close": Decimal("154.0"), "gap_pct": Decimal("-15.66"),
        "ohlc": [["22", 140.0, 163.7, 133.5, 154.0]], "event_idx": 0,
        "wire_total": 122, "wire_survived": 31, "wire_top": 4,
        "wire_sample": [["07:00", "RR.", "Transaction in Own Shares"]],
        "picked_at": datetime(2026, 7, 27, 6, 20, tzinfo=timezone.utc),
    }
    with patch.object(landing_story, "query", return_value=[row]):
        out = landing_story.current_story()
    # Decimals become floats so the frontend gets numbers, not strings
    assert out["gap_pct"] == pytest.approx(-15.66)
    assert isinstance(out["prev_close"], float)
    assert out["sentiment"] == "negative"
    assert out["wire"] == {
        "total": 122, "survived": 31, "top": 4,
        "sample": [["07:00", "RR.", "Transaction in Own Shares"]],
    }

    # Rows snapshotted before the funnel existed carry no wire, and the page
    # then skips its opening scenes rather than rendering an empty funnel.
    legacy = {**row, "wire_total": None, "wire_survived": None,
              "wire_top": None, "wire_sample": None}
    with patch.object(landing_story, "query", return_value=[legacy]):
        assert landing_story.current_story()["wire"] is None

    with patch.object(landing_story, "query", return_value=[]):
        assert landing_story.current_story() is None


def test_endpoint_caches_hard(client):
    with patch.object(landing_story, "query", return_value=[]):
        r = client.get("/api/landing/story")
    assert r.status_code == 200
    assert r.json() is None
    # the row changes weekly — a long stale-while-revalidate is free here
    assert "s-maxage=3600" in r.headers["Cache-Control"]
