"""Announcement body + prior-guidance context in the ranker prompt
(rns_llm._build_messages), and the guidance capture/lookup helpers.

See docs/rns-body-context-plan.md — motivated by LUCE/BARC both scoring 75 on
2026-07-28 while the ranker and vet had only ever seen the third-party AI
summary, never the RNS body itself.
"""

import sys, os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rns_llm


def _cand(**overrides) -> dict:
    cand = {
        "ticker": "TST",
        "company_name": "Test plc",
        "headline": "Trading Statement",
        "category": "trading_update",
        "tier": "A",
        "market_cap": 500_000_000,
        "published_at": datetime(2026, 7, 9, 6, 0, tzinfo=timezone.utc),
    }
    cand.update(overrides)
    return cand


def _user_prompt(cand=None, history=None, price=None, prior_guidance=None) -> str:
    msgs = rns_llm._build_messages(cand or _cand(), history or [], price or {}, prior_guidance)
    return msgs[1]["content"]


def _system_prompt(cand=None) -> str:
    """The system message — which since the Phase 0 move
    (docs/rns-earnings-quality-plan.md) also carries the whole output schema.
    Tests that assert on field descriptions read this, not the user message."""
    return rns_llm._build_messages(cand or _cand(), [], {})[0]["content"]


# ── body section ───────────────────────────────────────────────────────────────

def test_body_included_as_primary_source():
    user = _user_prompt(_cand(body="The full RNS text goes here."))
    assert "The full RNS text goes here." in user
    assert "primary source" in user


def test_body_missing_shows_not_available():
    user = _user_prompt(_cand(body=None))
    assert "Announcement text (verbatim, may be truncated)" in user
    assert "(not available)" in user


def test_stub_body_says_unavailable_external_document():
    user = _user_prompt(_cand(body="short", body_is_stub=True))
    assert "links to an external document" in user
    assert "short" not in user.split("Announcement text")[1].split("Prior guidance")[0]


# ── prior guidance section ──────────────────────────────────────────────────────

def test_no_prior_guidance_states_none_captured():
    user = _user_prompt(prior_guidance=None)
    assert "(none captured yet for this issuer)" in user


def test_prior_guidance_rendered_with_date_metric_value():
    prior = {
        "published_at": datetime(2026, 5, 19, tzinfo=timezone.utc),
        "guidance_metric": "FY2026 Adjusted Operating Profit",
        "guidance_value": "> £40m",
        "guidance_period": "FY2026",
    }
    user = _user_prompt(prior_guidance=prior)
    assert "2026-05-19" in user
    assert "FY2026 Adjusted Operating Profit" in user
    assert "> £40m" in user


def test_json_schema_requests_guidance_fields():
    system = _system_prompt()
    assert "guidance_metric" in system
    assert "guidance_value" in system
    assert "guidance_period" in system


def test_system_prompt_has_consensus_and_reiteration_clause():
    msgs = rns_llm._build_messages(_cand(), [], {})
    system = msgs[0]["content"]
    assert "reiterated guidance" in system
    assert "not an upgrade" in system


# ── guidance_checks output contract ──────────────────────────────────────────────
# The LUCE regression (75 -> 85 with the body attached) was an adjudication
# failure, not a retrieval one: the model read a reiterated FY26 figure and a
# new FY27 comment out of one paragraph and scored off the louder of the two.
# The fix is an output contract that makes it enumerate both first.

def test_json_schema_requests_guidance_checks_with_all_entry_fields():
    system = _system_prompt()
    assert "guidance_checks" in system
    for field in (
        "metric", "period", "guided_value", "consensus_value",
        "vs_prior", "vs_consensus",
    ):
        assert field in system


def test_guidance_checks_separates_prior_and_consensus_axes():
    # These were one enum initially. A figure can be reiterated AND below
    # consensus at once (LUCE's FY26 >£40m against £40.7m); collapsing them
    # into one field made the model pick one and silently drop the other,
    # which flipped LUCE's score run to run.
    system = _system_prompt()
    for v in ("raised", "reiterated", "lowered", "new", "unknown"):
        assert v in system
    for v in ("above", "in_line", "below", "no_consensus_stated"):
        assert v in system
    assert "INDEPENDENT" in system


def test_scoring_rules_cover_both_failure_combinations():
    system = _system_prompt()
    # LUCE: unchanged guide that consensus has overtaken must read negative.
    assert "reiterated + below consensus is a NEGATIVE" in system
    # ULVR: a stated upgrade with no consensus footnote is still a catalyst.
    assert "raised + no_consensus_stated is still a genuine" in system


