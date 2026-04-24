import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rns import _classify, _parse_rows, _parse_timestamp


# ── _classify — tier A (always surface) ───────────────────────────────────────

def test_classify_profit_warning_is_tier_a():
    r = _classify("Profit Warning", "profit-warning")
    assert r["tier"] == "A"
    assert r["category"] == "profit_warning"
    assert r["score"] >= 60

def test_classify_trading_update_is_tier_a():
    r = _classify("Q3 Trading Update", "q3-trading-update")
    assert r["tier"] == "A"
    assert r["category"] == "trading_update"

def test_classify_final_results_is_tier_a():
    r = _classify("Final Results", "final-results")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_recommended_offer_is_tier_a():
    r = _classify("Recommended Cash Offer", "recommended-cash-offer")
    assert r["tier"] == "A"
    assert r["category"] == "recommended_offer"

def test_classify_rule_2_7_offer_is_tier_a():
    r = _classify("Rule 2.7 Announcement", "rule-2-7-announcement")
    assert r["tier"] == "A"
    assert r["category"] == "firm_offer"

def test_classify_strategic_review_is_tier_a():
    r = _classify("Strategic Review", "strategic-review")
    assert r["tier"] == "A"
    assert r["category"] == "strategic_review"


# ── _classify — tier B (noteworthy) ───────────────────────────────────────────

def test_classify_acquisition_is_tier_b():
    r = _classify("Proposed Acquisition of Acme Ltd",
                  "proposed-acquisition-of-acme-ltd")
    assert r["tier"] == "B"
    assert r["category"] == "acquisition"

def test_classify_placing_is_tier_b():
    r = _classify("Placing and Subscription", "placing-and-subscription")
    assert r["tier"] == "B"
    assert r["category"] == "capital_raise"

def test_classify_contract_award_is_tier_b():
    r = _classify("Contract Award", "contract-award")
    assert r["tier"] == "B"
    assert r["category"] == "contract_win"


# ── _classify — tier C (routine noise) ────────────────────────────────────────

def test_classify_tios_is_tier_c():
    r = _classify("Transaction in Own Shares", "transaction-in-own-shares")
    assert r["tier"] == "C"
    assert r["category"] == "buyback"
    assert r["score"] <= 20  # low base, no overlays

def test_classify_tvr_is_tier_c():
    r = _classify("Total Voting Rights", "total-voting-rights")
    assert r["tier"] == "C"
    assert r["category"] == "tvr"

def test_classify_holdings_is_tier_c():
    r = _classify("Holding(s) in Company", "holding(s)-in-company")
    assert r["tier"] == "C"
    assert r["category"] == "holdings"

def test_classify_form_8_is_tier_c():
    r = _classify("Form 8.3 - Target Co", "form-8.3")
    assert r["tier"] == "C"
    assert r["category"] == "disclosure_8"

def test_classify_pdmr_is_tier_c():
    r = _classify("Director/PDMR Shareholding", "director-pdmr-shareholding")
    assert r["tier"] == "C"
    assert r["category"] == "director_pdmr"


# ── _classify — calibration fixes from ADVFN 2026-04-17 feed ─────────────────

def test_classify_notice_of_interim_results_is_not_tier_a():
    # "Notice of Interim Results" is scheduling, not the results themselves.
    r = _classify("Notice of Interim Results", "notice-of-interim-results")
    assert r["tier"] == "C"
    assert r["category"] == "notice_of_results"

def test_classify_notice_of_results_is_tier_c():
    r = _classify("Notice of Results", "notice-of-results")
    assert r["tier"] == "C"
    assert r["category"] == "notice_of_results"

def test_classify_update_re_offer_is_tier_b():
    r = _classify("Update re LBR Offer", "update-re-lbr-offer")
    assert r["tier"] == "B"
    assert r["category"] == "ma_update"

def test_classify_change_in_appointment_of_directors_is_tier_b():
    r = _classify("Change in Appointment of Representative Directors",
                  "change-in-appointment-of-representative-directors")
    assert r["tier"] == "B"
    assert r["category"] == "board_change"

def test_classify_compulsory_redemption_is_tier_b():
    r = _classify("Compulsory Redemption", "compulsory-redemption")
    assert r["tier"] == "B"
    assert r["category"] == "fund_winddown"


# ── _classify — unknown slug falls back ───────────────────────────────────────

