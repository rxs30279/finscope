"""High Impact RNS showcase — sentiment, auto-flag, follow-ups, auto-archive and
the admin status/extend endpoints. DB access is mocked (showcase._q / ._exec and
main.query), so these run without a database."""
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import gates
import showcase


def _cand(**kw):
    base = dict(
        id=1, symbol="ABC.L", company_name="Abc plc", headline="FY results",
        url="http://x", published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        tier="A", category="final_results", score=60, keyword_hits=["pos:2"],
        summary="Strong year", llm_score=80, llm_confidence="high",
        llm_thesis="Strong upside beat", llm_risks="none", llm_action="research",
        sector="Industrials", industry="x", country="GB", ftse_index="FTSE 250",
        market_cap=200_000_000,
    )
    base.update(kw)
    return base


# ── _sentiment ────────────────────────────────────────────────────────────────
def test_sentiment_category_override():
    assert showcase._sentiment({"category": "profit_warning"}) == "negative"
    assert showcase._sentiment({"category": "firm_offer"}) == "positive"


def test_sentiment_thesis_scan():
    assert showcase._sentiment(
        {"category": "final_results", "llm_thesis": "shares upside beat opportunity"}
    ) == "positive"
    assert showcase._sentiment(
        {"category": "final_results", "llm_thesis": "guidance miss and decline concern"}
    ) == "negative"


def test_sentiment_keyword_counts():
    # "pos:2" outweighs "neg:1"
    assert showcase._sentiment({"keyword_hits": ["pos:2", "neg:1"]}) == "positive"
    assert showcase._sentiment({"keyword_hits": ["neg:3", "pos:1"]}) == "negative"
    assert showcase._sentiment({"keyword_hits": ["pos:1", "neg:1"]}) == "neutral"
    # empty-count markers ("pos:") still register as one hit each
    assert showcase._sentiment({"keyword_hits": ["pos:", "pos:", "neg:"]}) == "positive"


def test_sentiment_default_neutral():
    assert showcase._sentiment({}) == "neutral"


def test_sentiment_uk_results_phrasing():
    # Real DeepSeek theses that scored 75-85 but read neutral before the UK
    # phrasing ("ahead of expectations", "upgrad" stem, "record", "swing to
    # profit") was added to _LLM_POS (2y CMCX/KLR/TBTG backtest, 2026-07).
    theses = [
        # KLR prelims 2026-03-03
        "Record results ahead of expectations, net cash position for first "
        "time in 25 years, and £100m buyback materially upgrading the "
        "investment case.",
        # TBTG finals 2026-04-16
        "Final results show revenue and profit significantly ahead of "
        "expectations, with guidance for FY26 profit ahead of consensus.",
        # CMCX interims 2024-11-21
        "Strong interim results with 45% revenue growth, swing to profit, and "
        "210% dividend hike confirm strategic turnaround.",
        # KLR prelims 2025-03-04
        "Record underlying operating profit, margin expansion, and a new "
        "share buyback programme signal a materially improved case.",
    ]
    for thesis in theses:
        assert showcase._sentiment(
            {"category": "final_results", "llm_thesis": thesis}
        ) == "positive", thesis
    # negative language still outweighs a positive-sounding "record"
    assert showcase._sentiment(
        {"category": "final_results",
         "llm_thesis": "record impairment, guidance miss and margin decline"}
    ) == "negative"


