import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import pandas as pd

import shorts
from shorts import (
    _attach_scores,
    _build_leaderboard,
    _index_universe,
    _last_working_day,
    _normalise_name,
    _parse_ansp_df,
    _resolve_symbol,
)


AS_OF = date(2026, 7, 17)


def _row(isin, d, pct, name="ACME PLC", symbol="ACME.L"):
    return {
        "isin": isin,
        "disclosure_date": d,
        "issuer_name": name,
        "ansp_pct": pct,
        "company_symbol": symbol,
    }


def test_ranked_by_pct_desc():
    rows = [
        _row("GB1", AS_OF, 2.5, name="LOW PLC"),
        _row("GB2", AS_OF, 8.1, name="HIGH PLC"),
    ]
    out = _build_leaderboard(rows, AS_OF)
    assert [r["name"] for r in out] == ["HIGH PLC", "LOW PLC"]
    assert out[0]["pct"] == 8.1


def test_issuer_without_latest_row_is_dropped():
    # Fell below the 0.2% threshold before as_of — no longer in the current file.
    rows = [
        _row("GB1", date(2026, 7, 15), 0.3, name="GONE PLC"),
        _row("GB2", AS_OF, 1.0, name="STILL PLC"),
    ]
    out = _build_leaderboard(rows, AS_OF)
    assert [r["name"] for r in out] == ["STILL PLC"]


def test_change_1m_null_while_series_young():
    rows = [
        _row("GB1", date(2026, 7, 13), 3.0),
        _row("GB1", AS_OF, 3.5),
    ]
    out = _build_leaderboard(rows, AS_OF)
    assert out[0]["change_1m"] is None
    assert out[0]["change_window"] == 0.5
    assert out[0]["window_start"] == "2026-07-13"


def test_change_1m_uses_closest_row_at_least_30d_back():
    rows = [
        _row("GB1", date(2026, 6, 1), 5.0),
        _row("GB1", date(2026, 6, 16), 4.0),   # closest row <= as_of - 30d
        _row("GB1", date(2026, 7, 10), 2.0),
        _row("GB1", AS_OF, 3.0),
    ]
    out = _build_leaderboard(rows, AS_OF)
    assert out[0]["change_1m"] == -1.0
    # window fallback still measured from the earliest row
    assert out[0]["change_window"] == -2.0


def test_history_serialised_in_date_order():
    rows = [
        _row("GB1", date(2026, 7, 14), 1.2),
        _row("GB1", AS_OF, 1.4),
    ]
    out = _build_leaderboard(rows, AS_OF)
    assert out[0]["history"] == [
        {"date": "2026-07-14", "pct": 1.2},
        {"date": "2026-07-17", "pct": 1.4},
    ]


def test_unresolved_symbol_kept_with_null_symbol():
    rows = [_row("IE1", AS_OF, 2.0, name="OUT OF UNIVERSE PLC", symbol=None)]
    out = _build_leaderboard(rows, AS_OF)
    assert out[0]["symbol"] is None
    assert out[0]["name"] == "OUT OF UNIVERSE PLC"


# ── _normalise_name ────────────────────────────────────────────────────────────

def test_normalise_strips_fca_long_form_suffixes():
    # The FCA writes out full legal names; company_metadata uses short forms.
    # Both must normalise to the same key (real misses found 2026-07-18).
    assert _normalise_name("PERSIMMON PUBLIC LIMITED COMPANY") == _normalise_name("Persimmon Plc")
    assert _normalise_name("THE UNITE GROUP PLC") == _normalise_name("Unite Group")
    assert _normalise_name("WEIR GROUP PLC(THE)") == _normalise_name("Weir Group PLC")
    assert _normalise_name("BRITISH LAND COMPANY PUBLIC LIMITED COMPANY(THE)") == _normalise_name(
        "British Land Company PLC"
    )


def test_normalise_spaced_and_dotted_plc_variants():
    # Real misses found 2026-07-18: legal names write PLC as "P L C"/"P.L.C.".
    assert _normalise_name("BELLWAY P L C") == _normalise_name("Bellway plc")
    assert _normalise_name("ROTORK P.L.C.") == _normalise_name("Rotork plc")
    assert _normalise_name("GREAT PORTLAND ESTATES P L C") == _normalise_name(
        "Great Portland Estates plc"
    )


