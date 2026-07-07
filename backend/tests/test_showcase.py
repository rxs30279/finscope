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
    assert res == {"candidates": 1, "flagged": 1, "skipped_sentiment": 0, "vetted": 1}
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


# ── expire_tracked_entries ────────────────────────────────────────────────────
def test_expire_archives_only_expired_approved():
    with patch.object(showcase, "_exec", return_value=3) as ex:
        res = showcase.expire_tracked_entries()
    assert res == {"archived": 3}
    sql = ex.call_args[0][0]
    assert "archived" in sql and "approved" in sql and "track_until" in sql


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


# ── extend endpoint ───────────────────────────────────────────────────────────
def test_extend_happy(client):
    when = datetime(2026, 8, 1, tzinfo=timezone.utc)
    with patch("main.query", return_value=[{"track_until": when}]):
        r = client.post("/api/showcase/5/extend")
    assert r.status_code == 200
    assert r.json()["id"] == 5


def test_extend_not_found(client):
    with patch("main.query", return_value=[]):
        r = client.post("/api/showcase/5/extend")
    assert r.status_code == 404


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