def test_sentiment_prod_thesis_vocabulary():
    # Vocabulary validated against 438 stored prod theses (2026-07): the M&A
    # premium/offer cluster and the discounted-placing cluster both previously
    # read neutral.
    positives = [
        "Recommended cash acquisition offering a near-term cash exit at a "
        "significant premium.",  # at a premium / significant premium
        "Transformational deal is EPS accretive by >20% in 2028.",
        "Guidance above consensus and a 60% profit surge.",
        "Rejection of the bid signals potential for a higher offer, which "
        "could significantly re-rate the stock.",
        "Approval removes a key overhang, de-risking the disposal and "
        "unlocking value.",
    ]
    negatives = [
        "Deeply discounted placing signals severe financial distress, likely "
        "diluting existing shareholders.",  # dilut stem
        "Revenue guidance slashed; this is a solvency crisis for a £26m "
        "market cap company.",
        "Non-cash fair value loss drove the net loss for the period.",
        "Results confirm margin deterioration, a £7.3m goodwill impairment "
        "and mounting headwinds.",  # deteriorat stem
        "Analysts downgrading estimates on the earnings shortfall.",  # downgrad stem
    ]
    for thesis in positives:
        assert showcase._sentiment(
            {"category": "final_results", "llm_thesis": thesis}
        ) == "positive", thesis
    for thesis in negatives:
        assert showcase._sentiment(
            {"category": "final_results", "llm_thesis": thesis}
        ) == "negative", thesis


def test_vet_prompt_includes_annual_history():
    annual = [
        {"fiscal_year": 2024, "period_end_date": "2024-03-31",
         "revenue": 359_745_000, "operating_income": 82_944_000,
         "net_income": 46_886_000, "eps_diluted": 0.167},
    ]
    msgs = showcase._vet_messages(_cand(), annual)
    user = msgs[1]["content"]
    assert "FY ended 2024-03-31" in user
    assert "revenue £359.7m" in user
    assert "diluted EPS 16.7p" in user
    # base-grounding instructions live in the system prompt
    system = msgs[0]["content"]
    assert "NEVER fill gaps from your memory" in system
    # no history → explicit no-data line, not a silent omission
    empty = showcase._vet_messages(_cand(), [])[1]["content"]
    assert "no stored annual financials" in empty


def test_vet_prompt_includes_body_as_primary_source():
    msgs = showcase._vet_messages(_cand(body="Full announcement text here."), [])
    user = msgs[1]["content"]
    assert "Full announcement text here." in user
    assert "primary source" in user


def test_vet_prompt_body_missing_shows_not_available():
    user = showcase._vet_messages(_cand(body=None), [])[1]["content"]
    assert "(not available)" in user


def test_vet_prompt_stub_body_says_unavailable_external_document():
    user = showcase._vet_messages(
        _cand(body="short stub", body_is_stub=True), []
    )[1]["content"]
    assert "links to an external document" in user
    assert "short stub" not in user


def test_annual_history_query_shape():
    rows = [
        {"fiscal_year": 2023, "period_end_date": "2023-03-31", "revenue": 1,
         "operating_income": 1, "net_income": 1, "eps_diluted": 0.1},
        {"fiscal_year": 2024, "period_end_date": "2024-03-31", "revenue": 2,
         "operating_income": 2, "net_income": 2, "eps_diluted": 0.2},
    ]
    with patch.object(showcase, "_q", return_value=list(reversed(rows))) as q:
        out = showcase._annual_history("ABC.L", before="2025-01-01")
        # DESC from SQL, reversed to oldest-first for the prompt
        assert [r["fiscal_year"] for r in out] == [2023, 2024]
        assert q.call_args[0][1] == ("ABC.L", "2025-01-01", "2025-01-01", 5)
    # no symbol → no query, empty history
    assert showcase._annual_history(None) == []


def test_sentiment_prefers_stored_llm_sentiment():
    # The ranker's stored direction beats the thesis scan — here the thesis
    # reads positive ("upside beat") but the model said negative.
    assert showcase._sentiment(
        {"category": "final_results", "llm_sentiment": "negative",
         "llm_thesis": "upside beat opportunity"}
    ) == "negative"
    # A stored "neutral" is also authoritative (no fall-through to the scan).
    assert showcase._sentiment(
        {"category": "final_results", "llm_sentiment": "neutral",
         "llm_thesis": "upside beat opportunity"}
    ) == "neutral"
    # Category overrides still outrank the stored value…
    assert showcase._sentiment(
        {"category": "profit_warning", "llm_sentiment": "positive"}
    ) == "negative"
    # …and junk/legacy values fall through to the scan.
    assert showcase._sentiment(
        {"category": "final_results", "llm_sentiment": "bullish!!",
         "llm_thesis": "upside beat opportunity"}
    ) == "positive"