def test_guidance_checks_precedes_score_in_the_output_schema():
    # Generation order is the whole mechanism — enumerating after the score
    # would let the model rationalise a number it had already chosen.
    schema = _system_prompt().split("Produce a JSON object")[1]
    assert schema.index("guidance_checks") < schema.index("score")


def test_schema_asks_for_every_period_not_just_the_prominent_one():
    assert "every period" in _system_prompt().lower()


def test_system_prompt_warns_against_the_loudest_statement_winning():
    msgs = rns_llm._build_messages(_cand(), [], {})
    system = msgs[0]["content"]
    assert "guidance_checks" in system
    assert "before you choose a score" in system


# ── Phase 0: the schema block lives in the system message ────────────────────────
# docs/rns-earnings-quality-plan.md Phase 0. DeepSeek's cache is prefix-based,
# so the ~4.9k schema block — byte-identical on every row — was billed at the
# cache-miss rate every call while it sat after ~14k chars of per-row body.
# Moving it lifts the cacheable prefix from 15% to ~36% of the prompt.

def test_schema_block_is_in_the_system_message_not_the_user_message():
    system, user = _system_prompt(), _user_prompt()
    assert "Produce a JSON object with these fields exactly" in system
    # Duplicating it would defeat the point: the user copy would still be
    # uncacheable, and the model would read the schema twice.
    assert "Produce a JSON object with these fields exactly" not in user


def test_user_message_still_ends_with_the_ordering_pointer():
    # The bulk moved into cache, but the ONE load-bearing instruction — fill
    # the enumerated fields in before the score — is restated at the tail, so
    # it is still the last thing read after ~14k chars of body. Everything this
    # project has measured says the model holds an instruction poorly across a
    # long body; this is the mitigation, not decoration.
    user = _user_prompt().rstrip()
    assert user.endswith(rns_llm._SCHEMA_POINTER)
    assert "guidance_checks and earnings_quality FIRST" in user
    assert "do not pick a score and then justify it" in user


def test_user_message_prefix_is_the_row_context_not_the_schema():
    # Guards the ordering the cache depends on: anything stable must precede
    # anything per-row, and the user message must start with per-row content.
    assert _user_prompt().startswith("Announcement\n")


# ── earnings_quality output contract ─────────────────────────────────────────────
# The BARC 2026-07-28 case, which guidance_checks cannot reach: guidance really
# was raised, so no guidance label disqualifies, while "USCB income increased
# 38%" was partly a c.£225m disposal gain and the loan loss rate had gone
# 52 -> 62bps. Over 7 runs the model named the £225m gain 0/7 times and put
# rising impairments in `risks` 1/7 — it could see the facts and had nowhere to
# put them. An enumerated field gets filled in; a free sentence gets improvised.

def _earnings_quality_schema() -> str:
    """Just the earnings_quality field description, so assertions can't be
    satisfied by wording that happens to appear elsewhere in the prompt."""
    return _system_prompt().split("  earnings_quality array")[1].split("  score ")[0]


def test_json_schema_requests_earnings_quality_with_all_entry_fields():
    system = _system_prompt()
    assert "earnings_quality" in system
    for field in ("item", "period", "value", "prior_value", "kind", "one_off_named"):
        assert field in system


def test_earnings_quality_precedes_score_in_the_output_schema():
    schema = _system_prompt().split("Produce a JSON object")[1]
    assert schema.index("earnings_quality") < schema.index("score")


def test_earnings_quality_asks_for_a_quote_not_a_recurring_boolean():
    # A recurring yes/no is defensible either way on structural hedge income
    # and on IB income, so the model flips run to run — the same instability
    # that splitting verdict into vs_prior/vs_consensus fixed for guidance.
    # Copying the company's own clause is stable, as guided_value is.
    block = _earnings_quality_schema()
    assert "quoted as printed" in block
    assert "do not judge for yourself" in block
    assert "recurring" not in block.lower()


def test_earnings_quality_asks_for_rate_lines_separately():
    # Measured, not assumed. On the first BARC validation run the model
    # enumerated the impairment charge in £bn ("£1.4bn vs £1.1bn") on every
    # successful sample and the loan loss rate (62 vs 52bps) on none of them —
    # so _worsening_loss_rate, which ignores the absolute charge by design,
    # had nothing to fire on. The gate can only adjudicate a line the model
    # actually enumerates.
    block = _earnings_quality_schema()
    assert "RATES COUNT AS LINES" in block
    assert "its OWN entry" in block
    assert "Never emit only the absolute one" in block


