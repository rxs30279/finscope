import sys, os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from rns import (
    _classify,
    _parse_rows,
    _parse_timestamp,
    _extract_summary,
    _fetch_body,
    _truncate_body,
    _prune_old,
    _BODY_CAP,
    _BODY_HEAD,
    _BODY_TAIL,
    _BODY_STUB_CHARS,
)


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

def test_classify_award_of_contract_reversed_is_contract_win():
    # Gresham House GRID, 2026-06-29: "award" and "contract" split + reversed, and
    # the slug ends "-contract" so the "-contract-" pattern can't match.
    r = _classify("Ocker Hill provisional award of 25yr LDES contract",
                  "ocker-hill-provisional-award-of-25yr-ldes-contract")
    assert r["tier"] == "B"
    assert r["category"] == "contract_win"

def test_classify_wins_contract_is_contract_win():
    r = _classify("Acme wins £40m contract", "acme-wins-40m-contract")
    assert r["tier"] == "B"
    assert r["category"] == "contract_win"

def test_classify_preferred_bidder_is_contract_win():
    r = _classify("Selected as preferred bidder", "selected-as-preferred-bidder")
    assert r["tier"] == "B"
    assert r["category"] == "contract_win"

def test_classify_ltip_awards_not_swept_into_contract_win():
    # The contract regex requires a contract/tender word — an LTIP "award" must
    # stay equity_issue (Tier C), not get promoted.
    r = _classify("Issue of Awards under the Company's LTIP",
                  "issue-of-awards-under-the-company-s-ltip")
    assert r["tier"] == "C"
    assert r["category"] == "equity_issue"

def test_classify_product_launch_is_tier_b():
    # Plus500, 2026-06-29: new revenue line had no category at all → fell to Tier C.
    r = _classify("Plus500 launches sports event-based contracts",
                  "plus500-launches-sports-event-based-contracts")
    assert r["tier"] == "B"
    assert r["category"] == "product_launch"

def test_classify_launch_of_buyback_stays_buyback_tier_c():
    # Regression (sweep 2026-06-29): "Launch of … share buyback" was wrongly grabbed
    # by product_launch/Tier B. It must stay buyback/Tier C.
    r = _classify("Launch of £100 million share buyback programme",
                  "launch-of-100-million-share-buyback-programme")
    assert r["tier"] == "C"
    assert r["category"] == "buyback"

def test_classify_strategic_review_launch_keeps_tier_a():
    # A Tier A category sits above product_launch and must still win its label.
    r = _classify("Company launches strategic review", "launch-of-strategic-review")
    assert r["tier"] == "A"
    assert r["category"] == "strategic_review"

def test_classify_placing_launch_stays_capital_raise():
    r = _classify("Launch of Placing", "launch-of-placing")
    assert r["tier"] == "B"
    assert r["category"] == "capital_raise"


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


# ── _classify — full-year results shapes the enumerated slugs miss ────────────

def test_classify_fy_results_with_financial_year_ended_is_tier_a():
    # Foresight Group, 2026-06-29: standalone "FY results" + prose date — slipped
    # to Tier C before because the FY regex needed digits adjacent to "FY".
    r = _classify("FY results for the financial year ended 31/3/2026",
                  "fy-results-for-the-financial-year-ended-31-3-2026")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_bare_fy_results_is_tier_a():
    r = _classify("FY Results", "fy-results")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_fy_year_attached_results_still_tier_a():
    # Regression guard for the original "FY26 Results" shape.
    r = _classify("FY26 Results", "fy26-results")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_results_for_year_ended_is_tier_a():
    # AdvancedAdvT, 2026-06-29: "...year ended <date>" prose, no FY token.
    r = _classify("Financial Results for year ended 28 February 2026",
                  "financial-results-for-year-ended-28-february-2026")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_results_for_half_year_ended_is_interim():
    # Same "year ended" prose but half-year — must label interim, not final.
    r = _classify("Results for the half year ended 30 June 2026",
                  "results-for-the-half-year-ended-30-june-2026")
    assert r["tier"] == "A"
    assert r["category"] == "interim_results"

def test_classify_first_half_results_is_interim():
    # Unilever ULVR, 2026-07-28: "First Half Results" has no "half-year"/"half year"
    # token at all — bare "half" attached to "results" was dropped to Tier C and
    # never scored before the fallback grew a bare-half alternative.
    r = _classify("2026 First Half Results", "2026-first-half-results")
    assert r["tier"] == "A"
    assert r["category"] == "interim_results"

