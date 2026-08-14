"""High Impact RNS showcase — sentiment, auto-flag, follow-ups, auto-archive and
the admin status/extend endpoints. DB access is mocked (showcase._q / ._exec and
main.query), so these run without a database."""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import gates
import showcase
import showcase_fwd


@pytest.fixture(autouse=True)
def _no_vet_network():
    """Keep the vet's full-text re-fetch off the network.

    Since 2026-08-03 _vet_candidate calls _vet_full_text, which re-fetches the
    announcement page to get past the 24k stored-body cap. The fixture URL is
    "http://x", so unpatched every vet test pays a DNS timeout — ~2.3s each,
    and the file header promises these run without external dependencies.

    Patched at the network boundary rather than over _vet_full_text itself, so
    the fallback logic still executes for real and the tests that exercise the
    fetch can simply re-patch this same name with their own return value."""
    with patch("showcase_fwd.fetch_announcement_text", return_value=None):
        yield


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


# ── Sequential base from earnings_quality (docs/rns-sequential-base-plan.md) ──
# Fixtures are the real stored earnings_quality for these five rns_ids, read
# from prod on 2026-08-04 (the plan's own worked examples, §5). ELIX and HSBA
# are exactly as stored — FRES and CTEC add a synthetic Revenue entry to
# simulate the Step 1 ranker-prompt fix landing (neither had one in the real
# row that day, which is the defect §1 of the plan is about).
_ELIX_EQ = [
    {"item": "Revenue", "kind": "income", "value": "£89.0m", "period": "H1 2026",
     "prior_value": "£71.2m (implied from 25% growth)", "one_off_named": None},
    {"item": "Adjusted EBITDA", "kind": "income", "value": "£27.6m", "period": "H1 2026",
     "prior_value": "£21.4m (implied from 29% growth)", "one_off_named": None},
]
_HSBA_EQ = [
    {"item": "Profit before tax", "kind": "income", "value": "$19.5bn", "period": "1H26",
     "prior_value": "$15.8bn",
     "one_off_named": "net favourable impact of notable items of $2.2bn"},
    {"item": "Revenue", "kind": "income", "value": "$37.7bn", "period": "1H26",
     "prior_value": "$34.1bn",
     "one_off_named": "net favourable impact of notable items of $0.8bn and "
                       "one-off property asset disposal gain of $0.2bn"},
]
_CGEO_EQ = [
    {"item": "Total portfolio value creation", "kind": "income", "value": "GEL 772,338",
     "period": "1H26", "prior_value": "GEL 1,014,360", "one_off_named": None},
    {"item": "Net income", "kind": "income", "value": "GEL 720,646", "period": "1H26",
     "prior_value": "GEL 988,747", "one_off_named": None},
]
_FRES_EQ_WITH_REVENUE = [
    {"item": "Revenue", "kind": "income", "value": "US$3,382.6m", "period": "H1 2026",
     "prior_value": "US$1,936.2m", "one_off_named": None},
    {"item": "Profit for the period", "kind": "income", "value": "US$1,463.4m",
     "period": "H1 2026", "prior_value": "US$467.6m", "one_off_named": None},
]
_CTEC_EQ_WITH_REVENUE = [
    {"item": "Revenue", "kind": "income", "value": "$1,232m", "period": "H1 2026",
     "prior_value": "$1,180m", "one_off_named": None},
    {"item": "Cost of revenue", "kind": "cost_or_charge", "value": "$900m",
     "period": "H1 2026", "prior_value": "$860m", "one_off_named": None},
]


def test_sequential_base_from_earnings_quality_fres_canonical_case():
    # The row that started the plan: +28.9% was derivable and the vet said it
    # couldn't be verified. 4,561.2 - 1,936.2 = 2,625.0; 3,382.6/2,625.0-1 = +28.9%.
    with patch.object(showcase, "_annual_history", return_value=[{"revenue": 4_561.2e6}]):
        base = showcase._sequential_base_from_earnings_quality(
            {"symbol": "FRES.L", "earnings_quality": _FRES_EQ_WITH_REVENUE}
        )
    assert base is not None
    assert base["period"] == "H1"
    assert abs(base["preceding_value"] - 2_625.0e6) < 1e5
    assert 28.5 < base["delta_pct"] < 29.3


def test_sequential_base_from_earnings_quality_elix_positive_control():
    with patch.object(showcase, "_annual_history", return_value=[{"revenue": 149.6e6}]):
        base = showcase._sequential_base_from_earnings_quality(
            {"symbol": "ELIX.L", "earnings_quality": _ELIX_EQ}
        )
    assert base is not None
    assert 13 < base["delta_pct"] < 14


def test_sequential_base_from_earnings_quality_ctec_negative_direction_control():
    with patch.object(showcase, "_annual_history", return_value=[{"revenue": 2_439e6}]):
        base = showcase._sequential_base_from_earnings_quality(
            {"symbol": "CTEC.L", "earnings_quality": _CTEC_EQ_WITH_REVENUE}
        )
    assert base is not None
    # "Cost of revenue" must not be picked up as the top line.
    assert base["current_value"] == 1_232e6
    assert -2.5 < base["delta_pct"] < -1.7


def test_sequential_base_from_earnings_quality_silent_on_hsba_named_one_off():
    # HSBA's Revenue line carries one_off_named — a raw sequential read of a
    # line the announcement itself says is one-off-flattered is not a clean
    # comparison. Default to silence (plan §5/§7).
    base = showcase._sequential_base_from_earnings_quality(
        {"symbol": "HSBA.L", "earnings_quality": _HSBA_EQ}
    )
    assert base is None


def test_sequential_base_from_earnings_quality_silent_on_cgeo_no_revenue_line():
    # No revenue/turnover item at all (only portfolio value creation / net
    # income), and its periods are quarters anyway — must stay silent.
    base = showcase._sequential_base_from_earnings_quality(
        {"symbol": "CGEO.L", "earnings_quality": _CGEO_EQ}
    )
    assert base is None


def test_sequential_base_from_earnings_quality_silent_when_field_absent():
    for eq in (None, [], "not a list"):
        assert showcase._sequential_base_from_earnings_quality(
            {"symbol": "ABC.L", "earnings_quality": eq}
        ) is None


def test_sequential_base_context_renders_the_fres_block():
    with patch.object(showcase, "_annual_history", return_value=[{"revenue": 4_561.2e6}]):
        text = showcase._sequential_base_context(
            {"symbol": "FRES.L", "earnings_quality": _FRES_EQ_WITH_REVENUE}
        )
    assert "Sequential comparison" in text
    assert "ABOVE the preceding half" in text
    assert "28.9%" in text


def test_sequential_base_context_empty_when_nothing_establishable():
    assert showcase._sequential_base_context({"symbol": "HSBA.L", "earnings_quality": _HSBA_EQ}) == ""
    assert showcase._sequential_base_context({}) == ""


def test_vet_prompt_includes_sequential_block_when_present():
    with patch.object(showcase, "_annual_history", return_value=[{"revenue": 4_561.2e6}]):
        msgs = showcase._vet_messages(
            _cand(symbol="FRES.L", earnings_quality=_FRES_EQ_WITH_REVENUE), []
        )
    user = msgs[1]["content"]
    assert "Sequential comparison" in user
    system = msgs[0]["content"]
    assert "use it rather than deriving your own sequential read" in system


def test_vet_prompt_omits_sequential_block_when_absent():
    msgs = showcase._vet_messages(_cand(earnings_quality=None), [])
    assert "Sequential comparison" not in msgs[1]["content"]


# ── One-off materiality handed to the vet ────────────────────────────────────
# Controls are the real stored extractions these rows produced, not invented
# fixtures. HSX is the row that motivated the whole change: the vet found a
# DIFFERENT, smaller one-off ($64.5m deferred tax) by reading the body and
# never sized the $173.7m at all.
_HSX_EQ_FIXED = [
    {"item": "Adjusted operating profit before tax", "kind": "income",
     "value": "$331.0m", "period": "H1 2026", "prior_value": "$262.0m",
     "one_off_named": "favourable prior-year development of $173.7 million"},
    {"item": "Prior-year development", "kind": "income", "value": "$173.7m",
     "period": "H1 2026", "prior_value": "$292.7m", "one_off_named": None},
]
# TW.L 9697075 as stored: the £222.2m cladding provision IS the line, so the
# ratio is a degenerate 100% that sizes nothing.
_TW_EQ_SELF_REF = [
    {"item": "Exceptional charge", "kind": "cost_or_charge", "value": "£222.2m",
     "period": "H1 2026", "prior_value": None,
     "one_off_named": "£222.2 million increase in cladding fire safety provision"},
]
# BA.L 9694659 as stored: named, but no figure in the one-off text to divide by.
_BA_EQ_UNQUANTIFIED = [
    {"item": "Free cash flow", "kind": "income", "value": "£1,234m",
     "period": "H1 2026", "prior_value": "£(368)m",
     "one_off_named": "high level of customer advances"},
]


def test_one_off_materiality_context_renders_the_hsx_ratio():
    text = showcase._one_off_materiality_context(
        {"symbol": "HSX.L", "earnings_quality": _HSX_EQ_FIXED}
    )
    assert "Named one-off materiality" in text
    assert "52.5% of it" in text
    # Quoted as the announcement printed it — never re-labelled with the
    # database's financial_currency, which is a different field entirely.
    assert "$173.7 million" in text
    # The one-off's own line is not itself sized against itself.
    assert text.count("equal to") == 1


def test_one_off_materiality_context_drops_the_self_referential_ratio():
    # Mirrors gates._gate_one_off returning n/a "self_referential": a 100%
    # ratio is not an adjudication however clean it looks.
    assert showcase._one_off_materiality_context(
        {"symbol": "TW.L", "earnings_quality": _TW_EQ_SELF_REF}
    ) == ""


