"""Unit tests for the pure HTML builders in email_rns_digest.py.

These exercise the render path with synthetic rows only — no DB, no Resend, no
network. They guard the digest that the user trades off: a render regression
(broken links, dropped rows, unescaped markup) would ship silently otherwise.
"""
from datetime import datetime, timezone

import email_rns_digest as d


def _row(**over) -> dict:
    """A fully-populated synthetic RNS row; override any field per test."""
    base = {
        "id": 1,
        "published_at": datetime(2026, 7, 8, 6, 30, tzinfo=timezone.utc),
        "ticker": "TSCO",
        "symbol": "TSCO.L",
        "company_name": "Tesco PLC",
        "headline": "Interim results",
        "url": "https://example.com/rns/1",
        "tier": "A",
        "category": "interim_results",
        "keyword_hits": [],
        "score": 10,
        "llm_score": 82,
        "llm_thesis": "Solid beat, guidance raised.",
        "llm_action": "research",
        "llm_risks": "Margin pressure",
        "llm_sentiment": "positive",
        "ftse_index": "FTSE 100",
        "market_cap": 20_000_000_000,
    }
    base.update(over)
    return base


# ── _cap_bucket ────────────────────────────────────────────────────────────────

def test_cap_bucket_maps_index_to_bucket():
    assert d._cap_bucket({"ftse_index": "FTSE 100"}) == "large"
    assert d._cap_bucket({"ftse_index": "FTSE 250"}) == "mid"
    assert d._cap_bucket({"ftse_index": "FTSE AIM 100"}) == "small"
    assert d._cap_bucket({"ftse_index": None}) == "small"      # unknown, no cap → small
    assert d._cap_bucket({}) == "small"


def test_cap_bucket_falls_back_to_market_cap_off_index():
    # Non-index names (LSE screen) bucket by cap: a £10B WISE is Large, not Small.
    assert d._cap_bucket({"ftse_index": "Main (non-index)", "market_cap": 9.7e9}) == "large"
    assert d._cap_bucket({"ftse_index": "Main (non-index)", "market_cap": 6e8}) == "mid"
    assert d._cap_bucket({"ftse_index": "AIM", "market_cap": 8e7}) == "small"
    assert d._cap_bucket({"ftse_index": None, "market_cap": 5e9}) == "large"
    # FTSE SmallCap / AIM 100 stay small regardless of cap (matches index tiers).
    assert d._cap_bucket({"ftse_index": "FTSE SmallCap", "market_cap": 5e9}) == "small"
    # junk cap values degrade to small, not crash
    assert d._cap_bucket({"ftse_index": "AIM", "market_cap": "junk"}) == "small"


# ── _format_mc ─────────────────────────────────────────────────────────────────

def test_format_mc_scales_and_handles_junk():
    assert d._format_mc(2_000_000_000) == "£2.0bn"
    assert d._format_mc(480_000_000) == "£480m"
    assert d._format_mc(52_000_000) == "£52m"
    assert d._format_mc(None) == ""
    assert d._format_mc("not-a-number") == ""


def test_format_mc_boundaries():
    # Exactly on the bn / m thresholds.
    assert d._format_mc(1_000_000_000) == "£1.0bn"
    assert d._format_mc(1_000_000) == "£1m"
    assert d._format_mc(999_000) == "£999k"


# ── _fmt_uk_time (BST vs GMT) ──────────────────────────────────────────────────

def test_fmt_uk_time_applies_summer_time():
    # July → BST (UTC+1): 06:30 UTC renders as 07:30.
    assert d._fmt_uk_time(datetime(2026, 7, 8, 6, 30, tzinfo=timezone.utc)) == "07:30"


def test_fmt_uk_time_winter_is_utc():
    # January → GMT (UTC+0): unchanged.
    assert d._fmt_uk_time(datetime(2026, 1, 8, 6, 30, tzinfo=timezone.utc)) == "06:30"


def test_fmt_uk_time_naive_assumed_utc():
    # A tz-naive timestamp is treated as UTC, not local.
    assert d._fmt_uk_time(datetime(2026, 1, 8, 6, 30)) == "06:30"


# ── _sentiment ─────────────────────────────────────────────────────────────────

def test_sentiment_category_override_wins():
    # profit_warning is a hard-negative category, even with a positive llm_sentiment.
    assert d._sentiment(_row(category="profit_warning", llm_sentiment="positive")) == "negative"
    assert d._sentiment(_row(category="firm_offer", llm_sentiment="negative")) == "positive"


def test_sentiment_uses_llm_field_then_thesis_then_hits():
    # No category override → trust the ranker's stored sentiment.
    assert d._sentiment(_row(category="trading_update", llm_sentiment="negative")) == "negative"
    # No llm_sentiment → scan the thesis.
    r = _row(category="trading_update", llm_sentiment=None,
             llm_thesis="Profit warning, guidance slashed below expectations.")
    assert d._sentiment(r) == "negative"
    # Nothing to go on → neutral.
    assert d._sentiment(_row(category="trading_update", llm_sentiment=None,
                             llm_thesis=None, keyword_hits=[])) == "neutral"