# ── flag_high_impact_candidates ───────────────────────────────────────────────
def test_flag_keeps_positive_and_stores_vet():
    vet = {"verdict": "include", "confidence": "high", "rationale": "clean",
           "model": "deepseek-chat", "low_base": {"period": "H1"}}
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=123.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation") as record_lb, \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates(hours=48)
    assert res == {"candidates": 1, "flagged": 1, "skipped_sentiment": 0,
                   "skipped_guidance": 0, "skipped_earnings_quality": 0,
                   "vetted": 1}
    params = ex.call_args[0][1]
    assert params[16] == "include"          # vet_verdict
    assert isinstance(params[20], datetime)  # vet_processed_at set
    # low_base gate is shadow-evaluated on the vet's own pool, separately from
    # the high_impact_rns INSERT above — must not touch showcase._exec/params.
    record_lb.assert_called_once()
    assert record_lb.call_args[0][0] == _cand()["id"]
    assert record_lb.call_args[0][1]["low_base"] == {"period": "H1"}


def test_flag_skips_non_positive():
    with patch.object(showcase, "_q", return_value=[_cand(category="profit_warning")]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate") as vet, \
         patch.object(showcase, "_exec") as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 0
    assert res["skipped_sentiment"] == 1
    vet.assert_not_called()
    ex.assert_not_called()


def test_flag_vet_failure_still_inserts_null_verdict():
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", side_effect=RuntimeError("api down")), \
         patch.object(gates, "record_low_base_evaluation") as record_lb, \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 1
    assert res["vetted"] == 0
    params = ex.call_args[0][1]
    assert params[16] is None   # vet_verdict NULL
    assert params[20] is None   # vet_processed_at NULL
    # A failed vet still gets a (n/a/not_vetted) low_base evaluation recorded.
    assert record_lb.call_args[0][1]["low_base"] is None


# ── guidance gate ─────────────────────────────────────────────────────────────
# The LUCE 2026-07-28 case: ">£40m" unchanged since May, against the £40.7m
# consensus printed in the same document. Flagged at 75/positive, fell 11.8%.
_LUCE_CHECK = {
    "metric": "Adjusted Operating Profit", "period": "FY2026",
    "guided_value": "> £40m", "consensus_value": "£40.7m",
    "vs_prior": "reiterated", "vs_consensus": "below",
}


def test_disqualifying_guidance_catches_reiterated_below_consensus():
    assert showcase._disqualifying_guidance(
        {"guidance_checks": [_LUCE_CHECK]}
    ) == _LUCE_CHECK


def test_disqualifying_guidance_scans_past_a_favourable_first_entry():
    # LUCE's FY2027 line is genuinely above consensus and appears alongside the
    # FY2026 one — letting the favourable entry short-circuit the scan would
    # reproduce exactly the failure this gate exists to stop.
    good = {"metric": "Adjusted Operating Profit", "period": "FY2027",
            "guided_value": "to exceed current market expectations",
            "consensus_value": "£42.3m",
            "vs_prior": "new", "vs_consensus": "above"}
    assert showcase._disqualifying_guidance(
        {"guidance_checks": [good, _LUCE_CHECK]}
    ) == _LUCE_CHECK


def test_disqualifying_guidance_allows_raised_without_consensus():
    # ULVR: restates a pre-existing 4-6% range while explicitly upgrading its
    # outlook, and prints no consensus. A genuine winner (+8.7% on the day) —
    # must not be gated out.
    assert showcase._disqualifying_guidance({"guidance_checks": [
        {"metric": "Underlying Sales Growth", "period": "FY2026",
         "guided_value": "4% to 6%", "consensus_value": None,
         "vs_prior": "raised", "vs_consensus": "no_consensus_stated"},
    ]}) is None


def test_disqualifying_guidance_also_catches_reiterated_in_line():
    # Over 7 LUCE runs the model split 4 "below" / 3 "in_line" on the same
    # figure (">£40m" is a floor; £40.7m is 1.75% above). Gating on "below"
    # alone would fire on barely half the runs, so an unraised guide that
    # merely matches a printed consensus counts too — it is no catalyst either.
    entry = {"vs_prior": "reiterated", "vs_consensus": "in_line"}
    assert showcase._disqualifying_guidance({"guidance_checks": [entry]}) == entry


def test_disqualifying_guidance_allows_reiterated_with_no_consensus():
    # The common case — no consensus footnote at all. This gate must only ever
    # fire on announcements that printed a consensus figure and failed it.
    assert showcase._disqualifying_guidance({"guidance_checks": [
        {"vs_prior": "reiterated", "vs_consensus": "no_consensus_stated"},
        {"vs_prior": "reiterated", "vs_consensus": "above"},
    ]}) is None


def test_disqualifying_guidance_fails_safe_on_unusable_input():
    # "unknown" is what _clean_guidance_checks assigns to labels it didn't
    # recognise — a parsing miss must not silently drop a row.
    for cand in (
        {},
        {"guidance_checks": None},
        {"guidance_checks": []},
        {"guidance_checks": "not a list"},
        {"guidance_checks": ["not a dict"]},
        {"guidance_checks": [{"vs_prior": "unknown", "vs_consensus": "below"}]},
    ):
        assert showcase._disqualifying_guidance(cand) is None


def test_gate_on_the_seven_observed_luce_samples():
    """LUCE 9689898 scored 7x at temperature 0.2 — the actual labels returned.

    vs_prior was "reiterated" every time; vs_consensus split 4 below / 3
    in_line. The gate must fire on all seven, because the score did not: it
    came back 75 six times and 85 once, never below the flag threshold.
    """
    observed = ["below", "below", "in_line", "in_line", "below", "below", "in_line"]
    for vs_consensus in observed:
        cand = {"guidance_checks": [
            {"metric": "Adjusted Operating Profit", "period": "FY2026",
             "guided_value": "> £40m", "consensus_value": "£40.7m",
             "vs_prior": "reiterated", "vs_consensus": vs_consensus},
            {"metric": "Adjusted Operating Profit", "period": "FY2027",
             "guided_value": "to exceed current market expectations",
             "consensus_value": "£42.3m",
             "vs_prior": "new", "vs_consensus": "above"},
        ]}
        assert showcase._disqualifying_guidance(cand) is not None


def test_gate_never_fires_on_the_seven_observed_ulvr_samples():
    """ULVR 9689925, same 7 runs — a genuine winner (+8.7% on the day).

    Its llm_score ranged 45-75, i.e. the score alone would have dropped it
    below the flag on 6 of 7 runs. The gate must leave it alone every time:
    every entry is either raised/new, or reiterated with no consensus printed.
    """
    observed = [
        [("raised", "no_consensus_stated"), ("new", "no_consensus_stated")],
        [("raised", "no_consensus_stated"), ("raised", "no_consensus_stated")],
        [("raised", "no_consensus_stated"), ("new", "no_consensus_stated")],
        [("reiterated", "no_consensus_stated"), ("new", "no_consensus_stated")],
        [("raised", "no_consensus_stated"), ("new", "no_consensus_stated")],
        [("raised", "no_consensus_stated"), ("raised", "no_consensus_stated")],
        [("raised", "no_consensus_stated"), ("reiterated", "no_consensus_stated")],
    ]
    for sample in observed:
        cand = {"guidance_checks": [
            {"metric": "Underlying Sales Growth", "period": "FY2026",
             "guided_value": "4% to 6%", "consensus_value": None,
             "vs_prior": p, "vs_consensus": c}
            for p, c in sample
        ]}
        assert showcase._disqualifying_guidance(cand) is None


def test_flag_skips_disqualifying_guidance_before_vetting():
    with patch.object(showcase, "_q",
                      return_value=[_cand(guidance_checks=[_LUCE_CHECK])]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate") as vet, \
         patch.object(showcase, "_exec") as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 0
    assert res["skipped_guidance"] == 1
    assert res["skipped_sentiment"] == 0
    vet.assert_not_called()   # no LLM spend on a row we've already ruled out
    ex.assert_not_called()


# ── printed-number parsers ────────────────────────────────────────────────────
# earnings_quality stores figures exactly as the announcement printed them, so
# these read them back. Every string below is a form actually observed in a
# stored body (plan Phase 2 / acceptance criterion 5). This is the piece most
# likely to be quietly wrong and the cheapest to test.

def test_parse_bps_reads_the_forms_banks_print():
    assert showcase._parse_bps("62bps") == 62
    assert showcase._parse_bps("52 bps") == 52
    assert showcase._parse_bps("44bp") == 44
    assert showcase._parse_bps("51 basis points") == 51
    assert showcase._parse_bps("0.5bps") == 0.5
    # The model sometimes drops the whole printed clause into `value`; the
    # leading figure is the current one, the parenthetical is the comparator.
    assert showcase._parse_bps("62bps (H125: 52bps)") == 62


def test_parse_bps_refuses_percentages_and_money():
    # "increased 38%" read as 3,800bps would fire the bank gate on an income
    # line's own comparator. Requiring the unit costs nothing — banks print the
    # loan loss rate in bps precisely because it is the normalised figure.
    for s in ("increased 38%", "38%", "£1.4bn", "c.£225m", "62", "", None, 62):
        assert showcase._parse_bps(s) is None, s


def test_parse_money_reads_the_forms_announcements_print():
    assert showcase._parse_money("£1.4bn") == 1.4e9
    assert showcase._parse_money("c.£225m") == 225e6
    assert showcase._parse_money(">£13.7bn") == 13.7e9
    assert showcase._parse_money("£0.2bn") == 0.2e9
    assert showcase._parse_money("£40.7m") == 40.7e6
    assert showcase._parse_money("$1.5 million") == 1.5e6
    assert showcase._parse_money("€2 billion") == 2e9
    assert showcase._parse_money("£1,400") == 1400
    assert showcase._parse_money("1.4bn") == 1.4e9
    # A currency-marked figure wins over a bare growth rate in the same string.
    assert showcase._parse_money("up 38% to £1.4bn") == 1.4e9


def test_parse_money_returns_none_rather_than_guessing():
    for s in ("increased 38%", "38%", "62bps", "significantly ahead",
              "", None, 1.4):
        assert showcase._parse_money(s) is None, s


# ── earnings-quality gate ─────────────────────────────────────────────────────
# BARC 2026-07-28: guidance genuinely raised (so the guidance gate above cannot
# fire), headline growth partly a c.£225m disposal gain, loan loss rate
# 52 -> 62bps. Fell 5.5% on the day; scored [55, 60, 65, 75, 80, 80, 80],
# positive 7/7, four runs clearing the flag threshold.
_BANK = {"sector": "Financial Services", "industry": "Banks - Diversified"}
_BARC_LLR = {
    "item": "Loan loss rate", "period": "H1 2026", "value": "62bps",
    "prior_value": "52bps", "kind": "cost_or_charge", "one_off_named": None,
}


def test_worsening_loss_rate_catches_the_barc_llr():
    assert showcase._worsening_loss_rate(
        {**_BANK, "earnings_quality": [_BARC_LLR]}
    ) == _BARC_LLR


def test_worsening_loss_rate_scans_past_earlier_entries():
    # The upgraded-income lines are enumerated first and are genuinely good
    # news; letting them short-circuit the scan reproduces the failure.
    entries = [
        {"item": "IB income", "period": "H1 2026", "value": "increased 20%",
         "prior_value": None, "kind": "income", "one_off_named": None},
        {"item": "USCB income", "period": "H1 2026", "value": "increased 38%",
         "prior_value": None, "kind": "income",
         "one_off_named": "c.£225m gain from the sale of the AA portfolio"},
        _BARC_LLR,
    ]
    assert showcase._worsening_loss_rate(
        {**_BANK, "earnings_quality": entries}
    ) == _BARC_LLR


def test_worsening_loss_rate_fires_on_the_quarter_as_well_as_the_half():
    # Enumeration is unstable — 2 to 7 entries across 7 BARC runs — so the
    # threshold sits below BOTH observed rises (H1 +10bps, Q2 +7bps) rather
    # than letting the outcome depend on which period the model enumerated.
    q2 = {"item": "Loan loss rate", "period": "Q2 2026", "value": "51bps",
          "prior_value": "44bps", "kind": "cost_or_charge"}
    assert showcase._worsening_loss_rate(
        {**_BANK, "earnings_quality": [q2]}
    ) == q2


def test_worsening_loss_rate_ignores_the_absolute_impairment_charge():
    # Any bank growing its loan book grows impairments; £1.1bn -> £1.4bn is
    # evidence of nothing on its own. The LLR is already normalised for book
    # size, which is why banks report it — that's the whole point of the rule.
    assert showcase._worsening_loss_rate({**_BANK, "earnings_quality": [
        {"item": "Credit impairment charges", "period": "H1 2026",
         "value": "£1.4bn", "prior_value": "£1.1bn", "kind": "cost_or_charge"},
    ]}) is None


def test_worsening_loss_rate_ignores_an_improving_or_flat_rate():
    for value, prior in (("52bps", "62bps"), ("62bps", "62bps"),
                         ("64bps", "62bps")):  # +2bps is below the threshold
        assert showcase._worsening_loss_rate({**_BANK, "earnings_quality": [
            {**_BARC_LLR, "value": value, "prior_value": prior},
        ]}) is None, (value, prior)


def test_worsening_loss_rate_is_bank_only():
    # The rule reads a bank's loan loss rate. Nothing else reports one, and the
    # control set is entirely non-banks — it must return None on every one.
    for row in (
        {"sector": "Consumer Defensive", "industry": "Household Products"},
        {"sector": "Industrials", "industry": "Specialty Industrial Machinery"},
        {"sector": "Financial Services", "industry": "Insurance - Life"},
        {"sector": "Financial Services", "industry": "Asset Management"},
        {"sector": None, "industry": None},   # out-of-universe, not a trust
    ):
        assert showcase._worsening_loss_rate(
            {**row, "earnings_quality": [_BARC_LLR]}
        ) is None, row


def test_worsening_loss_rate_fails_open_on_every_ambiguous_path():
    # Dropping a tradeable announcement is the high-severity error here, so an
    # entry the gate can't fully read is an entry it ignores.
    for entries in (
        None,
        [],
        "not a list",
        ["not a dict"],
        # "unclear" is what _clean_earnings_quality assigns to a kind it didn't
        # recognise — a parsing miss must never silently block a row.
        [{**_BARC_LLR, "kind": "unclear"}],
        [{**_BARC_LLR, "kind": "income"}],
        [{**_BARC_LLR, "period": None}],      # can't tell a half from a quarter
        [{**_BARC_LLR, "period": "  "}],
        [{**_BARC_LLR, "prior_value": None}],  # nothing to compare against
        [{**_BARC_LLR, "value": "materially higher"}],
        [{**_BARC_LLR, "value": "£1.4bn", "prior_value": "£1.1bn"}],
    ):
        assert showcase._worsening_loss_rate(
            {**_BANK, "earnings_quality": entries}
        ) is None, entries


def test_named_one_offs_reports_income_lines_only():
    # Surfaced, never gated: the one-off as a share of the growth isn't
    # computable — "c.£225m" against "increased 38%" is not a computation.
    uscb = {"item": "USCB income", "period": "H1 2026", "value": "increased 38%",
            "kind": "income",
            "one_off_named": "c.£225m gain from the sale of the AA portfolio"}
    entries = [
        uscb,
        {"item": "IB income", "kind": "income", "one_off_named": None},
        # A one-off CHARGE is recorded too (it flatters the trend) but it is
        # the charge gate's business, not this reporter's.
        {"item": "Litigation and conduct", "kind": "cost_or_charge",
         "one_off_named": "provision for the FCA motor finance redress scheme"},
    ]
    assert showcase._named_one_offs({"earnings_quality": entries}) == [uscb]
    for bad in (None, [], "not a list", ["not a dict"]):
        assert showcase._named_one_offs({"earnings_quality": bad}) == []


def test_flag_skips_worsening_loss_rate_before_vetting():
    cand = _cand(sector="Financial Services", industry="Banks - Diversified",
                 earnings_quality=[_BARC_LLR])
    with patch.object(showcase, "_q", return_value=[cand]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate") as vet, \
         patch.object(showcase, "_exec") as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 0
    assert res["skipped_earnings_quality"] == 1
    assert res["skipped_guidance"] == 0
    vet.assert_not_called()   # no LLM spend on a row we've already ruled out
    ex.assert_not_called()


def test_flag_still_flags_a_bank_with_a_clean_loss_rate():
    # The gate must not read "bank" as "block" — it fires on the rate move.
    cand = _cand(sector="Financial Services", industry="Banks - Diversified",
                 earnings_quality=[{**_BARC_LLR, "prior_value": "62bps"}])
    with patch.object(showcase, "_q", return_value=[cand]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=None), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1):
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 1
    assert res["skipped_earnings_quality"] == 0


# ── record_followups ──────────────────────────────────────────────────────────
def test_record_followups_excludes_story_and_tags_sentiment():
    active = [{"id": 10, "rns_id": 1, "symbol": "ABC.L",
               "published_at": datetime(2026, 6, 1, tzinfo=timezone.utc)}]
    newer = [{"id": 2, "headline": "CEO retires", "url": "u",
              "published_at": datetime(2026, 6, 5, tzinfo=timezone.utc),
              "tier": "A", "category": "board_change", "keyword_hits": ["neg:1"],
              "llm_score": 70, "llm_thesis": "leadership concern decline"}]
    seen = []

    def fake_q(sql, params=None):
        seen.append(params)
        return active if len(seen) == 1 else newer

    with patch.object(showcase, "_q", side_effect=fake_q), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.record_followups()

    assert res == {"active": 1, "inserted": 1}
    # The story's own rns_id (1) is passed so SQL can exclude it.
    assert seen[1] == ("ABC.L", active[0]["published_at"], 1)
    # Follow-up tagged negative (CEO exit) — the Luceco signal.
    assert ex.call_args[0][1][-1] == "negative"


# ── status endpoint ───────────────────────────────────────────────────────────
def test_status_happy(client):
    with patch("main.query", return_value=[{"id": 5}]):
        r = client.post("/api/showcase/5/status", json={"status": "approved"})
    assert r.status_code == 200
    assert r.json() == {"id": 5, "status": "approved"}


def test_status_not_found(client):
    with patch("main.query", return_value=[]):
        r = client.post("/api/showcase/9/status", json={"status": "rejected"})
    assert r.status_code == 404


def test_status_bad_value(client):
    r = client.post("/api/showcase/5/status", json={"status": "bogus"})
    assert r.status_code == 422


# ── list endpoint ─────────────────────────────────────────────────────────────
def test_list_showcase_empty(client):
    with patch("main.query", return_value=[]):
        r = client.get("/api/showcase")
    assert r.status_code == 200
    assert r.json() == []


# ── _vet_candidate wiring ─────────────────────────────────────────────────────
def _vet_json(**kw):
    base = {"verdict": "caution", "confidence": "medium", "rationale": "low base",
            "low_base": None}
    base.update(kw)
    return base


def test_vet_runs_with_reasoning_on_its_own_budget():
    """The vet is the one call asked to do arithmetic it cannot copy out of the
    text — 4 of 5 v4-flash rationales inverted the sequential comparison on
    2026-07-30. If this silently reverts to the fast path that regresses with no
    error anywhere; the verdict just goes back to being wrong."""
    with patch.object(showcase, "_annual_history", return_value=[]), \
         patch("rns_llm._call_deepseek", return_value=_vet_json()) as call:
        showcase._vet_candidate(_cand())
    assert call.call_args.kwargs["thinking"] is True
    assert call.call_args.kwargs["budget"] == showcase._VET_MAX_COMPLETION_TOKENS
    assert call.call_args.kwargs["tag"] == "showcase_vet"


def test_vet_budget_leaves_room_for_reasoning():
    """450 tokens covered the answer alone. Reasoning shares the budget, so the
    old cap would be spent before the answer started — every row a NULL verdict
    that looks exactly like an API outage."""
    assert showcase._VET_MAX_COMPLETION_TOKENS >= 4000


def test_vet_records_the_mode_in_the_model_label():
    """The 2026-07-30 audit could only split the failures by model because the
    label recorded it. Without the suffix, "did reasoning fix the arithmetic?"
    has no query that answers it."""
    with patch.object(showcase, "_annual_history", return_value=[]), \
         patch("rns_llm._call_deepseek", return_value=_vet_json()):
        vet = showcase._vet_candidate(_cand())
    assert vet["model"].endswith(":thinking")
    assert vet["verdict"] == "caution"


def test_vet_missing_history_still_vets():
    """Degrades to the announcement-only judgement rather than skipping."""
    with patch.object(showcase, "_annual_history", side_effect=RuntimeError("db down")), \
         patch("rns_llm._call_deepseek", return_value=_vet_json()) as call:
        assert showcase._vet_candidate(_cand())["verdict"] == "caution"
    call.assert_called_once()


def test_vet_truncation_propagates_as_a_failure():
    """A truncated vet must reach the caller's except branch and land as a NULL
    verdict — never as a verdict parsed from a half-written answer."""
    import rns_llm
    with patch.object(showcase, "_annual_history", return_value=[]), \
         patch("rns_llm._call_deepseek",
               side_effect=rns_llm.TruncatedResponse("out of budget")):
        with pytest.raises(rns_llm.TruncatedResponse):
            showcase._vet_candidate(_cand())


# ── Optional live vet sanity (opt-in — real DeepSeek call) ─────────────────────
@pytest.mark.skipif(
    not os.environ.get("RUN_LLM_TESTS"), reason="set RUN_LLM_TESTS=1 to hit DeepSeek"
)
def test_vet_flags_wise_nasdaq_listing():
    """The Wise secondary-listing case: a positive-framed story the market sold
    off. The vet should not wave it through as a clean 'include'."""
    cand = _cand(
        company_name="Wise plc", symbol="WISE.L", category="trading_update",
        headline="Wise proposes primary listing on the Nasdaq",
        llm_thesis="Nasdaq listing broadens investor access",
        llm_risks="UK index exclusion could force selling",
        summary="Wise intends to move its primary listing to the US.",
    )
    vet = showcase._vet_candidate(cand)
    assert vet["verdict"] in ("caution", "exclude")