def test_earnings_quality_is_bounded_and_ranks_what_to_keep():
    # The rate clause made enumeration exhaustive everywhere, not just on
    # banks: BOY went 2-5 entries to 5-22, INCH 2-8 to 5-13, and one INCH
    # sample burned the whole 8,000-token completion budget and was lost to a
    # truncated JSON. The bound protects the two things the gates actually
    # read — the named one-off and the rate pair — by ranking them above
    # routine detail rather than by trimming blindly.
    block = _earnings_quality_schema()
    assert "at most about 8 entries" in block
    assert "named one-off" in block
    assert "normalised rate that has a prior comparator" in block


def test_earnings_quality_period_is_mandatory():
    # The body prints H1 and Q2 impairments a few hundred chars apart; without
    # a period Python would compare a half-year against a quarter.
    block = _earnings_quality_schema()
    assert "Mandatory" in block
    assert "never merge two" in block


def test_score_guidance_covers_one_offs_and_rising_charge_rates():
    system = _system_prompt()
    assert "one-off contributor is worth less than its headline rate" in system
    assert "rising year on year is a negative" in system


# ── _clean_earnings_quality ──────────────────────────────────────────────────────

def test_clean_earnings_quality_normalises_a_full_entry():
    out = rns_llm._clean_earnings_quality([
        {"item": " Credit impairment charges ", "period": "H1 2026",
         "value": "£1.4bn", "prior_value": "£1.1bn", "kind": "Cost_Or_Charge",
         "one_off_named": "£0.2bn single name charge in the IB"},
    ])
    assert out == [{
        "item": "Credit impairment charges", "period": "H1 2026",
        "value": "£1.4bn", "prior_value": "£1.1bn", "kind": "cost_or_charge",
        "one_off_named": "£0.2bn single name charge in the IB",
    }]


def test_clean_earnings_quality_unknown_kind_falls_back_to_unclear():
    # showcase's gate matches kind == "cost_or_charge" exactly, so an invented
    # label must land somewhere the gate never fires: a parsing miss has to
    # fail open, never silently block a tradeable announcement.
    out = rns_llm._clean_earnings_quality([
        {"item": "Structural hedge income", "kind": "revenue"},
    ])
    assert out[0]["kind"] == "unclear"
    assert out[0]["period"] is None
    assert out[0]["one_off_named"] is None


def test_clean_earnings_quality_drops_entries_with_no_item():
    out = rns_llm._clean_earnings_quality([
        {"item": "", "value": "£1.4bn", "kind": "cost_or_charge"},
        {"item": "Loan loss rate", "value": "62bps", "prior_value": "52bps",
         "kind": "cost_or_charge", "period": "H1 2026"},
    ])
    assert [e["item"] for e in out] == ["Loan loss rate"]


def test_clean_earnings_quality_returns_none_when_unusable():
    for raw in (None, [], "not a list", {"not": "a list"}, ["not a dict"],
                [{"value": "£1.4bn"}]):
        assert rns_llm._clean_earnings_quality(raw) is None


def test_save_ranking_persists_earnings_quality_as_json():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(
            1,
            {"score": 75, "sentiment": "positive",
             "earnings_quality": [
                 {"item": "Loan loss rate", "period": "H1 2026",
                  "value": "62bps", "prior_value": "52bps",
                  "kind": "cost_or_charge", "one_off_named": None},
             ]},
            "deepseek-v4-flash:thinking",
        )
    params = cur.execute.call_args[0][1]
    assert params[11].adapted == [{
        "item": "Loan loss rate", "period": "H1 2026",
        "value": "62bps", "prior_value": "52bps",
        "kind": "cost_or_charge", "one_off_named": None,
    }]


def test_save_ranking_stores_null_when_no_earnings_quality():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(1, {"score": 60, "sentiment": "neutral"}, "m")
    assert cur.execute.call_args[0][1][11] is None


# ── history window ──────────────────────────────────────────────────────────────

def test_history_label_says_120_days():
    user = _user_prompt()
    assert "last 120 days" in user


def test_load_history_queries_120_day_window():
    with patch("rns_llm._query") as mock_query:
        mock_query.return_value = []
        rns_llm._load_history("TST.L")
    sql = mock_query.call_args[0][0]
    assert "120 days" in sql
    assert "60 days" not in sql


# ── _load_prior_guidance ─────────────────────────────────────────────────────────

def test_load_prior_guidance_no_symbol_returns_none():
    assert rns_llm._load_prior_guidance(None) is None