def test_one_off_materiality_context_silent_when_nothing_quantifiable():
    # Unquantified named one-offs are left to the vet's own reading of the
    # body — it needs no help FINDING those, only sizing them.
    for eq in (_BA_EQ_UNQUANTIFIED, None, [], "not a list"):
        assert showcase._one_off_materiality_context(
            {"symbol": "ABC.L", "earnings_quality": eq}
        ) == ""


def test_vet_prompt_includes_one_off_block_and_its_absence_guard():
    msgs = showcase._vet_messages(
        _cand(symbol="HSX.L", earnings_quality=_HSX_EQ_FIXED), []
    )
    assert "Named one-off materiality" in msgs[1]["content"]
    system = msgs[0]["content"]
    assert "use the percentage given rather than working out your own" in system
    # The load-bearing guard: silence must never read as "no one-offs here".
    assert "ABSENCE is not evidence the result is clean" in system


def test_vet_prompt_omits_one_off_block_when_absent():
    msgs = showcase._vet_messages(_cand(earnings_quality=None), [])
    assert "Named one-off materiality" not in msgs[1]["content"]


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


# ── FX for the leverage floor ─────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_fx_cache(tmp_path):
    """_fx_to_gbp memoises for 6h in memory AND on disk, so without this one
    test's rates leak into the next (and into the flag tests, which call it).
    The snapshot path is redirected into tmp_path so a test run can never read
    or clobber the developer's real cache file."""
    showcase._FX_CACHE["rates"] = None
    showcase._FX_CACHE["at"] = None
    with patch.object(showcase, "_FX_SNAPSHOT_DIR", str(tmp_path)), \
         patch.object(showcase, "_FX_SNAPSHOT_PATH", str(tmp_path / "fx.json")):
        yield
    showcase._FX_CACHE["rates"] = None
    showcase._FX_CACHE["at"] = None


def _fx_rows(*codes):
    return [{"code": c} for c in codes]


def test_fx_keeps_gbp_when_the_rate_lookup_dies():
    """A Yahoo/DB outage must not cost STERLING reporters the net-debt-vs-cap
    check — they never needed a rate. Only foreign names lose it (rate NULL →
    the SQL's OR-chain leaves that one test unevaluated)."""
    with patch.object(showcase, "_q", side_effect=RuntimeError("db down")):
        assert showcase._fx_to_gbp() == {"GBP": 1.0}


def test_fx_one_dead_pair_does_not_cost_the_others_their_rate():
    """GELGBP=X genuinely does not exist on Yahoo (3 companies report in GEL),
    so a per-pair failure has to be survivable rather than fatal."""
    def _ticker(t):
        if t == "GELGBP=X":
            raise RuntimeError("404")
        obj = type("T", (), {})()
        obj.fast_info = {"lastPrice": 0.74 if t == "GBP=X" else 0.86}
        return obj

    fake_yf = type("yf", (), {"Ticker": staticmethod(_ticker)})
    with patch.object(showcase, "_q", return_value=_fx_rows("USD", "EUR", "GEL")), \
         patch.dict("sys.modules", {"yfinance": fake_yf}):
        rates = showcase._fx_to_gbp()
    assert rates == {"GBP": 1.0, "USD": 0.74, "EUR": 0.86}
    assert "GEL" not in rates          # unevaluable, not defaulted to 1.0


def test_fx_never_defaults_a_missing_rate_to_one():
    """The dangerous failure would be treating an unknown currency as parity —
    that silently recreates the very bug this exists to fix."""
    def _ticker(t):
        raise RuntimeError("no data")

    fake_yf = type("yf", (), {"Ticker": staticmethod(_ticker)})
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": fake_yf}):
        rates = showcase._fx_to_gbp()
    assert rates == {"GBP": 1.0}
    assert "USD" not in rates


def _fake_yf(rates_by_ticker):
    def _ticker(t):
        if t not in rates_by_ticker:
            raise RuntimeError("404")
        obj = type("T", (), {})()
        obj.fast_info = {"lastPrice": rates_by_ticker[t]}
        return obj

    return type("yf", (), {"Ticker": staticmethod(_ticker)})


def test_fx_snapshot_carries_rates_across_processes():
    """The whole point of the on-disk tier: the RNS cron is a fresh process
    every 15 minutes, so a second 'process' must reuse the first one's rates
    instead of re-paying a ~3.4s Yahoo fetch."""
    yf = _fake_yf({"GBP=X": 0.74})
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": yf}):
        first = showcase._fx_to_gbp()
    assert first == {"GBP": 1.0, "USD": 0.74}

    # Simulate a brand-new process: memory empty, snapshot file still there.
    showcase._FX_CACHE["rates"] = None
    showcase._FX_CACHE["at"] = None
    boom = _fake_yf({})  # any network call now raises
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": boom}):
        second = showcase._fx_to_gbp()
    assert second == {"GBP": 1.0, "USD": 0.74}


def test_fx_stale_snapshot_is_ignored():
    showcase._fx_save_snapshot({"GBP": 1.0, "USD": 0.60})
    stale = datetime.now(timezone.utc) - timedelta(seconds=showcase._FX_TTL_SECONDS + 60)
    with open(showcase._FX_SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"at": stale.isoformat(), "rates": {"GBP": 1.0, "USD": 0.60}}, fh)
    assert showcase._fx_load_snapshot() is None


def test_fx_snapshot_without_sterling_is_treated_as_corrupt():
    """A snapshot missing GBP would drop the check for all 617 sterling
    reporters — refetch instead of trusting it."""
    with open(showcase._FX_SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"at": datetime.now(timezone.utc).isoformat(),
                   "rates": {"USD": 0.74}}, fh)
    assert showcase._fx_load_snapshot() is None


def test_fx_degraded_result_is_never_persisted_as_rates():
    """Writing a sterling-only dict as if it were good rates would pin every
    foreign name's check off for the whole 6h TTL on one Yahoo outage."""
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({})}):
        assert showcase._fx_to_gbp() == {"GBP": 1.0}
    # The failure marker IS written (that is the backoff), but no rates.
    blob = showcase._fx_read_blob()
    assert blob.get("failed_at")
    assert not blob.get("rates")


def _write_blob(rates=None, age_seconds=0, failed_seconds_ago=None):
    blob = {}
    if rates is not None:
        blob["rates"] = rates
        blob["at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        ).isoformat()
    if failed_seconds_ago is not None:
        blob["failed_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=failed_seconds_ago)
        ).isoformat()
    showcase._fx_write_blob(blob)


def test_fx_backs_off_instead_of_retrying_every_run():
    """The point of the backoff: a Yahoo outage must not mean ~16 cron runs a
    day each hammering it. Inside the window we make no call at all."""
    _write_blob(failed_seconds_ago=60)
    calls = []

    def _ticker(t):
        calls.append(t)
        raise RuntimeError("still down")

    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": type("yf", (), {"Ticker": staticmethod(_ticker)})}):
        showcase._fx_to_gbp()
    assert calls == []


def test_fx_retries_once_the_backoff_expires():
    _write_blob(failed_seconds_ago=showcase._FX_FAIL_BACKOFF_SECONDS + 60)
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({"GBP=X": 0.74})}):
        assert showcase._fx_to_gbp() == {"GBP": 1.0, "USD": 0.74}


def test_fx_serves_stale_rates_during_an_outage():
    """Adding a backoff without this would make outages WORSE — foreign names
    would lose the check for 30 minutes rather than retrying every 15. A
    day-old rate beats no rate for a test whose contested band is 1.0-1.27."""
    _write_blob(rates={"GBP": 1.0, "USD": 0.74}, age_seconds=26 * 3600,
                failed_seconds_ago=60)
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({})}):
        assert showcase._fx_to_gbp() == {"GBP": 1.0, "USD": 0.74}


def test_fx_stops_trusting_rates_that_are_too_stale():
    _write_blob(rates={"GBP": 1.0, "USD": 0.74},
                age_seconds=showcase._FX_STALE_MAX_SECONDS + 3600,
                failed_seconds_ago=60)
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({})}):
        assert showcase._fx_to_gbp() == {"GBP": 1.0}


def test_fx_failure_preserves_existing_rates_on_disk():
    """Stamping the backoff must not wipe the rates the outage window needs."""
    _write_blob(rates={"GBP": 1.0, "USD": 0.74}, age_seconds=10 * 3600)
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({})}):
        showcase._fx_to_gbp()
    blob = showcase._fx_read_blob()
    assert blob["rates"] == {"GBP": 1.0, "USD": 0.74}
    assert blob.get("failed_at")


def test_fx_success_clears_the_failure_marker():
    _write_blob(rates={"GBP": 1.0, "USD": 0.60},
                age_seconds=10 * 3600,
                failed_seconds_ago=showcase._FX_FAIL_BACKOFF_SECONDS + 60)
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({"GBP=X": 0.74})}):
        assert showcase._fx_to_gbp() == {"GBP": 1.0, "USD": 0.74}
    assert not showcase._fx_read_blob().get("failed_at")


def test_fx_stale_result_does_not_poison_the_memory_cache():
    """The memory slot means "fresh for 6h". Parking stale rates there would
    suppress the retry once the backoff expires."""
    _write_blob(rates={"GBP": 1.0, "USD": 0.74}, age_seconds=26 * 3600,
                failed_seconds_ago=60)
    with patch.object(showcase, "_q", return_value=_fx_rows("USD")), \
         patch.dict("sys.modules", {"yfinance": _fake_yf({})}):
        showcase._fx_to_gbp()
    assert showcase._FX_CACHE["rates"] is None