def test_classify_weeks_period_ended_is_final_results():
    # Games Workshop GAW, 2026-07-28: 52/53-week retail fiscal year — "year ended"
    # never appears in the headline, so the fallback missed it and it was dropped
    # to Tier C and never scored.
    r = _classify("Results for the 52 week period ended 31 May 2026",
                  "results-for-the-52-week-period-ended-31-may-2026")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_results_for_six_months_ended_is_interim():
    r = _classify("Results for the six months ended 30 June 2026",
                  "results-for-the-six-months-ended-30-june-2026")
    assert r["tier"] == "A"
    assert r["category"] == "interim_results"

def test_classify_half_year_financial_report_is_interim():
    # Ground Rents Income Fund, 2026-06-29: "half-year" + "report", no "results"/"-ly-".
    r = _classify("Half-year Financial Report", "half-year-financial-report")
    assert r["tier"] == "A"
    assert r["category"] == "interim_results"

def test_classify_interim_report_is_tier_a():
    r = _classify("Interim Report", "interim-report")
    assert r["tier"] == "A"
    assert r["category"] == "interim_results"

def test_classify_interim_dividend_not_promoted_to_interim_results():
    # The interim regex requires a results/report/statement word — a dividend must
    # stay routine (Tier C), not get swept up as interim results.
    r = _classify("Interim Dividend Declaration", "interim-dividend-declaration")
    assert r["tier"] == "C"
    assert r["category"] == "dividend_routine"

def test_classify_annual_financial_report_is_final_results():
    # Aberdeen City Council 54MP, 2026-06-26: AFR is the annual results doc, not
    # AGM admin — was being grabbed by agm_notice/Tier C.
    r = _classify("Annual Financial Report", "annual-financial-report")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_annual_report_and_accounts_is_final_results():
    r = _classify("Annual Report and Accounts 2026", "annual-report-and-accounts-2026")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_afr_with_notice_of_agm_stays_admin():
    # Bundled with the meeting → genuine AGM admin, stays Tier C.
    r = _classify("Annual Financial Report and Notice of AGM",
                  "annual-financial-report-and-notice-of-agm")
    assert r["tier"] == "C"
    assert r["category"] == "agm_notice"

def test_classify_publication_of_annual_report_stays_admin():
    r = _classify("Publication of Annual Report", "publication-of-annual-report")
    assert r["tier"] == "C"
    assert r["category"] == "agm_notice"

def test_classify_notice_of_fy_results_stays_tier_c():
    # "Notice of …" is scheduling — the notice guard must keep the FY fallback off.
    r = _classify("Notice of FY Results", "notice-of-fy-results")
    assert r["tier"] == "C"

def test_classify_satisfy_does_not_trigger_fy_results():
    # \bfy\b must not fire inside another word.
    r = _classify("Conditions satisfied - results of tender", "conditions-satisfied")
    assert r["category"] != "final_results"


# ── _classify — US-style "earnings" headlines (Ryanair, 2026-07-21) ───────────

def test_classify_q1_earnings_release_is_quarterly_tier_a():
    # Ryanair Holdings: "Q1 FY27 Ryanair Holdings plc Earnings" carries no
    # "results"/"trading" word, so it fell to Tier C and was never scored.
    r = _classify("Q1 FY27 Ryanair Holdings plc Earnings",
                  "q1-fy27-ryanair-holdings-plc-earnings")
    assert r["tier"] == "A"
    assert r["category"] == "quarterly"

def test_classify_bare_q1_earnings_is_quarterly_tier_a():
    r = _classify("Q1 FY27 Earnings", "q1-fy27-earnings")
    assert r["tier"] == "A"
    assert r["category"] == "quarterly"

def test_classify_full_year_earnings_is_final_results():
    r = _classify("Full Year Earnings", "full-year-earnings")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_half_year_earnings_is_interim():
    r = _classify("Half Year Earnings", "half-year-earnings")
    assert r["tier"] == "A"
    assert r["category"] == "interim_results"

def test_classify_earnings_release_is_tier_a():
    r = _classify("Earnings Release", "earnings-release")
    assert r["tier"] == "A"

def test_classify_notice_of_q1_earnings_stays_tier_c():
    # The notice guard must keep scheduling out of the earnings fallback.
    r = _classify("Notice of Q1 Earnings", "notice-of-q1-earnings")
    assert r["tier"] == "C"

def test_classify_earnings_growth_prose_not_promoted():
    # Bare "earnings" with no period marker or release word must not fire.
    r = _classify("Directorate Change and earnings comment",
                  "directorate-change-and-earnings-comment")
    assert r["category"] != "quarterly"
    assert r["category"] != "final_results"