def test_load_prior_guidance_returns_most_recent_row():
    row = {
        "published_at": datetime(2026, 5, 19, tzinfo=timezone.utc),
        "guidance_metric": "FY2026 Adjusted Operating Profit",
        "guidance_value": "> £40m",
        "guidance_period": "FY2026",
    }
    with patch("rns_llm._query", return_value=[row]) as mock_query:
        result = rns_llm._load_prior_guidance("LUCE.L", exclude_id=9689898)
    assert result == row
    args = mock_query.call_args[0][1]
    assert args == ("LUCE.L", 9689898)


def test_load_prior_guidance_none_when_no_rows():
    with patch("rns_llm._query", return_value=[]):
        assert rns_llm._load_prior_guidance("LUCE.L", exclude_id=1) is None


# ── _save_ranking guidance persistence ───────────────────────────────────────────

def test_save_ranking_stores_guidance_when_both_present():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(
            1,
            {
                "score": 60, "sentiment": "neutral",
                "guidance_metric": "FY2026 Adjusted Operating Profit",
                "guidance_value": "> £40m",
                "guidance_period": "FY2026",
            },
            "deepseek-v4-flash:thinking",
        )
    params = cur.execute.call_args[0][1]
    assert params[7:10] == ("FY2026 Adjusted Operating Profit", "> £40m", "FY2026")


def test_save_ranking_drops_half_filled_guidance():
    # A metric without a value (or vice versa) isn't a usable data point for
    # the next announcement's comparison.
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(
            1,
            {"score": 60, "sentiment": "neutral", "guidance_metric": "FY2026 Profit"},
            "deepseek-v4-flash:thinking",
        )
    params = cur.execute.call_args[0][1]
    assert params[7:10] == (None, None, None)


# ── _clean_guidance_checks ───────────────────────────────────────────────────────

def test_clean_guidance_checks_normalises_a_full_entry():
    out = rns_llm._clean_guidance_checks([
        {"metric": " Adjusted Operating Profit ", "period": "FY2026",
         "guided_value": "> £40m", "consensus_value": "£40.7m",
         "vs_prior": "Reiterated", "vs_consensus": "BELOW"},
    ])
    assert out == [{
        "metric": "Adjusted Operating Profit", "period": "FY2026",
        "guided_value": "> £40m", "consensus_value": "£40.7m",
        "vs_prior": "reiterated", "vs_consensus": "below",
    }]


def test_clean_guidance_checks_falls_back_on_invented_labels():
    # showcase's gate matches exact values, so an unrecognised label must land
    # on a value that fails safe rather than being stored verbatim.
    out = rns_llm._clean_guidance_checks([
        {"metric": "X", "vs_prior": "slightly better", "vs_consensus": "beat"},
    ])
    assert out[0]["vs_prior"] == "unknown"
    assert out[0]["vs_consensus"] == "no_consensus_stated"


def test_clean_guidance_checks_returns_none_when_unusable():
    # None, not [] — "no guidance in this announcement" and "the model didn't
    # answer" must not be conflated in the stored column.
    for raw in (None, [], "not a list", {"not": "a list"}, ["not a dict"]):
        assert rns_llm._clean_guidance_checks(raw) is None


def test_save_ranking_persists_guidance_checks_as_json():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(
            1,
            {
                "score": 60, "sentiment": "neutral",
                "guidance_checks": [
                    {"metric": "Adjusted Operating Profit", "period": "FY2026",
                     "guided_value": "> £40m", "consensus_value": "£40.7m",
                     "vs_prior": "reiterated", "vs_consensus": "below"},
                ],
                "guidance_metric": "FY2026 Adjusted Operating Profit",
                "guidance_value": "> £40m",
                "guidance_period": "FY2026",
            },
            "deepseek-v4-flash:thinking",
        )
    params = cur.execute.call_args[0][1]
    assert params[7:10] == ("FY2026 Adjusted Operating Profit", "> £40m", "FY2026")
    checks = params[10]
    assert checks.adapted == [{
        "metric": "Adjusted Operating Profit", "period": "FY2026",
        "guided_value": "> £40m", "consensus_value": "£40.7m",
        "vs_prior": "reiterated", "vs_consensus": "below",
    }]


def test_save_ranking_stores_null_when_no_guidance_checks():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(1, {"score": 60, "sentiment": "neutral"}, "m")
    assert cur.execute.call_args[0][1][10] is None


def test_save_ranking_no_guidance_stores_nulls():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(1, {"score": 60, "sentiment": "neutral"}, "m")
    params = cur.execute.call_args[0][1]
    # positions 7-9 are guidance_metric/guidance_value/guidance_period
    assert params[7:10] == (None, None, None)


# ── _clean_fwd_profit (migration 032) ────────────────────────────────────────