def test_fx_skips_currencies_with_no_yahoo_pair():
    """GELGBP=X 404s in ~0.56s on every run. Skipping it must not change the
    outcome — GEL stays absent, i.e. unevaluable."""
    calls = []

    def _ticker(t):
        calls.append(t)
        obj = type("T", (), {})()
        obj.fast_info = {"lastPrice": 0.74}
        return obj

    yf = type("yf", (), {"Ticker": staticmethod(_ticker)})
    with patch.object(showcase, "_q", return_value=_fx_rows("USD", "GEL")), \
         patch.dict("sys.modules", {"yfinance": yf}):
        rates = showcase._fx_to_gbp()
    assert "GELGBP=X" not in calls
    assert "GEL" not in rates
    assert rates == {"GBP": 1.0, "USD": 0.74}


def test_flag_passes_fx_codes_and_rates_into_the_candidate_query():
    """Parallel arrays land in the two slots the SQL's unnest() zips, directly
    after PEER_MARGIN_MIN_GROUP and before the llm_score floor. Positional, so
    a reordered param tuple silently mis-binds the whole WHERE clause."""
    with patch.object(showcase, "_fx_to_gbp", return_value={"GBP": 1.0, "USD": 0.74}), \
         patch.object(showcase, "_q", return_value=[]) as q:
        showcase.flag_high_impact_candidates(hours=48)
    params = q.call_args[0][1]
    assert params[0] == showcase.PEER_MARGIN_MIN_GROUP
    assert params[1] == ["GBP", "USD"]
    assert params[2] == [1.0, 0.74]
    assert params[3] == showcase.HIGH_IMPACT_VET_ENTRY_SCORE
    # The two arrays must stay index-aligned or every rate binds to the wrong
    # currency — the failure mode would be silent, not an error.
    assert len(params[1]) == len(params[2])


# ── flag_high_impact_candidates ───────────────────────────────────────────────
def test_flag_keeps_positive_and_stores_vet():
    vet = {"verdict": "include", "confidence": "high", "rationale": "clean",
           "score": 85,
           "model": "deepseek-chat", "low_base": {"period": "H1"}}
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=123.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation") as record_lb, \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates(hours=48)
    assert res == {"candidates": 1, "flagged": 1, "skipped_sentiment": 0,
                   "skipped_guidance": 0, "skipped_earnings_quality": 0,
                   "vetted": 1, "shadowed": 0}
    params = ex.call_args[0][1]
    assert params[16] == "include"          # vet_verdict
    assert isinstance(params[20], datetime)  # vet_processed_at set
    assert params[21] == 85                 # vet_score
    assert params[-1] == "approved"         # 85 >= publish floor
    # The raw low_base dict is saved verbatim onto the INSERT (migration 028),
    # in addition to being shadow-evaluated below — the gate's own evidence
    # only survives on rows it manages to adjudicate, so the model's own
    # extraction needs its own durable copy.
    assert params[22].adapted == {"period": "H1"}   # low_base
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


def test_flag_vet_failure_shadows_instead_of_publishing():
    """CONTRACT REVERSED 2026-08-03 (migration 029). A failed vet used to flag
    the story anyway with a NULL verdict; now vet_score decides publication and
    a NULL score is not a passing score, so the row is stored as 'shadow'.

    This is the sharpest edge of the new design: a DeepSeek outage during the
    morning batch no longer mislabels stories, it withholds them. The row is
    still INSERTed, so nothing is lost and a re-vet can promote it — but the
    public page stays empty until the API recovers."""
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", side_effect=RuntimeError("api down")), \
         patch.object(gates, "record_low_base_evaluation") as record_lb, \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 0
    assert res["shadowed"] == 1
    assert res["vetted"] == 0
    params = ex.call_args[0][1]
    assert params[16] is None   # vet_verdict NULL
    assert params[20] is None   # vet_processed_at NULL
    assert params[21] is None   # vet_score NULL — never treat as 0
    assert params[22] is None   # low_base NULL — no vet output to save
    assert params[-1] == "shadow"
    # A failed vet still gets a (n/a/not_vetted) low_base evaluation recorded.
    assert record_lb.call_args[0][1]["low_base"] is None


def test_flag_never_re_vets_an_announcement_that_already_has_a_score():
    """The 2026-08-05 cost bug. The symbol-level dedupe deliberately lets shadow
    rows back into the pool, so nothing stopped the SAME rns_id being re-vetted
    on every one of the ~16 cron runs a morning — ~8 reasoning-heavy calls per
    run, every one of them discarded by the ON CONFLICT. It also made publishing
    a lottery: the vet is not reproducible on identical input, and NXT.L rolled
    a 75 on its sixth re-vet that morning only for the INSERT to drop it.

    Asserted on the SQL because the exclusion has to happen in the candidate
    query — a Python-side skip would still have paid for the row's selection but,
    more to the point, the point of the fix is that the vet call is never made."""
    with patch.object(showcase, "_q", return_value=[]) as q, \
         patch.object(showcase, "_vet_candidate") as vet:
        showcase.flag_high_impact_candidates()
    sql = " ".join(q.call_args[0][0].split())
    assert "SELECT 1 FROM high_impact_rns h2 WHERE h2.rns_id = r.id" in sql
    assert "AND h2.vet_score IS NOT NULL" in sql
    vet.assert_not_called()


def test_flag_conflict_clause_only_overwrites_a_failed_vet():
    """The other half: a row kept eligible by the NULL-score exception must be
    able to land its retry. DO NOTHING silently threw it away, which is why the
    failure path above could never actually promote anything."""
    vet = {"verdict": "include", "confidence": "high", "rationale": "clean",
           "score": 88, "model": "deepseek-v4-flash:thinking", "low_base": None}
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        showcase.flag_high_impact_candidates()
    sql = " ".join(ex.call_args[0][0].split())
    assert "ON CONFLICT (rns_id) DO UPDATE SET" in sql
    assert "vet_score = EXCLUDED.vet_score" in sql
    # Without this guard the upsert would let a re-vet overwrite a stored
    # verdict — the exact non-determinism the candidate SQL now prevents.
    assert "WHERE high_impact_rns.vet_score IS NULL" in sql