# ── _classify — bundled "and Notice of Results" ───────────────────────────────
# Every headline/slug pair below is a real filing that landed in Tier C in the
# 180 days to 4 Aug 2026 — the ranker never saw any of them.

import pytest

@pytest.mark.parametrize("headline,slug", [
    ("Trading Update and Notice of Results",
     "trading-update-and-notice-of-results"),
    ("Half Year Trading Update and Notice of Results",
     "half-year-trading-update-and-notice-of-results"),
    ("Half-Year Trading Update and Notice of Results",
     "half-year-trading-update-and-notice-of-results"),
    ("Full Year Trading Update and Notice of Results",
     "full-year-trading-update-and-notice-of-results"),
    ("Pre-close Trading Update and Notice of Results",
     "pre-close-trading-update-and-notice-of-results"),
    ("Trading Update and Notice of Half-Year Results",
     "trading-update-and-notice-of-half-year-results"),
    # BIG's slug carries a trailing hyphen.
    ("Trading Update and Notice of Results",
     "trading-update-and-notice-of-results-"),
])
def test_classify_bundled_trading_update_beats_notice(headline, slug):
    r = _classify(headline, slug)
    assert r["tier"] == "A"
    assert r["category"] == "trading_update"

def test_classify_bare_notice_of_results_still_tier_c():
    # The guard must not disarm the notice category itself.
    r = _classify("Notice of Results", "notice-of-results")
    assert r["tier"] == "C"
    assert r["category"] == "notice_of_results"

def test_classify_notice_of_interim_results_still_tier_c():
    r = _classify("Notice of Interim Results", "notice-of-interim-results")
    assert r["tier"] == "C"
    assert r["category"] == "notice_of_results"


# ── _classify — digit-first period markers / bp's "SEA" ──────────────────────

def test_classify_bp_sea_quarterly_is_tier_a():
    # bp's actual Q2 results release, 4 Aug 2026 (−4.9% on the day) — scored
    # Tier C, so the ranker never saw an £85bn results day.
    r = _classify("2Q26 BP PLC SEA", "2q26-bp-plc-sea")
    assert r["tier"] == "A"
    assert r["category"] == "quarterly"

def test_classify_fy_sea_routes_to_final_results():
    # Same house style at the full-year end — routed by the period marker.
    r = _classify("FY26 BP PLC SEA", "fy26-bp-plc-sea")
    assert r["tier"] == "A"
    assert r["category"] == "final_results"

def test_classify_digit_first_quarter_results_is_tier_a():
    # 39IB, Tier C today: the enumerated quarterly slugs are all letter-first.
    r = _classify("2Q 2026 Results", "2q-2026-results-")
    assert r["tier"] == "A"
    assert r["category"] == "quarterly"

def test_classify_bare_sea_word_not_promoted():
    # KZG — "sea" is only a results word behind a period marker.
    r = _classify("Update on Sea Concession 2A Technical Report",
                  "update-on-sea-concession-2a-technical-report")
    assert r["tier"] == "C"

def test_classify_quarterly_presentation_stays_tier_c():
    # BVA — collateral around the release, not the release.
    r = _classify("HR- 2Q26 Earnings Presentation", "hr-2q26-earnings-presentation")
    assert r["tier"] == "C"

def test_classify_quarterly_conference_call_invitation_stays_tier_c():
    # 37QB — has a period marker AND "results", but it's an invitation.
    r = _classify("1H and 2Q 2026 Results Conference Call Invitation",
                  "1h-and-2q-2026-results-conference-call-invitation")
    assert r["tier"] == "C"

def test_classify_notice_of_digit_quarter_results_stays_tier_c():
    # BUR — the existing "notice" guard must still hold on the new branch.
    r = _classify("Notice of 2Q26 Results & Results Call Details",
                  "notice-of-2q26-results-results-call-details")
    assert r["tier"] == "C"

def test_classify_bp_trading_statement_unchanged():
    # bp files a trading statement weeks before the release; it was already
    # Tier A via the trading_update patterns and must stay there.
    r = _classify("2Q26 bp Trading Statement Part 1 of 1",
                  "2q26-bp-trading-statement-part-1-of-1")
    assert r["tier"] == "A"
    assert r["category"] == "trading_update"


# ── _classify — combination / merger phrasing of an offer ─────────────────────

def test_classify_recommended_combination_is_tier_a():
    # SEGRO, 4 Aug 2026 — £13bn FTSE 100 merger that scored Tier C.
    r = _classify("Recommended Combination", "recommended-combination")
    assert r["tier"] == "A"
    assert r["category"] == "recommended_offer"