def test_classify_unknown_slug_defaults_to_tier_c():
    r = _classify("Some Random Announcement", "some-random-announcement")
    assert r["tier"] == "C"
    assert r["category"] is None


# ── _classify — keyword overlays ──────────────────────────────────────────────

def test_classify_negative_keyword_boosts_score():
    r = _classify("Trading Update - materially below expectations",
                  "trading-update")
    # Tier A base 60, plus 2 neg hits capped at 2 -> +30
    assert r["tier"] == "A"
    assert r["score"] >= 85
    assert any(h.startswith("neg:") for h in r["keyword_hits"])

def test_classify_positive_keyword_boosts_score():
    r = _classify("Trading Update - significantly ahead of expectations",
                  "trading-update")
    assert r["tier"] == "A"
    assert r["score"] >= 85
    assert any(h.startswith("pos:") for h in r["keyword_hits"])

def test_classify_catalytic_keyword_hit_on_tier_c():
    # Even a routine-looking slug gets flagged if the headline mentions a catalyst
    r = _classify("Response to Press Speculation - possible offer", "unknown-slug")
    # catalyst keyword doesn't change the tier (tier A only if slug/headline matches
    # one of the category patterns), but it does surface via keyword_hits
    assert any(h.startswith("cat:") for h in r["keyword_hits"])

def test_classify_score_clamped_to_100():
    # Stack every overlay to try to exceed 100
    r = _classify(
        "profit warning materially below expectations going concern covenant "
        "resigns investigation challenging",
        "profit-warning",
    )
    assert r["score"] <= 100

def test_classify_score_floor_at_zero():
    # Degenerate case — score can't go negative
    r = _classify("", "")
    assert r["score"] >= 0
    assert r["tier"] == "C"


# ── _parse_timestamp ──────────────────────────────────────────────────────────

def test_parse_timestamp_pm():
    t = _parse_timestamp("17 Apr 2026 06:20 PM")
    assert t is not None
    assert (t.year, t.month, t.day, t.hour, t.minute) == (2026, 4, 17, 18, 20)

def test_parse_timestamp_am():
    t = _parse_timestamp("17 Apr 2026 07:30 AM")
    assert t is not None
    assert (t.hour, t.minute) == (7, 30)

def test_parse_timestamp_returns_none_on_garbage():
    assert _parse_timestamp("not a date") is None
    assert _parse_timestamp("") is None


# ── _parse_rows — HTML fixture ────────────────────────────────────────────────

_FIXTURE_HTML = """
<html><body>
<div class="announcement-table">
<table><tbody>
<tr>
  <td>17 Apr 2026 06:20 PM</td>
  <td><div class="text-center"><a class="regulatory source-RNS"
      href="/source/RNS">RNS</a></div></td>
  <td><div class="align-items-center d-flex">
      <div><a href="/company/KIE">Kier Group (KIE)</a></div></div></td>
  <td><a class="announcement-link"
      href="https://www.investegate.co.uk/announcement/rns/kier-group--kie/transaction-in-own-shares/9526802"
      >Transaction in Own Shares</a></td>
</tr>
<tr>
  <td>17 Apr 2026 07:00 AM</td>
  <td><div class="text-center"><a class="regulatory source-RNS"
      href="/source/RNS">RNS</a></div></td>
  <td><div class="align-items-center d-flex">
      <div><a href="/company/ACME">Acme PLC (ACME)</a></div></div></td>
  <td><a class="announcement-link"
      href="https://www.investegate.co.uk/announcement/rns/acme-plc--acme/profit-warning/9999001"
      >Profit Warning</a></td>
</tr>
</tbody></table>
</div>
</body></html>
"""


def test_parse_rows_extracts_expected_fields():
    rows = _parse_rows(_FIXTURE_HTML)
    assert len(rows) == 2
    r = rows[0]
    assert r["id"] == 9526802
    assert r["wire"] == "RNS"
    assert r["ticker"] == "KIE"
    assert r["company_name"] == "Kier Group"
    assert r["headline"] == "Transaction in Own Shares"
    assert r["headline_slug"] == "transaction-in-own-shares"
    assert r["published_at"].year == 2026
    assert "kier-group--kie" in r["url"]


def test_parse_rows_handles_multiple_rows():
    rows = _parse_rows(_FIXTURE_HTML)
    ids = [r["id"] for r in rows]
    assert 9526802 in ids
    assert 9999001 in ids


def test_parse_rows_empty_html_returns_empty_list():
    assert _parse_rows("<html><body></body></html>") == []