def test_flag_shadows_a_vetted_row_below_the_publish_floor():
    """The 60-74 llm_score band's normal outcome: vetted, scored, stored,
    invisible. The row must still carry its full vet output — that band is the
    only evidence base for calibrating HIGH_IMPACT_MIN_VET_SCORE, and it cannot
    be rebuilt later because rns_announcements rows get pruned."""
    vet = {"verdict": "caution", "confidence": "medium", "rationale": "dilution",
           "score": 64, "model": "deepseek-v4-flash:thinking",
           "low_base": {"period": "H1"}}
    with patch.object(showcase, "_q", return_value=[_cand(llm_score=65)]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 0
    assert res["shadowed"] == 1
    assert res["vetted"] == 1
    params = ex.call_args[0][1]
    assert params[-1] == "shadow"
    assert params[21] == 64                        # vet_score stored
    assert params[16] == "caution"                 # full vet output kept
    assert params[22].adapted == {"period": "H1"}  # low_base kept


def test_flag_publishes_a_promoted_row_the_ranker_underrated():
    """The point of dropping the entry floor to 60: the vet can PROMOTE. A
    story the ranker scored 65 — previously never even looked at — reaches the
    public page on the vet's own judgement."""
    vet = {"verdict": "include", "confidence": "high", "rationale": "clean",
           "score": 82, "model": "deepseek-v4-flash:thinking", "low_base": None}
    with patch.object(showcase, "_q", return_value=[_cand(llm_score=65)]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 1
    assert res["shadowed"] == 0
    assert ex.call_args[0][1][-1] == "approved"


def test_flag_demotes_a_high_ranker_score_the_vet_distrusts():
    """The other half: an 85 the vet scores down no longer publishes. Three
    rows currently live carry verdict='exclude' precisely because the old
    design could not do this."""
    vet = {"verdict": "exclude", "confidence": "high", "rationale": "guidance cut",
           "score": 30, "model": "deepseek-v4-flash:thinking", "low_base": None}
    with patch.object(showcase, "_q", return_value=[_cand(llm_score=85)]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["flagged"] == 0
    assert res["shadowed"] == 1
    assert ex.call_args[0][1][-1] == "shadow"


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


def test_disqualifying_guidance_no_longer_arms_reiterated_in_line():
    # DISARMED 2026-08-04. It was 8 of the 9 guidance blocks ever recorded and
    # no return horizon had ever judged it, and KLR.L 9702412 showed it cannot
    # tell "reiterated against a consensus just UPGRADED to meet it" (an H1
    # beat with a record order book) from the stale-consensus non-catalyst it
    # was built for. It now lives in the shadow guidance_wide gate instead.
    entry = {"vs_prior": "reiterated", "vs_consensus": "in_line"}
    assert showcase._disqualifying_guidance({"guidance_checks": [entry]}) is None
    assert showcase._unarmed_disqualifying_guidance({"guidance_checks": [entry]}) == (
        "reiterated_in_line", entry,
    )


def test_unarmed_guidance_catches_a_first_time_guide_below_consensus():
    # CLI.L 9702416 — FY EPS guided 4.6-5.5p against a printed 6.8p consensus,
    # a ~32% miss, labelled `new` because it was the first guide of the year.
    # The armed rule's vs_prior restriction lets it through; before this it came
    # back as a clean `pass`, which is worse than not adjudicating it at all.
    entry = {"vs_prior": "new", "vs_consensus": "below",
             "guided_value": "4.6 to 5.5 pence per share",
             "consensus_value": "6.8 pence per share"}
    assert showcase._disqualifying_guidance({"guidance_checks": [entry]}) is None
    assert showcase._unarmed_disqualifying_guidance({"guidance_checks": [entry]}) == (
        "below_consensus_other_vs_prior", entry,
    )


def test_unarmed_guidance_leaves_a_genuinely_clean_row_alone():
    # SYNT.L 9702422 — raised guidance, above consensus. Neither rule may touch
    # it, or the armed gate stops reporting `pass` on rows that deserve one.
    assert showcase._unarmed_disqualifying_guidance({"guidance_checks": [
        {"vs_prior": "raised", "vs_consensus": "above"},
        {"vs_prior": "new", "vs_consensus": "no_consensus_stated"},
    ]}) is None


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


def _luce_cand(vs_consensus):
    return {"guidance_checks": [
        {"metric": "Adjusted Operating Profit", "period": "FY2026",
         "guided_value": "> £40m", "consensus_value": "£40.7m",
         "vs_prior": "reiterated", "vs_consensus": vs_consensus},
        {"metric": "Adjusted Operating Profit", "period": "FY2027",
         "guided_value": "to exceed current market expectations",
         "consensus_value": "£42.3m",
         "vs_prior": "new", "vs_consensus": "above"},
    ]}


# LUCE 9689898 scored 7x at temperature 0.2 — the actual labels returned.
# vs_prior was "reiterated" every time; vs_consensus split 4 below / 3 in_line.
# The gate had to fire on all seven, because the score did not: it came back 75
# six times and 85 once, never below the flag threshold.
_LUCE_OBSERVED = ["below", "below", "in_line", "in_line", "below", "below", "in_line"]


def test_armed_gate_on_the_seven_observed_luce_samples():
    """This is the price of disarming in_line, stated as a number.

    The armed rule now fires on the 4 "below" runs and not the 3 "in_line"
    ones, so LUCE itself would be blocked 4 times in 7 rather than 7 in 7 — on
    a row where the model's label wobbled over one figure (">£40m" is a floor
    and £40.7m is 1.75% above it), not over anything about the announcement.
    That is a real regression in coverage of the case this whole gate came
    from, accepted because the in_line rule was 8 of 9 lifetime blocks with
    zero return evidence, and because the run below keeps the record.
    """
    fired = [showcase._disqualifying_guidance(_luce_cand(c)) is not None
             for c in _LUCE_OBSERVED]
    assert fired.count(True) == 4
    assert all(showcase._disqualifying_guidance(_luce_cand(c)) is not None
               for c in ("below",))


def test_armed_plus_shadow_still_covers_all_seven_luce_samples():
    # Nothing about LUCE became invisible — the 3 in_line runs move to the
    # shadow gate, which is what makes the disarm reversible on evidence.
    for vs_consensus in _LUCE_OBSERVED:
        cand = _luce_cand(vs_consensus)
        assert (
            showcase._disqualifying_guidance(cand) is not None
            or showcase._unarmed_disqualifying_guidance(cand) is not None
        )


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


def test_parse_bps_reads_a_standalone_percentage_as_a_rate():
    # UK banks print the cost of risk and the asset quality ratio as
    # percentages, not bps. Requiring the unit hid both of the only two
    # percentage-printed rate pairs in the table.
    assert showcase._parse_bps("0.25%") == 25
    assert showcase._parse_bps("0.19%") == 19
    assert showcase._parse_bps("  3.19 % ") == 319
    # Parentheses are the accounting charge convention, not a sign. Reading
    # VANQ's "(7.0)% vs (6.6)%" as -700 vs -660 would turn a 40bps
    # deterioration into an improvement.
    assert showcase._parse_bps("(7.0)%") == 700
    assert showcase._parse_bps("(6.6)%") == 660
    # An explicit minus is a real release and is honoured.
    assert showcase._parse_bps("-10.85%") == -1085
    # A bps figure still wins over any percentage in the same string.
    assert showcase._parse_bps("62bps (0.62%)") == 62


def test_parse_bps_refuses_percentages_in_prose_and_money():
    # "increased 38%" read as 3,800bps would fire the bank gate on an income
    # line's own comparator, so a percentage only counts when it is the whole
    # string. "38%" alone IS now read — on a bank cost_or_charge line that is a
    # rate, and the gate never reaches this parser on any other kind of line.
    for s in ("increased 38%", "up 38% to £1.4bn", "38% of revenue",
              "£1.4bn", "c.£225m", "62", "", None, 62):
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
    # Enumeration is unstable — 2 to 7 entries across 7 BARC runs — so the rule
    # must fire on either window rather than letting the outcome depend on
    # which period the model happened to enumerate. Q2's +7bps is the tightest
    # rise we need to catch and the threshold sits exactly on it.
    q2 = {"item": "Loan loss rate", "period": "Q2 2026", "value": "51bps",
          "prior_value": "44bps", "kind": "cost_or_charge"}
    assert showcase._worsening_loss_rate(
        {**_BANK, "earnings_quality": [q2]}
    ) == q2


# The two percentage-printed rate pairs the bps-only parser used to discard.
# Both are real stored rows from 2026-07-30; between them they are the only
# reason this parser changed, so they are pinned as fixtures.
_VANQ_COR = {
    "item": "Cost of risk", "period": "H1 2026", "value": "(7.0)%",
    "prior_value": "(6.6)%", "kind": "cost_or_charge", "one_off_named": None,
}
_LLOY_AQR = {
    "item": "Asset quality ratio", "period": "H1 2026", "value": "0.25%",
    "prior_value": "0.19%", "kind": "cost_or_charge", "one_off_named": None,
}


def test_worsening_loss_rate_catches_a_cost_of_risk_printed_as_a_percentage():
    # VANQ.L 2026-07-30: cost of risk 6.6 -> 7.0%, i.e. +40bps, and the stock
    # fell 17% over the following two sessions. The gate scored the row as
    # unparseable purely because the bank wrote "%" instead of "bps".
    assert showcase._worsening_loss_rate(
        {**_BANK, "earnings_quality": [_VANQ_COR]}
    ) == _VANQ_COR


def test_worsening_loss_rate_ignores_a_six_bp_rise_off_a_benign_base():
    # LLOY.L 2026-07-30: asset quality ratio 0.19 -> 0.25%. That is +32% in
    # relative terms — a bigger relative move than BARC's — and the stock still
    # rose 5.6%, because 0.19% is an exceptionally benign base. The threshold
    # keeps it out; see the note on _BANK_LLR_RISE_BPS for why a delta-in-bps
    # rule is the wrong shape for this case rather than merely mis-tuned.
    assert showcase._worsening_loss_rate(
        {**_BANK, "earnings_quality": [_LLOY_AQR]}
    ) is None


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
         patch.object(showcase, "_vet_candidate",
                      return_value={"verdict": "include", "score": 85}), \
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


# ── _story_close baseline ─────────────────────────────────────────────────────
def test_story_close_excludes_the_announcement_days_own_close():
    """The baseline must come from before the story broke. The old rule
    (date <= published_at::date) only held while the flag ran before that day's
    close; a row flagged a day late got the close CONTAINING its own move, so
    "% since news" measured the move from its own endpoint. CMCX.L rose
    458 -> 650 on its story day and read as flat."""
    with patch.object(showcase, "_q", return_value=[{"close": 620.0}]) as q:
        showcase._story_close("ELIX.L", datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc))
    sql = " ".join(q.call_args[0][0].split())
    # The same-day close is admissible ONLY after the close time.
    assert "p.date < s.local_ts::date" in sql
    assert "s.local_ts::time > %s::time" in sql
    # Regression guard on the exact rule that caused the bug.
    assert "date <= %s::date" not in sql


def test_story_close_boundary_is_the_lse_close_in_london_time():
    """published_at is UTC and the table spans BST and GMT, so a fixed offset
    would be an hour wrong for half the year. The cutoff is also the real
    closing-auction time — an announcement released after it genuinely did not
    move that day's close, and treating it as if it had would swap in a stale
    baseline a full session early."""
    assert showcase._LSE_CLOSE_LOCAL == "16:30"
    with patch.object(showcase, "_q", return_value=[]) as q:
        showcase._story_close("X.L", datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc))
    sql = " ".join(q.call_args[0][0].split())
    assert "AT TIME ZONE 'Europe/London'" in sql
    params = q.call_args[0][1]
    # The full timestamp is passed, not a date — the time of day IS the input.
    assert params[0] == datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)
    assert params[1] == "X.L"
    assert params[2] == showcase._LSE_CLOSE_LOCAL


def test_story_close_returns_none_when_no_price_history():
    """No baseline is better than a wrong one — _enrich leaves the % blank."""
    with patch.object(showcase, "_q", return_value=[]):
        assert showcase._story_close("NEW.L", datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)) is None


# ── _entry_open / the gap split ───────────────────────────────────────────────
def test_entry_open_takes_the_announcement_days_own_open_before_the_bell():
    """A 07:00 RNS is public by the 08:00 open, so THAT day's open is the first
    dealable price. The helper this replaced (_next_open) took the day after,
    skipping the whole session the news was priced into — the off-by-one that
    flattened the signal in the score-performance work."""
    with patch.object(showcase, "_q", return_value=[{"open": 110.0}]) as q:
        assert showcase._entry_open(
            "ABC.L", datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)) == 110.0
    sql = " ".join(q.call_args[0][0].split())
    # Same-day bar admissible only when the release beat the open; later
    # announcements fall through to the next session.
    assert "p.date > s.local_ts::date" in sql
    assert "p.date = s.local_ts::date AND s.local_ts::time < %s::time" in sql
    assert "ORDER BY p.date ASC" in sql
    # Never the blanket "day after" rule.
    assert "date > %s::date" not in sql