def test_classify_possible_combination_is_tier_a():
    # SEGRO, 22 Jul 2026 — the opening statement of the same merger.
    r = _classify("Statement re Possible Combination",
                  "statement-re-possible-combination-")
    assert r["tier"] == "A"
    assert r["category"] == "possible_offer"

def test_classify_recommended_merger_is_tier_a():
    r = _classify("Recommended Merger of Acme and Beta",
                  "recommended-merger-of-acme-and-beta")
    assert r["tier"] == "A"
    assert r["category"] == "recommended_offer"

def test_classify_possible_merger_is_tier_a():
    r = _classify("Statement re Possible Merger", "statement-re-possible-merger")
    assert r["tier"] == "A"
    assert r["category"] == "possible_offer"

def test_classify_business_combination_prose_not_promoted():
    # "Combination" only counts behind possible/recommended — a routine mention
    # must not reach an offer category. (Directorate Change is board_change/B on
    # its own; the point here is that the bare word doesn't make it an offer.)
    r = _classify("Directorate Change following business combination",
                  "directorate-change-following-business-combination")
    assert r["category"] not in ("recommended_offer", "possible_offer")


# ── _classify — bare one-word filings ─────────────────────────────────────────

def test_classify_bare_disposal_is_tier_b():
    # Halma, 4 Aug 2026 (+5.5% on the day) and FirstGroup, 29 Jul 2026.
    r = _classify("Disposal", "disposal")
    assert r["tier"] == "B"
    assert r["category"] == "disposal"

def test_classify_bare_acquisition_is_tier_b():
    r = _classify("Acquisition", "acquisition")
    assert r["tier"] == "B"
    assert r["category"] == "acquisition"

def test_classify_bare_event_matches_on_equality_not_substring():
    # The bare-event lookup is equality-only: a headline that merely contains
    # the word, and that no existing disposal pattern covers, must not be
    # promoted. Keeps the new path from widening into a substring match.
    r = _classify("Disposal Group Update", "disposal-group-update")
    assert r["tier"] == "C"
    assert r["category"] is None

def test_classify_disposal_of_business_unchanged():
    # The existing "disposal of" pattern must still win on its own.
    r = _classify("Disposal of Momart International",
                  "disposal-of-momart-international")
    assert r["tier"] == "B"
    assert r["category"] == "disposal"


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
<tr>
  <td>17 Apr 2026 08:12 AM</td>
  <td><div class="text-center"><a class="regulatory source-FNW"
      href="/source/FNW">FNW</a></div></td>
  <td><div class="align-items-center d-flex">
      <div><a href="/company/FNEWS">FinanceWire News (FNEWS)</a></div></div></td>
  <td><a class="announcement-link"
      href="https://www.investegate.co.uk/announcement/fnw/financewire-news--fnews/startrader-launches-pre-ipo-trading-products-/9641654"
      >STARTRADER Launches Pre-IPO Trading Products</a></td>
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


def test_parse_rows_excludes_financewire_noise():
    # FNW ("FinanceWire News", ticker FNEWS) is a non-regulatory PR wire — dropped.
    rows = _parse_rows(_FIXTURE_HTML)
    assert all(r["wire"] != "FNW" for r in rows)
    assert all(r["ticker"] != "FNEWS" for r in rows)
    assert 9641654 not in [r["id"] for r in rows]


# ── _extract_summary ──────────────────────────────────────────────────────────

def test_extract_summary_returns_text():
    soup = BeautifulSoup(
        '<div id="collapseSummary"><p>Revenue up 10%.</p></div>', "html.parser"
    )
    assert _extract_summary(soup) == "Revenue up 10%."


def test_extract_summary_drops_disclaimer():
    soup = BeautifulSoup(
        '<div id="collapseSummary"><p>Revenue up 10%.</p>'
        '<p id="summary-disclaimer">AI-generated, may be inaccurate.</p></div>',
        "html.parser",
    )
    assert _extract_summary(soup) == "Revenue up 10%."


def test_extract_summary_missing_node_returns_none():
    soup = BeautifulSoup("<div>nothing here</div>", "html.parser")
    assert _extract_summary(soup) is None


# ── _fetch_body ────────────────────────────────────────────────────────────────

def test_fetch_body_rns_node():
    soup = BeautifulSoup(
        '<div class="fr-view-element"><p>Full RNS text.</p></div>', "html.parser"
    )
    assert _fetch_body(soup) == "Full RNS text."


def test_fetch_body_prn_node():
    soup = BeautifulSoup(
        '<div class="prn-announcement"><p>Full PRN text.</p></div>', "html.parser"
    )
    assert _fetch_body(soup) == "Full PRN text."