def test_normalise_ampersand_and_word_and_are_interchangeable():
    assert _normalise_name("MARKS AND SPENCER GROUP P.L.C.") == _normalise_name(
        "Marks & Spencer Group plc"
    )
    assert _normalise_name("YOUNG & CO'S BREWERY PLC") == _normalise_name(
        "Young & Co.'s Brewery, P.L.C."
    )


# ── _index_universe / _resolve_symbol ──────────────────────────────────────────

_UNIVERSE = [
    {"symbol": "AUTO.L", "name": "Autotrader Group plc", "isin": None},
    {"symbol": "CCR.L", "name": "C&C Group plc", "isin": None},
    {"symbol": "BA.L", "name": "BAE Systems plc", "isin": "GB0002634946"},
]


def test_resolve_by_isin_fast_path():
    idx = _index_universe(_UNIVERSE)
    assert _resolve_symbol("GB0002634946", "SOMETHING ELSE ENTIRELY", *idx) == "BA.L"


def test_resolve_spacing_differences_via_tight_index():
    # FCA "AUTO TRADER" vs our "Autotrader"; FCA "C & C" vs our "C&C".
    idx = _index_universe(_UNIVERSE)
    assert _resolve_symbol("GB00BVYVFW23", "AUTO TRADER GROUP PLC", *idx) == "AUTO.L"
    assert _resolve_symbol("IE00B010DT83", "C & C GROUP PUBLIC LIMITED COMPANY", *idx) == "CCR.L"


def test_resolve_ambiguous_tight_key_never_mislinks():
    idx = _index_universe(
        [
            {"symbol": "AB.L", "name": "Alpha Beta plc", "isin": None},
            {"symbol": "ABX.L", "name": "Alph Abeta plc", "isin": None},
        ]
    )
    # Both collapse to ALPHABETA once spaces go -- must resolve to neither.
    assert _resolve_symbol("GB1", "ALPHA BETA PLC", *idx) == "AB.L"  # exact norm still wins
    assert _resolve_symbol("GB2", "ALPHABETA PLC", *idx) is None


def test_resolve_unknown_name_returns_none():
    idx = _index_universe(_UNIVERSE)
    assert _resolve_symbol("CH0126881561", "SWISS RE AG", *idx) is None


# ── _last_working_day ──────────────────────────────────────────────────────────

def test_last_working_day_weekend_maps_to_friday():
    assert _last_working_day(date(2026, 7, 18)) == date(2026, 7, 17)  # Sat -> Fri
    assert _last_working_day(date(2026, 7, 19)) == date(2026, 7, 17)  # Sun -> Fri


def test_last_working_day_weekday_unchanged():
    assert _last_working_day(date(2026, 7, 17)) == date(2026, 7, 17)  # Fri
    assert _last_working_day(date(2026, 7, 13)) == date(2026, 7, 13)  # Mon


# ── _parse_ansp_df ─────────────────────────────────────────────────────────────

def test_parse_current_file_well_formed():
    # Mirrors the real current CSV (13 Jul 2026 format).
    df = pd.DataFrame(
        {
            "Name of Company": ["BAE Systems Plc"],
            "International Securities Identification Number (ISIN)": ["GB0002634946"],
            "Aggregated net short position (%)": [0.40],
            "Position date (of latest position date notified)": ["25/06/2026"],
        }
    )
    rows = _parse_ansp_df(df, fallback_disclosure_date=date(2026, 7, 18))
    assert rows == [
        {
            "isin": "GB0002634946",
            "issuer_name": "BAE Systems Plc",
            "ansp_pct": 0.4,
            "position_date": date(2026, 6, 25),
            "disclosure_date": date(2026, 7, 18),
        }
    ]