def test_entry_open_boundary_is_the_lse_open_in_london_time():
    """published_at is UTC and the table spans BST and GMT, so a fixed offset
    would be an hour wrong for half the year — and an hour is the difference
    between the 07:00 slot and the open."""
    assert showcase._LSE_OPEN_LOCAL == "08:00"
    with patch.object(showcase, "_q", return_value=[]) as q:
        assert showcase._entry_open(
            "X.L", datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)) is None
    sql = " ".join(q.call_args[0][0].split())
    assert "AT TIME ZONE 'Europe/London'" in sql
    assert q.call_args[0][1][2] == showcase._LSE_OPEN_LOCAL


def _showcase_row(**kw):
    """A stored high_impact_rns row, as _enrich receives it."""
    base = dict(
        id=7, rns_id=1, symbol="ABC.L", company_name="Abc plc",
        headline="FY results", url="http://x", summary="Strong year",
        published_at=datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc),
        category="final_results", tier="A", status="approved",
        llm_score=80, llm_confidence="high", llm_thesis="beat", llm_risks="none",
        vet_verdict="include", vet_confidence="high", vet_rationale="clean",
        vet_score=82, story_close=100.0,
        flagged_at=None, decided_at=None,
        fwd_multiple=None, fwd_metric=None, fwd_basis=None, fwd_is_bound=None,
        fwd_period=None, fwd_quote=None,
    )
    base.update(kw)
    return base


def test_enrich_splits_the_move_into_gap_and_since_open():
    """The two halves must compound back to the whole. A reader who sees only
    "+21%" cannot tell whether it was there to take: here 10 points gapped open
    before anyone could deal and 10 points were available afterwards, and the
    page has to be able to say which was which."""
    with patch("main._watchlist_rows",
               return_value=[{"symbol": "ABC.L", "name": "Abc plc",
                              "current_price": 121.0}]), \
         patch("main._scrub_screener_metrics"), patch("main._attach_pegy"), \
         patch.object(showcase, "_q", return_value=[]), \
         patch.object(showcase, "_entry_open", return_value=110.0):
        row = showcase._enrich([_showcase_row()])[0]

    assert row["gap_pct"] == 10.0                 # 100 -> 110, untradeable
    assert row["pct_since_entry_open"] == 10.0    # 110 -> 121, tradeable
    assert row["entry_open"] == 110.0
    # (1 + gap) * (1 + since) - 1 == the old single figure, so the split loses
    # nothing.
    assert row["pct_since_news"] == 21.0


def test_enrich_leaves_both_halves_blank_until_the_entry_open_exists():
    """A story that broke this morning has no open on record. Blank, never a
    zero — a 0.0% gap reads as "the market shrugged", which is a claim."""
    with patch("main._watchlist_rows",
               return_value=[{"symbol": "ABC.L", "name": "Abc plc",
                              "current_price": 121.0}]), \
         patch("main._scrub_screener_metrics"), patch("main._attach_pegy"), \
         patch.object(showcase, "_q", return_value=[]), \
         patch.object(showcase, "_entry_open", return_value=None):
        row = showcase._enrich([_showcase_row()])[0]

    assert row["gap_pct"] is None
    assert row["pct_since_entry_open"] is None
    assert row["entry_open"] is None


# ── list endpoint ─────────────────────────────────────────────────────────────
def test_list_showcase_empty(client):
    with patch("main.query", return_value=[]):
        r = client.get("/api/showcase")
    assert r.status_code == 200
    assert r.json() == []


def test_list_showcase_public_never_returns_shadow_rows(client):
    """The public list must stay keyed on status='approved'. A shadow row is a
    story the vet REJECTED — leaking it onto the public page would undo the one
    thing the vet exists to do."""
    with patch("main.query", return_value=[]) as q:
        client.get("/api/showcase")
    sql = q.call_args[0][0]
    assert "status = 'approved'" in sql
    assert "shadow" not in sql


def test_list_showcase_hides_old_stories_without_deleting_them(client):
    """The page restarts at SHOWCASE_MIN_STORY_DATE. This is a display floor in
    the SELECT and nothing else: the rows stay in high_impact_rns, keep their
    follow-ups, and still answer /gates and every calibration query. If this
    ever becomes a DELETE the calibration history goes with it."""
    with patch("main.query", return_value=[]) as q:
        r = client.get("/api/showcase")
    assert r.status_code == 200
    sql = " ".join(q.call_args[0][0].split())
    assert "(published_at AT TIME ZONE 'Europe/London')::date >= %s::date" in sql
    assert q.call_args[0][1] == (showcase.SHOWCASE_MIN_STORY_DATE,)
    assert "DELETE" not in sql.upper()


def test_list_shadow_applies_the_same_display_floor(client):
    """Withheld rows are interleaved into the same table as published ones, so a
    floor on only one list would leave old withheld stories sitting above
    published ones the page no longer shows."""
    with patch("main.query", return_value=[]) as q:
        client.get("/api/showcase/shadow")
    sql = " ".join(q.call_args[0][0].split())
    assert "(published_at AT TIME ZONE 'Europe/London')::date >= %s::date" in sql
    assert q.call_args[0][1] == (showcase.SHOWCASE_MIN_STORY_DATE,)


def test_list_shadow_is_admin_only(client):
    """These are unpublished judgements about live companies. If the token guard
    is ever dropped, every story the vet withheld becomes public — the exact
    outcome the shadow status exists to prevent."""
    r = client.get("/api/showcase/shadow", headers={"X-Admin-Token": "wrong"})
    assert r.status_code in (401, 403)


def test_list_shadow_selects_shadow_ordered_by_vet_score(client):
    """Ordering is load-bearing, not cosmetic: the near-misses just under 75 are
    the rows that inform whether the floor is set right, so they must sort first.
    NULLS LAST keeps failed vet calls from squatting the top on a score they
    never produced."""
    with patch("main.query", return_value=[]) as q:
        r = client.get("/api/showcase/shadow")
    assert r.status_code == 200
    sql = " ".join(q.call_args[0][0].split())
    assert "status = 'shadow'" in sql
    assert "ORDER BY vet_score DESC NULLS LAST" in sql


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


# ── vet_score cleaning (migration 029) ────────────────────────────────────────
# This number now decides publication, so the prompt's rules are re-enforced in
# Python rather than trusted. See showcase._clean_vet_score.
def test_vet_score_coerces_and_clamps():
    assert showcase._clean_vet_score(82, "include") == 82
    assert showcase._clean_vet_score("82", "include") == 82
    assert showcase._clean_vet_score(81.6, "include") == 82   # rounds, not floors
    assert showcase._clean_vet_score(140, "include") == 100
    assert showcase._clean_vet_score(-5, "include") == 0


def test_vet_score_unusable_input_is_none_not_zero():
    """None must stay distinguishable from a real 0 — the caller refuses to
    publish on NULL, and a 0 would look like a considered rejection."""
    for bad in (None, "", "high", [], {}, True, False):
        assert showcase._clean_vet_score(bad, "include") is None


def test_vet_score_capped_by_verdict():
    """v4-flash is documented to write dismissive words and attach a mid-range
    number (rns_llm._JSON_SCHEMA_BLOCK). The caps stop that publishing a story."""
    assert showcase._clean_vet_score(90, "exclude") == 40
    assert showcase._clean_vet_score(90, "caution") == 74
    # Below the cap is left alone, and an unknown/None verdict is not capped.
    assert showcase._clean_vet_score(20, "exclude") == 20
    assert showcase._clean_vet_score(90, None) == 90


def test_vet_score_capping_is_one_directional():
    """A pessimistic score under an optimistic verdict is NOT raised — holding
    a story back is the cheaper error."""
    assert showcase._clean_vet_score(10, "include") == 10


# ── vet full-text re-fetch ────────────────────────────────────────────────────
def test_vet_full_text_prefers_the_refetched_page():
    long_text = "A" * 50_000
    with patch("showcase_fwd.fetch_announcement_text", return_value=long_text):
        out = showcase._vet_full_text(_cand(body="short stored body"))
    assert out == long_text


def test_vet_full_text_falls_back_to_stored_body_on_fetch_failure():
    """A dead URL must degrade the input, never cost the row its vet call — a
    raised exception here would now silently drop a story."""
    with patch("showcase_fwd.fetch_announcement_text",
               side_effect=RuntimeError("timeout")):
        out = showcase._vet_full_text(_cand(body="stored body"))
    assert out == "stored body"


def test_vet_full_text_keeps_the_stub_message():
    with patch("showcase_fwd.fetch_announcement_text") as fetch:
        out = showcase._vet_full_text(_cand(body=None, body_is_stub=True))
    assert "body unavailable" in out
    fetch.assert_not_called()


def test_vet_full_text_head_tail_keeps_both_ends():
    """Head-only truncation would drop the reiterated-guidance and consensus
    language rns.py records as sitting ~85% through a long results document."""
    text = ("H" * showcase._VET_BODY_HEAD) + ("M" * 5000) + ("T" * showcase._VET_BODY_TAIL)
    with patch("showcase_fwd.fetch_announcement_text", return_value=text):
        out = showcase._vet_full_text(_cand(body="x"))
    assert out.startswith("H")
    assert out.endswith("T")
    assert "5000 chars omitted" in out


# ── forward multiple off the ranker's extraction (migration 032) ─────────────
def _fwd_profit(**kw):
    base = dict(found=True, metric="ebitda", value_low_m=20.0, value_high_m=None,
                currency="GBP", period_label="FY2026", period_months=12,
                source="guidance", relation="eq", quote="Adjusted EBITDA of £20m")
    base.update(kw)
    return base