def test_fetch_body_missing_node_returns_none():
    # Neither container present — e.g. a page-layout change (selector rot).
    soup = BeautifulSoup('<div class="art-board">chrome only</div>', "html.parser")
    assert _fetch_body(soup) is None


def test_fetch_body_empty_node_returns_none():
    soup = BeautifulSoup('<div class="fr-view-element"></div>', "html.parser")
    assert _fetch_body(soup) is None


def test_fetch_body_prefers_rns_over_prn_when_both_present():
    soup = BeautifulSoup(
        '<div class="fr-view-element">RNS text</div>'
        '<div class="prn-announcement">PRN text</div>',
        "html.parser",
    )
    assert _fetch_body(soup) == "RNS text"


def test_fetch_body_falls_back_to_news_window_for_other_wires():
    # eqs/gnw/bzw/mfn each wrap their text in their own class, so neither wire
    # selector matches; the shared `news-window` parent is what carries them.
    soup = BeautifulSoup(
        '<div class="news-window">'
        '<div class="eqs-announcement"><p>Full EQS text.</p></div>'
        "</div>",
        "html.parser",
    )
    assert _fetch_body(soup) == "Full EQS text."


def test_fetch_body_prefers_wire_selector_over_news_window_superset():
    # On a real RNS page `news-window` contains `fr-view-element` plus the
    # registered-address header and the RNS footer. The precise selector must
    # win so those captures stay free of that chrome.
    soup = BeautifulSoup(
        '<div class="news-window">'
        "One Waterside Drive Reading"
        '<div class="fr-view-element">RNS text</div>'
        "This information is provided by RNS."
        "</div>",
        "html.parser",
    )
    assert _fetch_body(soup) == "RNS text"


def test_fetch_body_ignores_repeated_news_window():
    # The guard that keeps `.art-board`'s failure mode from recurring: if a
    # layout change ever makes this a repeated wrapper, return nothing rather
    # than storing page chrome as announcement text.
    soup = BeautifulSoup(
        '<div class="news-window">chrome</div>'
        '<div class="news-window">real body</div>',
        "html.parser",
    )
    assert _fetch_body(soup) is None


def test_fetch_body_empty_news_window_returns_none():
    # The `ukn` case: the container is present but carries no text at all
    # (PDF-only or JS-rendered). There is genuinely nothing to capture.
    soup = BeautifulSoup(
        '<div class="news-window"><div class="ukn-announcement"></div></div>',
        "html.parser",
    )
    assert _fetch_body(soup) is None


# ── _truncate_body ─────────────────────────────────────────────────────────────

def test_truncate_body_under_cap_kept_whole():
    text = "x" * 5000
    stored, chars, is_stub = _truncate_body(text)
    assert stored == text
    assert chars == 5000
    assert is_stub is False


def test_truncate_body_stub_below_threshold():
    text = "y" * (_BODY_STUB_CHARS - 1)
    stored, chars, is_stub = _truncate_body(text)
    assert is_stub is True
    assert stored == text  # still stored whole, just flagged
    assert chars == _BODY_STUB_CHARS - 1


def test_truncate_body_over_cap_head_and_tail():
    head = "H" * _BODY_HEAD
    middle = "M" * 50_000
    tail = "T" * _BODY_TAIL
    text = head + middle + tail
    stored, chars, is_stub = _truncate_body(text)
    assert chars == len(text)
    assert is_stub is False
    assert stored.startswith(head)
    assert stored.endswith(tail)
    assert "chars omitted" in stored
    assert len(stored) < len(text)
    # The omitted middle must never leak into what's stored/prompted.
    assert "M" * 100 not in stored


def test_truncate_body_at_exactly_cap_kept_whole():
    text = "z" * _BODY_CAP
    stored, chars, is_stub = _truncate_body(text)
    assert stored == text
    assert chars == _BODY_CAP


# ── _prune_old — body-nulling extension ────────────────────────────────────────

def test_prune_old_nulls_body_on_tier_ab_after_body_days():
    with patch("rns._get_pool") as mock_get_pool:
        pool = MagicMock()
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 3
        conn.cursor.return_value = cur
        pool.getconn.return_value = conn
        mock_get_pool.return_value = pool

        result = _prune_old(days=14, body_days=30)

    assert result["body_pruned"] == 3
    assert result["body_older_than_days"] == 30
    # Two statements: the Tier C hard-delete, then the body NULL-out.
    calls = cur.execute.call_args_list
    assert len(calls) == 2
    assert "DELETE FROM rns_announcements" in calls[0][0][0]
    second_sql = calls[1][0][0]
    assert "SET body = NULL" in second_sql
    assert "tier IN ('A', 'B')" in second_sql
    assert calls[1][0][1] == ("30",)
