"""Tests for the SEO-overhaul company endpoints: /api/company-extras (the
always-200 enrichment payload) and /api/companies (the A-Z / sector-hub feed),
plus the _sector_slug helper that must stay in sync with the frontend.

Hermetic: main.query is monkeypatched, so nothing touches the DB. The extras
endpoint fires several queries per request; the fake dispatches on the SQL so
one stub can drive the whole handler.
"""
import pytest

import main


# ── _sector_slug (MUST match sectorSlug() in frontend/src/lib/company.ts) ───────

def test_sector_slug_basic():
    assert main._sector_slug("Consumer Cyclical") == "consumer-cyclical"

def test_sector_slug_lowercases_and_hyphenates():
    assert main._sector_slug("Financial Services") == "financial-services"

def test_sector_slug_strips_punctuation():
    # "&" is dropped, the spaces around it each become a hyphen — identical to the
    # frontend's lower -> spaces-to-"-" -> strip-non-[a-z0-9-] order.
    assert main._sector_slug("Health & Care") == "health--care"

def test_sector_slug_keeps_digits():
    assert main._sector_slug("Sector 42") == "sector-42"


# ── /api/company-extras ─────────────────────────────────────────────────────────

def _extras_dispatcher(rns=None, analyst=None, valuation=None,
                       peer_names=None, sector_peers=None):
    """Build a fake `query` that returns per-table fixtures for the handler's
    several calls, keyed on distinctive SQL fragments."""
    def _q(sql, params=None):
        s = " ".join(sql.split())
        if "ANY(%s)" in s:                 # peer-name lookup
            return peer_names or []
        if "ttm_financials" in s:          # sector_peers JOIN
            return sector_peers or []
        if "rns_announcements" in s:
            return rns or []
        if "analyst_snapshots" in s:
            return analyst or []
        if "valuation_estimates" in s:
            return valuation or []
        raise AssertionError(f"unexpected query: {s[:80]}")
    return _q


def test_company_extras_full_payload(client, monkeypatch):
    monkeypatch.setattr(main, "query", _extras_dispatcher(
        rns=[{"id": 1, "headline": "Trading update", "category": "TS"}],
        analyst=[{"snapshot_date": "2026-07-18", "consensus": "Buy",
                  "total_analysts": 6, "buy_pct": 66.0}],
        valuation=[{"fair_value": 250.0, "peer_basis": "industry",
                    "peer_symbols": ["AZN.L", "GSK.L"]}],
        peer_names=[{"symbol": "AZN.L", "name": "AstraZeneca"},
                    {"symbol": "GSK.L", "name": "GSK"}],
        sector_peers=[{"symbol": "SHEL.L", "name": "Shell"}],
    ))
    r = client.get("/api/company-extras?symbol=BP.L")
    assert r.status_code == 200
    body = r.json()
    assert body["rns"][0]["headline"] == "Trading update"
    assert body["analyst"]["consensus"] == "Buy"
    assert body["valuation"]["fair_value"] == 250.0
    # peer_symbols get hydrated into {symbol, name} objects for the chips.
    assert body["valuation"]["peers"] == [
        {"symbol": "AZN.L", "name": "AstraZeneca"},
        {"symbol": "GSK.L", "name": "GSK"},
    ]
    assert body["sector_peers"][0]["symbol"] == "SHEL.L"


def test_company_extras_empty_is_200_and_cacheable(client, monkeypatch):
    # The uncovered-small-cap case: every source empty. This MUST be 200 (not 404)
    # and carry the cache header, so Next's data cache stores it — that's the whole
    # reason the endpoint exists.
    monkeypatch.setattr(main, "query", _extras_dispatcher())
    r = client.get("/api/company-extras?symbol=NOBODY.L")
    assert r.status_code == 200
    body = r.json()
    assert body == {"rns": [], "analyst": None, "valuation": None, "sector_peers": []}
    assert "s-maxage=900" in r.headers.get("cache-control", "")


def test_company_extras_insufficient_valuation_is_dropped(client, monkeypatch):
    # A row exists but peer_basis="insufficient" -> not a real estimate; suppress it
    # (and never even look up peer names).
    def _boom_names(*a, **k):
        raise AssertionError("peer-name lookup should not run for insufficient val")
    monkeypatch.setattr(main, "query", _extras_dispatcher(
        valuation=[{"fair_value": 100.0, "peer_basis": "insufficient",
                    "peer_symbols": ["X.L"]}],
    ))
    r = client.get("/api/company-extras?symbol=THIN.L")
    assert r.status_code == 200
    assert r.json()["valuation"] is None


def test_company_extras_valuation_without_peers(client, monkeypatch):
    # fair_value present, no peer_symbols -> valuation kept, peers = [] (no crash).
    monkeypatch.setattr(main, "query", _extras_dispatcher(
        valuation=[{"fair_value": 300.0, "peer_basis": "industry",
                    "peer_symbols": []}],
    ))
    r = client.get("/api/company-extras?symbol=SOLO.L")
    body = r.json()
    assert body["valuation"]["fair_value"] == 300.0
    assert body["valuation"]["peers"] == []


# ── /api/companies ──────────────────────────────────────────────────────────────

def test_companies_list_shape_and_cache(client, monkeypatch):
    rows = [
        {"symbol": "AZN.L", "name": "AstraZeneca", "sector": "Healthcare",
         "ftse_index": "FTSE 100", "currency": "GBp", "market_cap": 2.0e11},
        {"symbol": "BP.L", "name": "BP", "sector": "Energy",
         "ftse_index": "FTSE 100", "currency": "GBp", "market_cap": 8.0e10},
    ]
    monkeypatch.setattr(main, "query", lambda sql, params=None: rows)
    r = client.get("/api/companies")
    assert r.status_code == 200
    body = r.json()
    assert [c["symbol"] for c in body] == ["AZN.L", "BP.L"]
    assert body[0]["currency"] == "GBp"
    # Universe changes only on the quarterly index refresh — held a day at the edge.
    assert "s-maxage=86400" in r.headers.get("cache-control", "")