def test_fwd_from_ranker_computes_the_multiple_with_no_call():
    """The whole point: the figure came out of the ranker's scoring response, so
    the multiple costs neither a DeepSeek call nor an Investegate fetch."""
    with patch("showcase_fwd._run_extraction") as run, \
         patch("showcase_fwd.fetch_announcement_text") as fetch:
        out = showcase_fwd.fwd_from_ranker(
            _cand(fwd_profit=_fwd_profit(), llm_model="deepseek-v4-flash:thinking")
        )
    run.assert_not_called()
    fetch.assert_not_called()
    # market_cap 200m, no net debt -> EV 200m / EBITDA 20m
    assert out["fwd_multiple"] == 10.0
    assert out["fwd_metric"] == "ebitda"
    assert out["fwd_basis"] == "guidance"
    assert out["fwd_value"] == 20_000_000
    # fwd_model records WHICH model produced the figure, and it is now the
    # ranker's rather than showcase_fwd's own constant.
    assert out["fwd_model"] == "deepseek-v4-flash:thinking"


def test_fwd_from_ranker_returns_none_without_an_extraction():
    """A row ranked before 032 shipped. None (not an all-None dict) is what
    tells the caller to leave fwd_processed_at NULL so the paid backfill can
    still pick it up."""
    assert showcase_fwd.fwd_from_ranker(_cand()) is None
    assert showcase_fwd.fwd_from_ranker(_cand(fwd_profit=None)) is None


def test_fwd_from_ranker_reads_a_json_string():
    out = showcase_fwd.fwd_from_ranker(
        _cand(fwd_profit=json.dumps(_fwd_profit()))
    )
    assert out["fwd_multiple"] == 10.0


def test_fwd_from_ranker_found_false_counts_as_processed():
    """"The ranker read it and nothing qualified" is finished work, not a gap.
    Stamping it stops the backfill route paying to ask the same question."""
    out = showcase_fwd.fwd_from_ranker(_cand(fwd_profit={"found": False}))
    assert out["fwd_multiple"] is None
    assert out["fwd_processed_at"] is not None


def test_fwd_from_ranker_still_applies_every_gate():
    """compute_fwd_multiple is reused verbatim, so the gates that guard the
    number did not move and are not re-implemented here."""
    usd = showcase_fwd.fwd_from_ranker(_cand(fwd_profit=_fwd_profit(currency="USD")))
    assert usd["fwd_multiple"] is None      # no FX, by design
    half = showcase_fwd.fwd_from_ranker(_cand(fwd_profit=_fwd_profit(period_months=6)))
    assert half["fwd_multiple"] is None     # H1 figure, not a full year
    bank = showcase_fwd.fwd_from_ranker(
        _cand(fwd_profit=_fwd_profit(), sector="Financial Services", industry="Banks")
    )
    assert bank["fwd_multiple"] is None     # EV is meaningless for a bank
    tiny = showcase_fwd.fwd_from_ranker(
        _cand(fwd_profit=_fwd_profit(value_low_m=0.5))
    )
    assert tiny["fwd_multiple"] is None     # 400x — outside the sanity band
    # ...but the extraction itself is still stored on every one of those, so a
    # blank column can always be explained against the quote.
    assert usd["fwd_quote"] and usd["fwd_currency"] == "USD"


@pytest.mark.parametrize("value_m, quote", [
    # The three live derivations caught on 2026-08-14, each a stated growth
    # rate multiplied into a stated base. Copying is the module's one hard rule
    # and this is the only enforcement of it that does not need the model's
    # cooperation — the prompt already forbade all three in as many words.
    (3654.0, "Underlying EBIT Increase in the range of 10% to 12% £3,322m"),
    (645.0, "Operating profit growth of c.42% ... consensus adjusted operating "
            "profit for FY26 is £454m"),
    (486.0, "a further c.7% upgrade to consensus ... consensus adjusted "
            "operating profit for FY26 is £454m"),
])
def test_fwd_rejects_a_figure_its_quote_does_not_contain(value_m, quote):
    out = showcase_fwd.fwd_from_ranker(_cand(
        fwd_profit=_fwd_profit(metric="ebit", value_low_m=value_m, quote=quote),
        market_cap=60_000_000_000,
    ))
    assert out["fwd_multiple"] is None
    # The extraction is still stored — a blank column has to be explainable.
    assert out["fwd_value"] == value_m * 1e6
    assert out["fwd_quote"]


def test_fwd_keeps_the_figure_the_same_quote_does_print():
    """The other half of the DPLM case: the £454m consensus figure printed in
    the footnote is a real stated number and must still pass, or the guard
    would just be blanking the announcements it was meant to read."""
    out = showcase_fwd.fwd_from_ranker(_cand(fwd_profit=_fwd_profit(
        metric="ebit", value_low_m=454.0, source="consensus",
        quote="Analyst consensus adjusted operating profit for FY26 is £454m, "
              "as at 15 July 2026. Operating profit growth of c.42%",
    ), market_cap=9_000_000_000))
    assert out["fwd_multiple"] == 19.82


def test_fwd_quote_check_matches_across_units():
    """The quote's units and the extraction's routinely differ, and a range
    carries its suffix only on the last member ("£4.7-4.9bn"). Rolls Royce is
    the live case: value_low_m 4700 against a quote saying 4.7bn."""
    assert showcase_fwd._quote_contains_value(
        "we now expect £4.7bn-£4.9bn underlying operating profit", 4700.0)
    assert showcase_fwd._quote_contains_value(
        "Analyst consensus adjusted operating profit for FY26 is £454m", 454.0)
    assert showcase_fwd._quote_contains_value("Underlying EBIT £3,322m", 3322.0)
    assert showcase_fwd._quote_contains_value("EBITDA of £15.0 million", 15.0)
    # ...and does not wave through a number that simply isn't there.
    assert not showcase_fwd._quote_contains_value(
        "Underlying EBIT up 10% to 12% on £3,322m", 3654.0)
    assert not showcase_fwd._quote_contains_value("", 40.0)


def test_fwd_quote_check_applies_to_the_legacy_extractor_too():
    """Both callers reach compute_fwd_multiple, so a derived figure is caught
    whichever call produced it."""
    out = showcase_fwd.compute_fwd_multiple(
        {"found": True, "metric": "ebitda", "value_low_m": 99.0, "currency": "GBP",
         "period_months": 12, "source": "guidance", "relation": "eq",
         "quote": "EBITDA margin of 20% on revenue of £495m"},
        _cand(), "m",
    )
    assert out["fwd_multiple"] is None


def test_fwd_from_ranker_marks_an_upper_bound():
    out = showcase_fwd.fwd_from_ranker(
        _cand(fwd_profit=_fwd_profit(relation="above", source="consensus"))
    )
    assert out["fwd_is_bound"] is True
    assert out["fwd_basis"] == "consensus"