def test_parse_historic_file_with_fca_misaligned_columns():
    # Mirrors the real historic CSV of 17 Jul 2026: headers say (pct, position
    # date, became-historical date) but the values are shifted one column —
    # the pct column holds position dates and the became-historical column
    # holds the pct. Killed the 17 Jul cron run before this fix.
    df = pd.DataFrame(
        {
            "Name of Company": ["4IMPRINT GROUP PLC", "ABERDEEN GROUP PLC"],
            "International Securities Identification Number (ISIN)": ["GB0006640972", "GB00BF8Q6K64"],
            "Aggregated net short position (%)": ["29/06/2026", "06/07/2026"],
            "Position date": ["14/07/2026", "15/07/2026"],
            "Date the aggregated net short position became historical": [1.05, 4.57],
        }
    )
    rows = _parse_ansp_df(df)
    assert rows[0]["ansp_pct"] == 1.05
    assert rows[0]["position_date"] == date(2026, 6, 29)
    # became-historical date keys the row (no fallback passed)
    assert rows[0]["disclosure_date"] == date(2026, 7, 14)
    assert rows[1]["ansp_pct"] == 4.57
    assert rows[1]["disclosure_date"] == date(2026, 7, 15)


def test_parse_historic_file_well_formed():
    # If/when the FCA fixes their file, the same headers must parse straight.
    df = pd.DataFrame(
        {
            "Name of Company": ["4IMPRINT GROUP PLC"],
            "International Securities Identification Number (ISIN)": ["GB0006640972"],
            "Aggregated net short position (%)": [1.05],
            "Position date": ["29/06/2026"],
            "Date the aggregated net short position became historical": ["14/07/2026"],
        }
    )
    rows = _parse_ansp_df(df)
    assert rows[0]["ansp_pct"] == 1.05
    assert rows[0]["position_date"] == date(2026, 6, 29)
    assert rows[0]["disclosure_date"] == date(2026, 7, 14)


def test_parse_skips_stray_unparseable_pct_row():
    df = pd.DataFrame(
        {
            "Name of Company": ["GOOD PLC", "BAD PLC", "ALSO GOOD PLC"],
            "International Securities Identification Number (ISIN)": ["GB1", "GB2", "GB3"],
            "Aggregated net short position (%)": [1.0, "n/a", 2.0],
            "Position date (of latest position date notified)": ["25/06/2026"] * 3,
        }
    )
    rows = _parse_ansp_df(df, fallback_disclosure_date=date(2026, 7, 18))
    assert [r["isin"] for r in rows] == ["GB1", "GB3"]


def test_attach_scores_resolved_vs_unresolved(monkeypatch):
    import main
    monkeypatch.setattr(main, "_scrub_screener_metrics", lambda rows: None)
    monkeypatch.setattr(main, "_attach_pegy", lambda rows: None)
    monkeypatch.setattr(main, "_quality_score", lambda r: 7)
    monkeypatch.setattr(main, "_value_score", lambda r: 5)
    monkeypatch.setattr(
        shorts, "query",
        lambda sql, params=None: [
            {"symbol": "ACME.L", "momentum_score": 8, "risk_score": 3, "ftse_index": "FTSE 250"}
        ],
    )
    rows = [{"symbol": "ACME.L"}, {"symbol": None}]
    _attach_scores(rows)
    assert rows[0]["momentum_score"] == 8
    assert rows[0]["quality_score"] == 7
    assert rows[0]["value_score"] == 5
    assert rows[0]["risk_score"] == 3
    assert rows[0]["ftse_index"] == "FTSE 250"
    # unresolved issuer: everything null, keys still present for the frontend
    assert rows[1] == {
        "symbol": None,
        "momentum_score": None, "quality_score": None,
        "value_score": None, "risk_score": None, "ftse_index": None,
    }


def test_attach_scores_no_resolved_symbols_skips_query(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("query should not run when nothing resolves")
    monkeypatch.setattr(shorts, "query", _boom)
    rows = [{"symbol": None}]
    _attach_scores(rows)
    assert rows[0]["momentum_score"] is None


def test_parse_empty_file_returns_no_rows():
    df = pd.DataFrame(
        columns=[
            "Name of Company",
            "International Securities Identification Number (ISIN)",
            "Aggregated net short position (%)",
            "Position date",
            "Date the aggregated net short position became historical",
        ]
    )
    assert _parse_ansp_df(df) == []