def test_clean_fwd_profit_normalises_a_full_extraction():
    out = rns_llm._clean_fwd_profit({
        "found": True, "metric": "EBITDA", "value_low_m": 45, "value_high_m": 48,
        "currency": " gbp ", "period_label": "FY2026", "period_months": 12,
        "source": "Guidance", "relation": "MIN", "quote": " at least £45m ",
    })
    assert out == {
        "found": True, "metric": "ebitda", "value_low_m": 45.0,
        "value_high_m": 48.0, "currency": "GBP", "period_label": "FY2026",
        "period_months": 12, "source": "guidance", "relation": "min",
        "quote": "at least £45m",
    }


def test_clean_fwd_profit_keeps_a_negative_answer():
    # {"found": false} is a real, useful answer — the ranker read the text and
    # nothing qualified. It must NOT collapse to NULL, which showcase reads as
    # "never extracted" and re-queues for the paid backfill.
    assert rns_llm._clean_fwd_profit({"found": False}) == {"found": False}


def test_clean_fwd_profit_discards_fields_contradicting_found_false():
    out = rns_llm._clean_fwd_profit(
        {"found": False, "metric": "ebitda", "value_low_m": 45}
    )
    assert out == {"found": False}


def test_clean_fwd_profit_blanks_unrecognised_metric_and_source():
    # Unlike vs_prior/vs_consensus these do NOT fail open: compute_fwd_multiple
    # refuses a metric or basis it doesn't know, and a blank multiple beats a
    # wrong one on a public page.
    out = rns_llm._clean_fwd_profit({
        "found": True, "metric": "operating profit", "source": "broker note",
        "value_low_m": 10, "currency": "GBP", "period_months": 12,
    })
    assert out["metric"] is None
    assert out["source"] is None


def test_clean_fwd_profit_defaults_relation_to_eq():
    # relation only controls the "<" upper-bound prefix, never whether the
    # number is computed, so an absent one must not blank the multiple.
    out = rns_llm._clean_fwd_profit({"found": True, "metric": "pbt"})
    assert out["relation"] == "eq"


def test_clean_fwd_profit_coerces_junk_numbers_to_none():
    out = rns_llm._clean_fwd_profit({
        "found": True, "value_low_m": "not a number",
        "value_high_m": float("nan"), "period_months": "twelve",
    })
    assert out["value_low_m"] is None
    assert out["value_high_m"] is None
    assert out["period_months"] is None


def test_clean_fwd_profit_returns_none_when_unusable():
    # None, not {"found": False} — "nothing was stated" and "this row predates
    # the field" drive different behaviour in showcase.
    for raw in (None, [], "not a dict", 42):
        assert rns_llm._clean_fwd_profit(raw) is None


def test_save_ranking_persists_fwd_profit_as_json():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(
            1,
            {
                "score": 60, "sentiment": "neutral",
                "fwd_profit": {
                    "found": True, "metric": "ebitda", "value_low_m": 45,
                    "currency": "GBP", "period_label": "FY2026",
                    "period_months": 12, "source": "guidance", "relation": "eq",
                    "quote": "EBITDA of £45m",
                },
            },
            "deepseek-v4-flash:thinking",
        )
    fwd = cur.execute.call_args[0][1][12]
    assert fwd.adapted["metric"] == "ebitda"
    assert fwd.adapted["value_low_m"] == 45.0


def test_save_ranking_stores_null_when_no_fwd_profit():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(1, {"score": 60, "sentiment": "neutral"}, "m")
    assert cur.execute.call_args[0][1][12] is None


def test_prompt_forbids_deriving_the_fwd_figure():
    # The one safety property of this field: it copies, it never computes. A
    # derived profit would put an invented number on the public page.
    assert "fwd_profit" in rns_llm._JSON_SCHEMA_BLOCK
    assert "COPY ONLY" in rns_llm._JSON_SCHEMA_BLOCK


# ── _clean_net_debt_reported (migration 033) ─────────────────────────────────
# ANTO.L 9719041 is the row that motivated the column: its HY26 statement prints
# net debt of $3,966.1m at 30 June 2026 against 31 Dec 2025's $2,749.5m, while
# our own annual_financials series says $4,194.8m for that same date.
_ANTO_QUOTE = (
    "Net debt at the end of the period was $3,966.1 million (31 December 2025: "
    "$2,749.5 million), reflecting a balance of strong cash flows, capital "
    "expenditures, payment of dividends"
)