def test_flag_computes_the_multiple_on_a_shadow_row():
    """THE ARCHIVE BUG. Between 5d6f7f5 and migration 032 the multiple ran only
    `if publish:`, so every row of /high-impact-rns/archive — which is nothing
    but shadow rows — showed a blank. Free extraction, so no reason to skip."""
    vet = {"verdict": "caution", "confidence": "medium", "rationale": "thin",
           "score": 64, "model": "deepseek-v4-flash:thinking", "low_base": None}
    cand = _cand(llm_score=65, fwd_profit=_fwd_profit())
    with patch.object(showcase, "_q", return_value=[cand]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        res = showcase.flag_high_impact_candidates()
    assert res["shadowed"] == 1
    params = ex.call_args[0][1]
    assert params[-1] == "shadow"
    assert params[23] == "ebitda"      # fwd_metric
    assert params[31] == 10.0          # fwd_multiple — the column that was blank
    assert params[33] is not None      # fwd_processed_at stamped


def test_flag_never_pays_for_a_second_extraction_call():
    """The reason the `if publish:` gate could be dropped. If this ever fails,
    the morning batch has quietly gone back to two LLM calls per candidate."""
    vet = {"verdict": "include", "confidence": "high", "rationale": "ok",
           "score": 85, "model": "m", "low_base": None}
    with patch.object(showcase, "_q", return_value=[_cand(fwd_profit=_fwd_profit())]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1), \
         patch("showcase_fwd.extract_fwd_fields") as extract:
        showcase.flag_high_impact_candidates()
    extract.assert_not_called()


def test_flag_leaves_a_pre_032_row_eligible_for_backfill():
    """No ranker extraction — the row must NOT be stamped, or the /extract-fwd
    backfill will skip it forever."""
    vet = {"verdict": "include", "confidence": "high", "rationale": "ok",
           "score": 85, "model": "m", "low_base": None}
    with patch.object(showcase, "_q", return_value=[_cand()]), \
         patch.object(showcase, "_story_close", return_value=1.0), \
         patch.object(showcase, "_vet_candidate", return_value=vet), \
         patch.object(gates, "record_low_base_evaluation"), \
         patch.object(showcase, "_exec", return_value=1) as ex:
        showcase.flag_high_impact_candidates()
    params = ex.call_args[0][1]
    assert params[31] is None          # fwd_multiple
    assert params[33] is None          # fwd_processed_at NULL -> still eligible


def test_candidate_sql_selects_the_ranker_extraction():
    with patch.object(showcase, "_q", return_value=[]) as q:
        showcase.flag_high_impact_candidates()
    sql = " ".join(q.call_args[0][0].split())
    assert "r.fwd_profit" in sql
    assert "r.llm_model" in sql


# ── reported numbers on the archive (Tier 1) ─────────────────────────────────
def test_reported_lines_passes_values_through_verbatim():
    """Values span money, percentages, pence per share and prose, so they are
    NOT normalised — a parser over that would be wrong often enough to mislead,
    and the announcement's own wording is the audit trail."""
    rows = [{"showcase_id": 7, "earnings_quality": [
        {"period": "H1 2026", "item": "Revenue", "value": "£89.0m",
         "prior_value": "£71.2m (implied from 25% growth)"},
        {"period": "H1 2026", "item": "InnovaMatrix revenue", "value": "down >90%",
         "prior_value": None},
    ]}]
    with patch.object(showcase, "_q", return_value=rows):
        out = showcase._reported_lines([{"id": 7}])
    assert out[7][0]["value"] == "£89.0m"
    assert out[7][1]["value"] == "down >90%"


def test_reported_lines_reads_jsonb_delivered_as_text():
    rows = [{"showcase_id": 7,
             "earnings_quality": json.dumps([{"item": "Revenue", "value": "£1m"}])}]
    with patch.object(showcase, "_q", return_value=rows):
        out = showcase._reported_lines([{"id": 7}])
    assert out[7][0]["item"] == "Revenue"


def test_reported_lines_skips_rows_with_nothing_extracted():
    for eq in (None, [], "not json"):
        with patch.object(showcase, "_q", return_value=[{"showcase_id": 7, "earnings_quality": eq}]):
            assert showcase._reported_lines([{"id": 7}]) == {}


def test_reported_net_debt_passes_the_company_figure_through():
    rows = [{"showcase_id": 7, "net_debt_reported": {
        "found": True, "value": "$3,966.1 million", "as_at": "30 June 2026",
        "prior_value": "$2,749.5 million", "prior_as_at": "31 December 2025",
        "leverage": "0.68x",
    }}]
    with patch.object(showcase, "_q", return_value=rows):
        out = showcase._reported_net_debt([{"id": 7}])
    assert out[7]["value"] == "$3,966.1 million"
    assert out[7]["prior_as_at"] == "31 December 2025"


def test_reported_net_debt_drops_the_negative_answer():
    """{"found": false} is a real stored answer — the ranker read the text and
    it printed no net-debt figure — but there is nothing to render, so the UI
    shows our own series alone rather than an empty comparison."""
    for nd in ({"found": False}, {"found": True, "value": ""}, None):
        with patch.object(showcase, "_q",
                          return_value=[{"showcase_id": 7, "net_debt_reported": nd}]):
            assert showcase._reported_net_debt([{"id": 7}]) == {}


def test_reported_net_debt_reads_jsonb_delivered_as_text():
    rows = [{"showcase_id": 7, "net_debt_reported":
             json.dumps({"found": True, "value": "net cash of £41.2m"})}]
    with patch.object(showcase, "_q", return_value=rows):
        out = showcase._reported_net_debt([{"id": 7}])
    # Net cash stays the company's wording, never a negative number.
    assert out[7]["value"] == "net cash of £41.2m"


def test_net_debt_series_computes_leverage_only_where_it_means_something():
    rows = [
        {"company_symbol": "A.L", "fiscal_year": 2024, "period_end_date": None,
         "net_debt": 100.0, "ebitda": 50.0},
        # Negative EBITDA makes the ratio meaningless rather than large — the
        # same call rns_llm._build_messages makes for its own leverage line.
        {"company_symbol": "A.L", "fiscal_year": 2025, "period_end_date": None,
         "net_debt": 100.0, "ebitda": -50.0},
        {"company_symbol": "A.L", "fiscal_year": 2026, "period_end_date": None,
         "net_debt": None, "ebitda": 50.0},
    ]
    with patch.object(showcase, "_q", return_value=rows):
        out = showcase._net_debt_series(["A.L"])
    assert out["A.L"][0]["net_debt_to_ebitda"] == 2.0
    assert out["A.L"][1]["net_debt_to_ebitda"] is None
    assert out["A.L"][2]["net_debt"] is None


def test_net_debt_series_keeps_net_cash_negative():
    """Net cash must stay a negative net_debt in the payload — the UI is what
    turns it into "net cash", exactly as _fmt_net_debt_m does server-side. A
    sign lost here inverts a leverage read."""
    rows = [{"company_symbol": "A.L", "fiscal_year": 2025, "period_end_date": None,
             "net_debt": -198.6, "ebitda": 50.0}]
    with patch.object(showcase, "_q", return_value=rows):
        out = showcase._net_debt_series(["A.L"])
    assert out["A.L"][0]["net_debt"] == -198.6


# ── sequential comparator on the archive ─────────────────────────────────────
# The defect this closes: ANTO.L 9719041's table showed H1'26 revenue $4,479.0m
# against the company's own $3,799.4m comparator (+18%) while the vet rationale
# on the same row said "about 7% below H2 2025's $4,820.9m". Both correct,
# different comparators, and nothing on the page said so.
_ANTO_EQ = [
    {"item": "Revenue", "kind": "income", "period": "H1 2026",
     "value": "$4,479.0m", "prior_value": "$3,799.4m", "one_off_named": None},
    {"item": "EBITDA", "kind": "income", "period": "H1 2026",
     "value": "$2,840.5m", "prior_value": "$2,234.2m", "one_off_named": None},
]


def test_sequential_summary_reproduces_the_figure_the_vet_quotes():
    """Same arithmetic the vet was handed as a fact, so the page cannot drift
    from the prompt: FY25 $8,620.3m - H1'25 $3,799.4m = H2'25 $4,820.9m, and
    $4,479.0m is 7.1% below it."""
    with patch.object(showcase, "_annual_history",
                      return_value=[{"revenue": 8_620_300_000.0}]):
        out = showcase._sequential_summary(
            [{"id": 7, "symbol": "ANTO.L"}], {7: _ANTO_EQ}, {}
        )
    assert out[7]["preceding_value"] == 4_820_900_000.0
    assert out[7]["delta_pct"] == -7.1
    assert out[7]["basis"] == "derived_from_fy_total"
    # The prior-year half stays available so the UI can show what was subtracted
    # from what, rather than asserting a derived number with no working.
    assert out[7]["prior_year_value"] == 3_799_400_000.0


def test_sequential_summary_names_the_half_the_ui_must_label():
    """The UI must not have to know that the half before H1 is H2."""
    with patch.object(showcase, "_annual_history",
                      return_value=[{"revenue": 8_620_300_000.0}]):
        out = showcase._sequential_summary(
            [{"id": 7, "symbol": "ANTO.L"}], {7: _ANTO_EQ}, {}
        )
    assert out[7]["period"] == "H1"
    assert out[7]["preceding_period"] == "H2"


def test_sequential_summary_is_silent_rather_than_guessing():
    """Absent from the map, never a partial entry — the archive renders nothing
    instead of a comparison it cannot establish."""
    # No revenue line at all.
    assert showcase._sequential_summary(
        [{"id": 7, "symbol": "A.L"}],
        {7: [{"item": "EBITDA", "period": "H1 2026", "value": "$1m",
              "prior_value": "$1m"}]},
        {},
    ) == {}
    # Nothing extracted for this entry.
    assert showcase._sequential_summary([{"id": 7, "symbol": "A.L"}], {}, {}) == {}
    # Revenue there, but no annual history to derive the preceding half from.
    with patch.object(showcase, "_annual_history", return_value=[]):
        assert showcase._sequential_summary(
            [{"id": 7, "symbol": "ANTO.L"}], {7: _ANTO_EQ}, {}
        ) == {}


def test_sequential_summary_silent_on_currency_mismatch():
    """HILS.L 9716717 (2026-08-14): FY2025 annual revenue was reported in GBP
    (£868.8m), then the company switched to USD for its H1 2026 interim
    ($606.7m / $561.1m). _sequential_summary builds its own stripped-down
    candidate dict — this locks in that it now threads financial_currency
    through from currency_by_symbol rather than omitting it, which is what
    let the archive page keep showing a GBP-minus-USD figure even after
    gates.compute_sequential_base itself was guarded."""
    hils_eq = [
        {"item": "Revenue", "kind": "income", "period": "H1 2026",
         "value": "$606.7m", "prior_value": "$561.1m", "one_off_named": None},
    ]
    with patch.object(showcase, "_annual_history",
                       return_value=[{"revenue": 868_800_000.0, "currency": "GBP"}]):
        out = showcase._sequential_summary(
            [{"id": 7, "symbol": "HILS.L"}],
            {7: hils_eq},
            {"HILS.L": "USD"},
        )
    assert out == {}


def test_archive_endpoint_asks_for_the_detail(client):
    with patch.object(showcase, "_q", return_value=[]), \
         patch.object(showcase, "_enrich", return_value=[]) as enrich:
        client.get("/api/showcase/shadow")
    assert enrich.call_args.kwargs.get("detail") is True


def test_public_showcase_pays_for_no_detail(client):
    """The public list is the hot, cached path and must not pay for two extra
    queries it never renders."""
    with patch.object(showcase, "_q", return_value=[]), \
         patch.object(showcase, "_enrich", return_value=[]) as enrich:
        client.get("/api/showcase")
    assert enrich.call_args.kwargs.get("detail") in (None, False)


def test_pending_endpoint_pays_for_no_detail(client):
    with patch.object(showcase, "_q", return_value=[]), \
         patch.object(showcase, "_enrich", return_value=[]) as enrich:
        client.get("/api/showcase/pending")
    assert enrich.call_args.kwargs.get("detail") in (None, False)


# ── price context (1m/6m) ─────────────────────────────────────────────────────
def test_price_context_renders_both_windows():
    with patch("rns_llm._load_price_change", return_value={"chg_1m": 0.221, "chg_6m": 0.141}):
        out = showcase._price_context("GRG.L")
    assert "1 month +22.1%" in out
    assert "6 months +14.1%" in out


def test_price_context_withheld_for_point_in_time_reruns():
    """rns_llm._load_price_change measures from CURRENT_DATE. In a backtest that
    is future data, so it must be withheld rather than silently leaked."""
    with patch("rns_llm._load_price_change") as load:
        out = showcase._price_context("GRG.L", before="2026-01-01")
    assert "look-ahead" in out
    load.assert_not_called()


def test_price_context_degrades_without_history():
    with patch("rns_llm._load_price_change", return_value={}):
        assert "no price history" in showcase._price_context("NEW.L")
    with patch("rns_llm._load_price_change", side_effect=RuntimeError("db down")):
        assert "no price history" in showcase._price_context("GRG.L")
    assert "no price history" in showcase._price_context(None)


def test_vet_prompt_carries_price_context_and_neutral_framing():
    user = showcase._vet_messages(_cand(), [], price_context="  1 month +22.1%, 6 months +14.1%")[1]["content"]
    assert "1 month +22.1%" in user
    assert "before this announcement" in user.lower()
    # The rubric must not tell the model that a strong prior run is bad — that
    # would be calibrating a direction on zero evidence.
    system = showcase._vet_messages(_cand(), [])[0]["content"]
    assert "context, not as a verdict in either direction" in system


# ── Reporting currency ────────────────────────────────────────────────────────
_USD_ANNUAL = [
    {"fiscal_year": 2024, "period_end_date": "2024-12-31",
     "revenue": 284_000_000_000, "operating_income": 30_000_000_000,
     "net_income": 16_000_000_000, "eps_diluted": 2.63,
     "fcf": 20_000_000_000, "net_debt": 5_000_000_000,
     "total_equity": 180_000_000_000},
]


def test_vet_prompt_renders_annuals_in_the_reporting_currency():
    """A dollar filer's series must not be labelled in pounds.

    annual_financials is denominated in company_metadata.financial_currency,
    which is USD for Shell/BP/AZN. Rendering it as "£284,000.0m" put a figure
    in front of the model that appears nowhere in the announcement it is being
    told to check the series against.
    """
    user = showcase._vet_messages(
        _cand(financial_currency="USD"), _USD_ANNUAL
    )[1]["content"]
    assert "revenue $284,000.0m" in user
    assert "£284,000.0m" not in user
    assert "net debt $5,000.0m" in user
    # EPS: the x100 pence conversion is a GBP convention. $2.63 is not 263.0p.
    assert "diluted EPS $2.63" in user
    assert "263.0p" not in user
    # The block states its own units, so the model can spot a mismatch against
    # an announcement that quotes something else.
    assert "reported in\nUSD ($)" in user


def test_vet_prompt_gbp_still_renders_pounds_and_pence():
    user = showcase._vet_messages(
        _cand(financial_currency="GBP"),
        [{"fiscal_year": 2024, "period_end_date": "2024-03-31",
          "revenue": 359_745_000, "eps_diluted": 0.167}],
    )[1]["content"]
    assert "revenue £359.7m" in user
    assert "diluted EPS 16.7p" in user


def test_vet_prompt_unmapped_currency_uses_the_bare_code():
    # "$" alone cannot separate USD from CAD/AUD, so anything outside the
    # symbol map must name itself.
    user = showcase._vet_messages(
        _cand(financial_currency="CAD"), _USD_ANNUAL
    )[1]["content"]
    assert "revenue CAD 284,000.0m" in user
    assert "$284,000.0m" not in user


def test_vet_prompt_missing_currency_is_labelled_an_assumption():
    # GBP is the right default for a UK-listed universe, but it is a guess and
    # the prompt says so rather than passing it off as fact.
    user = showcase._vet_messages(_cand(), _USD_ANNUAL)[1]["content"]
    assert "revenue £284,000.0m" in user
    assert "reporting currency not on file, assumed" in user


# ── Guidance context ──────────────────────────────────────────────────────────
_GUIDANCE = [
    {"metric": "Adjusted Operating Profit", "period": "FY2026",
     "guided_value": "> £40m", "consensus_value": "£44.1m",
     "vs_prior": "reiterated", "vs_consensus": "below"},
    {"metric": "Free cash flow", "period": "FY2027",
     "guided_value": "positive FCF", "consensus_value": None,
     "vs_prior": "new", "vs_consensus": "no_consensus_stated"},
]


def test_vet_prompt_carries_the_rankers_guidance_extraction():
    """The vet's first named job is catching a quiet guidance cut, and the
    ranker had already extracted the comparison it was re-deriving from text."""
    user = showcase._vet_messages(
        _cand(guidance_checks=_GUIDANCE), []
    )[1]["content"]
    assert "Adjusted Operating Profit (FY2026): guided > £40m" in user
    assert "vs prior guidance: reiterated; vs consensus: below" in user
    assert "consensus printed as £44.1m" in user
    # Every entry, not just the first — a second statement is where the catch
    # usually hides.
    assert "Free cash flow (FY2027)" in user
    # Framed as a checklist to verify, never as a finding to adopt: it is the
    # same model on the same document one pass earlier.
    assert "Not an independent source" in user


def test_vet_prompt_separates_no_guidance_from_no_extraction():
    # NULL means the ranker emitted nothing; [] means it read the announcement
    # and found no forward statement. Collapsing them would tell the model a
    # company guided nothing when in fact nobody looked.
    absent = showcase._vet_messages(_cand(guidance_checks=None), [])[1]["content"]
    assert "not extracted for this announcement" in absent
    empty = showcase._vet_messages(_cand(guidance_checks=[]), [])[1]["content"]
    assert "found no forward-looking statement" in empty


def test_vet_system_prompt_teaches_the_reiterated_below_combination():
    system = showcase._vet_messages(_cand(), [])[0]["content"]
    # The one combination the guidance gate exists for.
    assert "reiterated AND below a consensus" in system
    # And the trap in the other direction — most announcements print no
    # consensus footnote at all, which is not evidence of anything.
    assert "carries no information in either direction" in system


# ── Company size ──────────────────────────────────────────────────────────────
def test_vet_prompt_carries_market_cap():
    big = showcase._vet_messages(_cand(market_cap=1.61e9), [])[1]["content"]
    assert "Market cap £1.61bn" in big
    small = showcase._vet_messages(_cand(market_cap=62_500_000), [])[1]["content"]
    assert "Market cap £62.5m" in small
    none = showcase._vet_messages(_cand(market_cap=None), [])[1]["content"]
    assert "market cap not on file" in none


def test_market_cap_warns_when_it_and_the_accounts_differ_in_currency():
    """market_cap is in the QUOTE currency, annual_financials in the REPORTING
    currency. For HSBA that is GBP against USD — a ratio across the two is
    wrong by the FX rate with nothing in the output to reveal it."""
    usd = showcase._vet_messages(
        _cand(market_cap=270.26e9, currency="GBp", financial_currency="USD"), []
    )[1]["content"]
    assert "Market cap £270.26bn" in usd
    assert "market cap is in GBP, but the company reports its accounts in USD" in usd
    assert "Do not form a ratio across the two" in usd


def test_market_cap_stays_quiet_when_gbp_quote_meets_gbp_accounts():
    # "GBp" and "GBP" are the same currency — the stored cap is in pounds, not
    # pence (verified against GRG's own share count). A warning here would be
    # noise on ~99% of the universe.
    gbp = showcase._vet_messages(
        _cand(market_cap=1.61e9, currency="GBp", financial_currency="GBP"), []
    )[1]["content"]
    assert "Market cap £1.61bn" in gbp
    assert "DIFFERENT currency" not in gbp
    # Unknown reporting currency must not warn either — nothing is known to differ.
    unknown = showcase._vet_messages(
        _cand(market_cap=1.61e9, currency="GBp", financial_currency=None), []
    )[1]["content"]
    assert "DIFFERENT currency" not in unknown


# ── Score bands ───────────────────────────────────────────────────────────────
def test_vet_prompt_score_bands_agree_with_the_publish_floor():
    """The bands must not straddle HIGH_IMPACT_MIN_VET_SCORE.

    Regression on a real contradiction: the system prompt called 60-79
    "positive but carrying a catch a reader must be told" while the JSON block
    called 75+ "you found nothing a reader would need warning about". 75 is the
    publish floor, so the one boundary that decides publication was described
    two incompatible ways.
    """
    msgs = showcase._vet_messages(_cand(), [])
    system, user = msgs[0]["content"], msgs[1]["content"]
    pub = showcase.HIGH_IMPACT_MIN_VET_SCORE
    ex_cap = showcase._VET_VERDICT_SCORE_CAP["exclude"]
    ca_cap = showcase._VET_VERDICT_SCORE_CAP["caution"]

    # Bands are contiguous and derived from the thresholds they must match.
    assert f"{pub} and above means" in system
    assert f"60-{pub - 1} means positive but carrying a catch" in system
    assert f"{ex_cap + 1}-59 means unproven" in system
    assert f"{ex_cap} and below means" in system
    # The JSON block describes the same boundary the same way.
    assert f"A score of {pub}+ asserts you found no" in user
    assert f"60-{pub - 1} is\n              the band for a positive case that DOES carry" in user
    # The old wording, in either passage, is the bug.
    assert "80+" not in system
    assert "60-79" not in system and "60-79" not in user

    # A 'caution' can never reach the publish floor — the caps and the floor
    # are one system, so if that ceases to hold the prompt above is misleading
    # about what the verdict costs.
    assert ca_cap < pub
    assert ex_cap < pub
    # Prompt caps and the Python enforcement are the same numbers.
    assert f"cannot carry a score above {ex_cap}" in system
    assert f"a 'caution' cannot exceed {ca_cap}" in system
    assert f"exclude <= {ex_cap}" in user and f"caution <= {ca_cap}" in user
