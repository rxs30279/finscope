"""Shape assertions against the live production API.

One test per endpoint, checking structure not values (so a quiet news day or a
weekend can't turn these red). AZN.L is the stable ticker used for per-symbol
routes. Freshness/recency is deliberately NOT asserted here — that is
backend/healthcheck.py's responsibility.
"""
TICKER = "AZN.L"


def test_filters(get_json):
    d = get_json("/api/filters")
    assert isinstance(d, dict)
    assert isinstance(d.get("sectors"), list) and d["sectors"], "no sectors"
    assert "countries" in d


def test_screener(get_json):
    rows = get_json("/api/screener")
    assert isinstance(rows, list) and rows, "screener returned no rows"
    first = rows[0]
    for key in ("symbol", "name", "market_cap"):
        assert key in first, f"screener row missing {key!r}"


def test_search_finds_known_company(get_json):
    hits = get_json("/api/search", q="astrazeneca")
    assert isinstance(hits, list) and hits, "search returned nothing"
    assert any(h.get("symbol") == TICKER for h in hits), f"{TICKER} not in results"


def test_company(get_json):
    d = get_json("/api/company", symbol=TICKER)
    assert d.get("symbol") == TICKER
    assert d.get("name"), "company has no name"


def test_snapshot(get_json):
    d = get_json("/api/snapshot", symbol=TICKER)
    assert isinstance(d, dict) and d, "empty snapshot"


def test_valuation(get_json):
    d = get_json("/api/valuation", symbol=TICKER)
    assert d.get("symbol") == TICKER


def test_rns_latest_is_a_list(get_json):
    # May legitimately be empty on weekends / quiet days — assert only the shape.
    rows = get_json("/api/rns/latest")
    assert isinstance(rows, list)
    if rows:
        assert "published_at" in rows[0] or "headline" in rows[0]


def test_rns_ranked_is_a_list(get_json):
    rows = get_json("/api/rns/ranked")
    assert isinstance(rows, list)


def test_showcase_is_a_list(get_json):
    assert isinstance(get_json("/api/showcase"), list)


def test_market_sidebar(get_json):
    d = get_json("/api/market/sidebar")
    assert isinstance(d, dict)
    assert "benchmarks" in d and "as_of" in d


def test_fear_greed(get_json):
    d = get_json("/api/market/fear-greed")
    assert "score" in d and "sentiment" in d


def test_analysts_latest(get_json):
    rows = get_json("/api/analysts/latest")
    assert isinstance(rows, list) and rows, "no analyst rows"
    assert "name" in rows[0] and "consensus" in rows[0]


def test_dividends(get_json):
    d = get_json("/api/dividends", symbol=TICKER)
    assert d.get("symbol") == TICKER


def test_shorts(get_json):
    d = get_json("/api/shorts", symbol=TICKER)
    assert d.get("symbol") == TICKER


def test_research_posts(get_json):
    d = get_json("/api/research/posts")
    assert isinstance(d.get("posts"), list)


def test_subscribers_count(get_json):
    d = get_json("/api/subscribers/count")
    assert isinstance(d.get("count"), int) and d["count"] >= 0


def test_admin_route_rejects_without_token(client):
    # An admin-guarded POST must refuse an unauthenticated caller.
    r = client.post("/api/prices/refresh")
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"