def test_clean_net_debt_reported_keeps_the_figures_verbatim():
    out = rns_llm._clean_net_debt_reported({
        "found": True,
        "value": "$3,966.1 million", "as_at": "30 June 2026",
        "prior_value": "$2,749.5 million", "prior_as_at": "31 December 2025",
        "leverage": "0.68x", "prior_leverage": "0.53x",
        "quote": _ANTO_QUOTE,
    })
    assert out["value"] == "$3,966.1 million"
    assert out["prior_as_at"] == "31 December 2025"
    assert out["leverage"] == "0.68x"


def test_clean_net_debt_reported_drops_a_value_absent_from_its_quote():
    """The guard that matters. fwd_profit's measured failure was the model
    computing a figure and presenting it as stated, and prompt wording alone did
    not stop it. A fabricated *reported* net debt is worse than a blank here,
    because the whole point of the column is to contradict our own number."""
    out = rns_llm._clean_net_debt_reported({
        "found": True,
        # borrowings 7,659.4 - cash 2,716.5, i.e. exactly what a model that
        # computed it instead of copying it would return. Appears nowhere in
        # the sentence it claims to come from.
        "value": "$4,942.9 million",
        "quote": _ANTO_QUOTE,
    })
    assert out == {"found": False}


@pytest.mark.parametrize("value,quote", [
    # Same figure, three printed scales — all measured on live rows. A literal
    # string compare rejected the last two.
    ("$3,966.1m", "Net debt at the end of the period was $3,966.1 million"),
    # Narrative in thousands, quote a table row headed in thousands.
    ("$68,709 thousand", "Net debt (3) 68,709 63,887 8"),
    # Narrative in units, quote a £000s column.
    ("£5,054,000 net cash", "(Net debt)/cash (18,464) 23,518 - 5,054"),
])
def test_clean_net_debt_reported_matches_across_printed_scales(value, quote):
    """Announcements print the same number several ways in one document, and
    rejecting the table-row forms threw away 6 of the first 24 measured runs
    while letting nothing extra through."""
    assert rns_llm._clean_net_debt_reported(
        {"found": True, "value": value, "quote": quote}
    )["found"] is True


@pytest.mark.parametrize("value", ["4.3 times", "3.7x", "net leverage of 4.3x"])
def test_clean_net_debt_reported_refuses_a_leverage_ratio(value):
    """DP World's HY26 prints leverage and no absolute net debt; the model
    answered "4.3 times" on two runs and "3.7x" on a third — pre- and
    post-IFRS16, i.e. not even the same quantity. A money field must hold
    money."""
    assert rns_llm._clean_net_debt_reported({
        "found": True, "value": value,
        "quote": f"net debt to adjusted EBITDA stands at {value}",
    }) == {"found": False}


def test_clean_net_debt_reported_requires_a_quote_at_all():
    # No quote is a failed guard, not a pass — there is nothing to check against.
    assert rns_llm._clean_net_debt_reported(
        {"found": True, "value": "$3,966.1 million"}
    ) == {"found": False}


def test_clean_net_debt_reported_rejects_a_gross_cash_balance():
    """FOUR.L 9704828, live on 2026-08-14: the model answered net_debt_reported
    with "Cash and bank deposits 136.9 102.3 +34%" — a gross balance the
    announcement never called net of anything (4imprint never uses the words
    "net debt" or "net cash" anywhere in the release). The mantissa guard alone
    passed this, because $136.9m genuinely is the number printed; only a check
    for the word "net" catches it."""
    assert rns_llm._clean_net_debt_reported({
        "found": True, "value": "$136.9m",
        "quote": "Cash and bank deposits 136.9 102.3 +34%",
    }) == {"found": False}


def test_clean_net_debt_reported_rejects_a_dropped_cash_qualifier():
    """BBY.L 9716718, live on 2026-08-14: the model correctly copied the
    number (1,708 appears verbatim in the quote) but dropped the word "cash"
    from a table row headed "Net cash - recourse", storing "£1,708m" — which,
    shown with no computed sign on the page, reads as debt when Balfour Beatty
    is genuinely net CASH £1,708m."""
    assert rns_llm._clean_net_debt_reported({
        "found": True, "value": "£1,708m",
        "quote": "Net cash - recourse 3 1,708 1,446 1,237",
    }) == {"found": False}


def test_clean_net_debt_reported_accepts_the_qualifier_when_present():
    """The fix for the case above: same row, value corrected to carry the word
    the table's own header used."""
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "net cash of £1,708m",
        "quote": "Net cash - recourse 3 1,708 1,446 1,237",
    })
    assert out["found"] is True
    assert out["value"] == "net cash of £1,708m"