# ── _company_url ───────────────────────────────────────────────────────────────

def test_company_url_strips_dot_l_suffix():
    assert d._company_url({"symbol": "TSCO.L"}).endswith("/company/TSCO")


def test_company_url_unresolved_symbol_links_to_yahoo():
    # NULL symbol = ticker never resolved against company_metadata, i.e. the
    # company is outside our universe — its page would be empty, so link out.
    assert d._company_url({"ticker": "azn"}) == "https://finance.yahoo.com/quote/AZN.L"
    # Trailing dot in investegate tickers (e.g. JD.) is stripped before .L.
    assert d._company_url({"ticker": "JD.", "symbol": None}) == "https://finance.yahoo.com/quote/JD.L"


# ── _esc ───────────────────────────────────────────────────────────────────────

def test_esc_escapes_and_dashes_none():
    assert d._esc("a & b < c") == "a &amp; b &lt; c"
    assert d._esc(None) == "—"


# ── _render_row / _render_section ──────────────────────────────────────────────

def test_render_row_contains_company_headline_and_link():
    html = d._render_row(_row())
    assert "Tesco PLC" in html
    assert "Interim results" in html
    assert "https://example.com/rns/1" in html
    assert "/company/TSCO" in html            # company-page link
    assert "Interim Results" in html          # category label


def test_render_row_out_of_universe_links_to_yahoo():
    html = d._render_row(_row(symbol=None))
    assert "finance.yahoo.com/quote/TSCO.L" in html
    assert "/company/TSCO" not in html


def test_render_row_escapes_hostile_markup_in_name():
    html = d._render_row(_row(company_name="A & B <script>", headline="H&M deal"))
    assert "&amp;" in html and "&lt;script&gt;" in html
    assert "<script>" not in html             # raw tag never leaks through


def test_render_section_empty_shows_no_items():
    html = d._render_section("large", [])
    assert "no items" in html


def test_render_section_lists_every_row():
    rows = [_row(id=1, company_name="Alpha PLC"), _row(id=2, company_name="Beta PLC")]
    html = d._render_section("mid", rows)
    assert "Alpha PLC" in html and "Beta PLC" in html
    assert "2 items" in html                  # count in the heading bar


# ── _render_html (whole document) ──────────────────────────────────────────────

def test_render_html_empty_variant():
    html = d._render_html([], total_all=0)
    assert html.startswith("<!doctype html>")
    assert "No significant items today." in html


def test_render_html_full_document():
    rows = [
        _row(id=1, ticker="AZN", symbol="AZN.L", company_name="AstraZeneca PLC",
             ftse_index="FTSE 100"),
        _row(id=2, ticker="XYZ", symbol="XYZ.L", company_name="Small Co PLC",
             ftse_index="FTSE AIM 100", market_cap=40_000_000),
    ]
    html = d._render_html(rows, total_all=17)
    assert "AstraZeneca PLC" in html
    assert "Small Co PLC" in html
    assert "AI-ranked: <b>2/17</b>" in html   # ranked/total header stat
    assert "2 items" in html                  # section count
    # Every row's canonical company link is present.
    assert "/company/AZN" in html and "/company/XYZ" in html


# ── _render_text (plain-text alternative) ──────────────────────────────────────

def test_render_text_contains_ticker_headline_and_unsub_url():
    text = d._render_text([_row()], total_all=1,
                          unsub_url="https://x/api/unsubscribe?email=a%40b.com&t=abc",
                          manage_url="https://x/subscribe")
    assert "TSCO" in text
    assert "Interim results" in text
    assert "https://x/api/unsubscribe?email=a%40b.com&t=abc" in text
    assert "https://x/subscribe" in text
    assert "<" not in text and ">" not in text


def test_render_text_empty_variant():
    text = d._render_text([], total_all=0)
    assert "No significant items today." in text


def test_render_text_reports_items_below_the_cutoff():
    text = d._render_text([_row()], total_all=5)
    assert "4 more below the cutoff" in text


def test_render_text_omits_cutoff_line_when_nothing_is_hidden():
    text = d._render_text([_row()], total_all=1)
    assert "more below the cutoff" not in text


# ── _send_one (text part reaches send_email) ────────────────────────────────────

def test_send_one_passes_non_empty_text_kwarg(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.alphamoveai.co.uk")
    import emailer
    captured = {}
    monkeypatch.setattr(emailer, "send_email",
                        lambda **kw: captured.update(kw) or "msg-1")

    ok = d._send_one("Alpha <digest@alphamoveai.co.uk>", "Subject", [_row()],
                     "a@b.com", "https://app.alphamoveai.co.uk", total_all=1)

    assert ok is True
    assert captured["text"]
    assert "TSCO" in captured["text"]
    assert "Unsubscribe:" in captured["text"]
