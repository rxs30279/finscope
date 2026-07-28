"""High Impact RNS showcase — sentiment, auto-flag, follow-ups, auto-archive and
the admin status/extend endpoints. DB access is mocked (showcase._q / ._exec and
main.query), so these run without a database."""
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

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
    vet = {"verdict": "include", "confidence": "high", "rationale": "clean", "model": "deepseek-chat"}
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=123.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates(hours=48)
    assert res == {"candidates": 1, "flagged": 1, "skipped_sentiment": 0,
                   "skipped_guidance": 0, "vetted": 1}
    params = ex.call_args[0][1]
    assert params[16] == "include"          # vet_verdict
    assert isinstance(params[20], datetime)  # vet_processed_at set


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
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 1
    assert res["vetted"] == 0
    params = ex.call_args[0][1]
    assert params[16] is None   # vet_verdict NULL
    assert params[20] is None   # vet_processed_at NULL


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