def test_clean_net_debt_reported_does_not_require_cash_wording_on_a_dual_header():
    """PSN.L 9707275's own convention: "Net (debt)/cash" with the sign already
    encoded in value's own parentheses ("£(165.0)m"). The pure-net-cash check
    must not fire here — it isn't a plain "net cash" label, it's a dual
    debt/cash toggle header, and the parenthetical already carries the sign."""
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£(165.0)m",
        "quote": "Net (debt)/cash at 30 June £(165.0)m £123.0m £(288.0)m",
    })
    assert out["found"] is True


def test_clean_net_debt_reported_keeps_net_cash_wording():
    """Never converted to a negative — read backwards a sign flip reverses a
    leverage judgement, the same reason showcase._fmt_net_debt_m exists."""
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "net cash of £41.2m",
        "quote": "The Group ended the period with net cash of £41.2m",
    })
    assert out["value"] == "net cash of £41.2m"


def test_clean_net_debt_reported_accepts_a_bracket_meaning_debt_not_cash():
    """HILS.L 9716717's own net-debt bridge: "Net debt (170.9)" — checked by
    hand against the surrounding note (cash 83.4 minus borrowings and lease
    liabilities of 254.3 = -170.9), the bracket here means the FUNDS position
    is negative, i.e. this genuinely is net debt of £170.9m, not net cash. A
    bare "$170.9m" is the right answer for this one; the net-cash-wording check
    must not fire on it, because the quote's label is "Net debt", not "net
    cash"."""
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "$170.9m",
        "quote": "Net debt at the end of the period (170.9)",
    })
    assert out["found"] is True
    assert out["value"] == "$170.9m"


def test_clean_net_debt_reported_keeps_a_negative_answer():
    # Most RNS print no net-debt figure; that is a completed extraction, not a
    # missing one, and NULL is reserved for rows ranked before the column.
    assert rns_llm._clean_net_debt_reported({"found": False}) == {"found": False}
    for raw in (None, [], "not a dict", 42):
        assert rns_llm._clean_net_debt_reported(raw) is None


# ── net_debt_reported breakdown (the reconciliation bridge) ──────────────────
# RNK.L 9719084's own note 11, verbatim — the worked example in the prompt.
# TWO separate quotes on purpose: `quote` is the headline "Net debt £X" line,
# `breakdown_quote` is the note underneath it. The first live run against this
# exact row got the bridge exactly right but stored it under one shared quote
# field, which the model never widened to cover the note — so every row failed
# the mantissa check against text that never contained it. Splitting the field
# fixed it on the very next run with no other change; see
# rns_llm._clean_net_debt_breakdown's docstring.
_RNK_HEADLINE_QUOTE = "Net debt £147.2m £154.7m (5)%"
_RNK_BREAKDOWN_QUOTE = (
    "Total loans and borrowings (30.0) (30.2) Adjusted for: Accrued interest "
    "- 0.2 (30.0) (30.0) Cash and short-term deposits 86.8 75.4 Net debt "
    "excluding IFRS 16 lease liabilities 56.8 45.4 IFRS 16 lease liabilities "
    "(204.0) (200.1) Net debt (147.2) (154.7)"
)
_RNK_BRIDGE_ROWS = [
    {"label": "Total loans and borrowings", "value": "(30.0)", "prior_value": "(30.2)"},
    {"label": "Cash and short-term deposits", "value": "86.8", "prior_value": "75.4"},
    {"label": "Net debt excluding IFRS 16 lease liabilities", "value": "56.8", "prior_value": "45.4"},
    {"label": "IFRS 16 lease liabilities", "value": "(204.0)", "prior_value": "(200.1)"},
]


def test_clean_net_debt_reported_carries_a_genuine_bridge():
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£147.2m", "quote": _RNK_HEADLINE_QUOTE,
        "breakdown": _RNK_BRIDGE_ROWS, "breakdown_quote": _RNK_BREAKDOWN_QUOTE,
    })
    assert out["found"] is True
    labels = [r["label"] for r in out["breakdown"]]
    assert labels == [r["label"] for r in _RNK_BRIDGE_ROWS]
    assert out["breakdown"][3]["value"] == "(204.0)"
    assert out["breakdown"][3]["prior_value"] == "(200.1)"
    assert out["breakdown_quote"] == _RNK_BREAKDOWN_QUOTE


def test_clean_net_debt_reported_breakdown_absent_by_default():
    """The common case — a single "Net debt £X" line with no bridge under it —
    must not synthesize a one-row breakdown that only repeats `value`."""
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£147.2m", "quote": _RNK_HEADLINE_QUOTE,
    })
    assert out["breakdown"] is None
    assert out["breakdown_quote"] is None


