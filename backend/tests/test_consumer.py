from datetime import date
from unittest.mock import patch, MagicMock

import consumer


# ── _period_to_date ─────────────────────────────────────────────────────────────
def test_period_to_date_ons_quarterly():
    assert consumer._period_to_date("2026 Q1", "Q") == date(2026, 1, 1)
    assert consumer._period_to_date("2026 Q4", "Q") == date(2026, 10, 1)


def test_period_to_date_ons_monthly():
    assert consumer._period_to_date("2026 JUL", "M") == date(2026, 7, 1)


def test_period_to_date_boe_normalises_period_end_to_month_start():
    # BoE stamps the period END ("30 Jun 2026") — normalise back to the 1st.
    assert consumer._period_to_date("30 Jun 2026", "BOE") == date(2026, 6, 1)


def test_period_to_date_oecd():
    assert consumer._period_to_date("2026-06", "OECD") == date(2026, 6, 1)


# ── GfK regex — verified against both the July and August 2026 wording ─────────
def test_gfk_regex_matches_august_wording():
    text = "Overall Index Score was up three points to -14 in August"
    m = consumer._GFK_SCORE_RE.search(text)
    assert m is not None
    assert m.group(1) == "-14"
    assert m.group(2) == "August"


def test_gfk_regex_matches_july_wording():
    text = "Overall Index Score was up six points to -17 in July"
    m = consumer._GFK_SCORE_RE.search(text)
    assert m is not None
    assert m.group(1) == "-17"
    assert m.group(2) == "July"


def test_gfk_regex_keeps_the_sign_the_slug_drops():
    # The slug for this release said "14" (no minus) — the body text carries
    # the real, negative value, which is why the parser reads the body.
    text = "<p>Overall Index Score was up three points to -14 in August.</p>"
    stripped = consumer._strip_html(text)
    m = consumer._GFK_SCORE_RE.search(stripped)
    assert m.group(1) == "-14"


# ── OECD SDMX index-mapping ──────────────────────────────────────────────────────
def test_oecd_confidence_returns_chronological_order_despite_scrambled_index():
    # SDMX-JSON keys observations by index, and the index order is NOT
    # chronological — this fixture deliberately lists them out of order.
    fake_json = {
        "data": {
            "structures": [{
                "dimensions": {
                    "observation": [{
                        "values": [
                            {"id": "1990-01"},
                            {"id": "1990-02"},
                            {"id": "1990-03"},
                        ]
                    }]
                }
            }],
            "dataSets": [{
                "series": {
                    "0:0:0:0:0:0": {
                        "observations": {"2": [98.3], "0": [98.2], "1": [98.25]}
                    }
                }
            }],
        }
    }
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = fake_json
    with patch("consumer.requests.get", return_value=resp):
        rows = consumer._fetch_oecd_confidence()
    assert [p for p, d, v in rows] == ["1990-01", "1990-02", "1990-03"]
    assert [d for p, d, v in rows] == sorted(d for p, d, v in rows)


# ── BoE "Invalid series code" detection ──────────────────────────────────────────
def test_boe_fetch_returns_empty_on_invalid_series_code_html():
    # A bad code makes the endpoint 200 with an HTML "Error" page, not CSV.
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.text = "<html><title>Error</title>Invalid series code value supplied</html>"
    with patch("consumer.requests.get", return_value=resp):
        rows = consumer._fetch_boe_series("consumer_credit")
    assert rows == []


def test_boe_fetch_parses_valid_csv():
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.text = "DATE,LPMB4TC\n30 Jun 2026,9.1\n31 May 2026,8.7\n"
    with patch("consumer.requests.get", return_value=resp):
        rows = consumer._fetch_boe_series("consumer_credit")
    assert rows == [
        ("30 Jun 2026", date(2026, 6, 1), 9.1),
        ("31 May 2026", date(2026, 5, 1), 8.7),
    ]


# ── /api/consumer endpoint ────────────────────────────────────────────────────────
def test_consumer_endpoint_returns_200_with_cards_when_every_fetcher_fails(client):
    consumer._cache.clear()
    with patch("consumer._db_query", return_value=[]), \
         patch("consumer.requests.get", side_effect=Exception("network disabled in tests")):
        r = client.get("/api/consumer")
    assert r.status_code == 200
    data = r.json()
    assert data["cards"] == []
    assert data["history"] == {}
    consumer._cache.clear()
