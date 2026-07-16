"""Unit tests for refresh_lse_universe classification — the rules that decide
which LSE lines qualify for the wider universe. Pure functions only; the
LSE fetch and yfinance vet are exercised by the job's dry-run mode."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import refresh_lse_universe as l


def _line(tidm="ABC", name="ACME HOLDINGS PLC", cap=100e6, isin="GB00B0000000",
          currency="GBX", market="AIM", line_name="ORD 1P"):
    return {"tidm": tidm, "issuername": name, "marketcapitalization": cap,
            "isin": isin, "currency": currency, "_market": market,
            "name": line_name}


def test_classify_keeps_uk_sterling_equity():
    out = l.classify([_line()])
    assert "ABC.L" in out
    assert out["ABC.L"]["label"] == "AIM"
    assert out["ABC.L"]["cap"] == 100e6


def test_classify_labels_main_market():
    out = l.classify([_line(market="MAINMARKET")])
    assert out["ABC.L"]["label"] == "Main (non-index)"


def test_classify_drops_irish_and_foreign_isins():
    rows = [
        _line(tidm="FLTR", name="FLUTTER ENTERTAINMENT PLC", isin="IE00BWT6H894"),
        _line(tidm="SMSN", name="SAMSUNG ELECTRONICS", isin="US7960508882"),
        _line(tidm="CKI", name="CK INFRASTRUCTURE", isin="BMG2178K1009"),
        _line(tidm="JER", name="JERSEY CO", isin="JE00B0000000"),
    ]
    out = l.classify(rows)
    assert set(out) == {"JER.L"}  # only the Channel Islands ISIN survives


def test_classify_drops_non_sterling_lines():
    out = l.classify([_line(currency="USD"), _line(tidm="EUR1", name="X PLC", currency="EUR")])
    assert out == {}


def test_classify_drops_fund_like_names():
    rows = [
        _line(tidm="VCT1", name="OCTOPUS TITAN VCT PLC"),
        _line(tidm="TR1", name="BLACKROCK SMALLER CO TRUST PLC"),
        _line(tidm="FND", name="GRESHAM HOUSE ENERGY STORAGE FUND PLC"),
    ]
    assert l.classify(rows) == {}


def test_classify_collapses_multi_line_issuers_to_biggest():
    rows = [
        _line(tidm="YNGA", name="YOUNG & CO'S BREWERY PLC", cap=350e6),
        _line(tidm="YNGN", name="YOUNG & CO'S BREWERY PLC", cap=161e6),
    ]
    out = l.classify(rows)
    assert set(out) == {"YNGA.L"}


def test_classify_drops_pref_ccds_and_pibs_lines():
    # Real LSE line names, verified 2026-07-15: EQUITY-category lines of real
    # operating companies whose only tell is the instrument name.
    rows = [
        _line(tidm="SANB", name="SANTANDER UK PLC",
              line_name="8 5/8% NON-CUM STLG PRF #1"),
        _line(tidm="ELLA", name="ECCLESIASTICAL INSURANCE OFFICE PLC",
              line_name="8.625% NON CUM IRRD PRF #1"),
        _line(tidm="NBS", name="NATIONWIDE BUILDING SOCIETY",
              line_name="CORE CAPITAL DEFERRED SHS (MIN 250 CCDS)"),
        _line(tidm="NTEA", name="NORTHERN ELECTRIC PLC",
              line_name="8.061P(NET)CUM PRF SHS 1P"),
        _line(tidm="WISE", name="WISE GROUP PLC",
              line_name="CLS A ORD USD0.01 (DI)"),
    ]
    assert set(l.classify(rows)) == {"WISE.L"}


def test_classify_honours_skip_list():
    out = l.classify([_line(tidm="EVR", name="EVRAZ PLC", cap=1.2e9, market="MAINMARKET")])
    assert out == {}


def test_cap_hysteresis():
    assert l.c_keep({"cap": 45e6})       # kept: above the £40M exit floor
    assert not l.c_keep({"cap": 39e6})   # purged: below it
    assert l.CAP_IN > l.CAP_OUT          # entry must sit above exit


def test_total_pages_derived_when_missing():
    assert l._total_pages({"totalPages": 5}) == 5
    assert l._total_pages({"totalElements": 250}) == 3   # ceil(250/100)
    assert l._total_pages({"totalElements": 0}) == 1     # never truncate to 0
    assert l._total_pages({}) == 1


def _db_row(ftse_index="AIM", source="lse_screen", active=True):
    return {"ftse_index": ftse_index, "universe_source": source, "is_active": active}


def _cand(label="AIM", cap=100e6):
    return {"label": label, "cap": cap, "name": "X", "tidm": "X"}


def test_reconcile_new_respects_entry_floor():
    eligible = {"BIG.L": _cand(cap=60e6), "SML.L": _cand(cap=45e6)}
    new, relabels, deact, purge = l.reconcile(eligible, {}, {"BIG.L", "SML.L"})
    assert new == ["BIG.L"]              # 45M is above CAP_OUT but below CAP_IN
    assert relabels == deact == purge == []


def test_reconcile_never_touches_hl_or_manual_rows():
    db = {"HLX.L": _db_row(ftse_index="FTSE 250", source="hl_index"),
          "MAN.L": _db_row(source="manual")}
    new, relabels, deact, purge = l.reconcile({}, db, set())
    assert relabels == deact == purge == []


def test_reconcile_relabels_and_reactivates():
    db = {"LBL.L": _db_row(ftse_index="Main (non-index)"),
          "OFF.L": _db_row(active=False)}
    eligible = {"LBL.L": _cand(label="AIM"), "OFF.L": _cand(label="AIM")}
    new, relabels, deact, purge = l.reconcile(eligible, db, set(eligible))
    assert relabels == ["LBL.L", "OFF.L"]  # wrong label + inactive-but-eligible
    assert new == deact == purge == []


def test_reconcile_deactivates_listed_but_ineligible():
    # In the feed but excluded by the rules (e.g. re-domiciled to an IE ISIN):
    # retire with history, don't purge. Already-inactive rows are left alone.
    db = {"FLTR.L": _db_row(ftse_index="Main (non-index)"),
          "DONE.L": _db_row(active=False)}
    new, relabels, deact, purge = l.reconcile({}, db, {"FLTR.L", "DONE.L"})
    assert deact == ["FLTR.L"]
    assert purge == []


def test_reconcile_purges_gone_and_sub_floor_names():
    db = {"GONE.L": _db_row(), "TINY.L": _db_row()}
    eligible = {"TINY.L": _cand(cap=30e6)}   # below the £40M exit floor
    new, relabels, deact, purge = l.reconcile(eligible, db, {"TINY.L"})
    assert purge == ["GONE.L", "TINY.L"]     # absent from feed / shrank away
    assert deact == []