def test_clean_net_debt_reported_breakdown_requires_its_own_quote():
    """A breakdown array with no breakdown_quote at all cannot be checked
    against anything and is dropped whole, same contract as the headline
    figure's own "no quote is a failed guard, not a pass"."""
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£147.2m", "quote": _RNK_HEADLINE_QUOTE,
        "breakdown": _RNK_BRIDGE_ROWS,
    })
    assert out["breakdown"] is None
    assert out["breakdown_quote"] is None


def test_clean_net_debt_reported_breakdown_drops_a_fabricated_row():
    """Same guard as the headline figure, applied per row: a number absent from
    breakdown_quote is dropped rather than trusted, without discarding the
    rows that do check out."""
    rows = _RNK_BRIDGE_ROWS + [
        {"label": "Off-balance-sheet financing", "value": "£999.0m", "prior_value": None},
    ]
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£147.2m", "quote": _RNK_HEADLINE_QUOTE,
        "breakdown": rows, "breakdown_quote": _RNK_BREAKDOWN_QUOTE,
    })
    labels = [r["label"] for r in out["breakdown"]]
    assert "Off-balance-sheet financing" not in labels
    assert len(labels) == 4


def test_clean_net_debt_reported_breakdown_none_when_every_row_fails():
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£147.2m", "quote": _RNK_HEADLINE_QUOTE,
        "breakdown": [{"label": "Invented line", "value": "£777.7m"}],
        "breakdown_quote": _RNK_BREAKDOWN_QUOTE,
    })
    assert out["breakdown"] is None
    assert out["breakdown_quote"] is None


def test_clean_net_debt_reported_breakdown_caps_row_count():
    rows = [
        {"label": f"Row {i}", "value": f"{10 + i}.0", "prior_value": None}
        for i in range(10)
    ]
    bq = "some rows: " + " ".join(f"{10 + i}.0" for i in range(10))
    out = rns_llm._clean_net_debt_reported({
        "found": True, "value": "£147.2m", "quote": _RNK_HEADLINE_QUOTE,
        "breakdown": rows, "breakdown_quote": bq,
    })
    assert len(out["breakdown"]) == rns_llm._ND_BREAKDOWN_MAX


def test_clean_net_debt_reported_breakdown_ignored_on_a_negative_answer():
    # {"found": false} carries no other field, breakdown included.
    out = rns_llm._clean_net_debt_reported({
        "found": False, "breakdown": _RNK_BRIDGE_ROWS,
        "breakdown_quote": _RNK_BREAKDOWN_QUOTE,
    })
    assert out == {"found": False}


def test_prompt_asks_for_the_reconciliation_bridge():
    assert "IFRS 16 lease liabilities" in rns_llm._JSON_SCHEMA_BLOCK
    assert "breakdown" in rns_llm._JSON_SCHEMA_BLOCK


def test_save_ranking_persists_net_debt_reported_as_json():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(
            1,
            {
                "score": 60, "sentiment": "neutral",
                "net_debt_reported": {
                    "found": True, "value": "$3,966.1 million",
                    "as_at": "30 June 2026", "quote": _ANTO_QUOTE,
                },
            },
            "deepseek-v4-flash:fast",
        )
    nd = cur.execute.call_args[0][1][13]
    assert nd.adapted["value"] == "$3,966.1 million"
    assert nd.adapted["as_at"] == "30 June 2026"


def test_save_ranking_stores_null_when_no_net_debt_reported():
    with patch("rns_llm._get_pool") as mock_pool:
        conn = mock_pool.return_value.getconn.return_value
        cur = conn.cursor.return_value
        rns_llm._save_ranking(1, {"score": 60, "sentiment": "neutral"}, "m")
    assert cur.execute.call_args[0][1][13] is None


def test_prompt_forbids_computing_net_debt():
    assert "net_debt_reported" in rns_llm._JSON_SCHEMA_BLOCK
    assert "NET CASH IS NOT NEGATIVE NET DEBT HERE" in rns_llm._JSON_SCHEMA_BLOCK


def test_prompt_forbids_a_gross_cash_balance_and_a_dropped_qualifier():
    # The two live defects found 2026-08-14 (FOUR.L, BBY.L) both got their own
    # prompt paragraph in addition to the mechanical guard, same as fwd_profit's
    # derivation defect did — prompt wording alone didn't stop that one either.
    assert "A GROSS CASH BALANCE IS NOT THIS FIELD" in rns_llm._JSON_SCHEMA_BLOCK
    assert "MUST SURVIVE OUT OF A TABLE ROW TOO" in rns_llm._JSON_SCHEMA_BLOCK
