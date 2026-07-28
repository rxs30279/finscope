"""Announcement body + prior-guidance context in the ranker prompt
(rns_llm._build_messages), and the guidance capture/lookup helpers.

See docs/rns-body-context-plan.md — motivated by LUCE/BARC both scoring 75 on
2026-07-28 while the ranker and vet had only ever seen the third-party AI
summary, never the RNS body itself.
"""

import sys, os
from datetime import datetime, timezone
from unittest.mock import patch

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
    user = _user_prompt()
    assert "guidance_metric" in user
    assert "guidance_value" in user
    assert "guidance_period" in user


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
    user = _user_prompt()
    assert "guidance_checks" in user
    for field in (
        "metric", "period", "guided_value", "consensus_value",
        "vs_prior", "vs_consensus",
    ):
        assert field in user


def test_guidance_checks_separates_prior_and_consensus_axes():
    # These were one enum initially. A figure can be reiterated AND below
    # consensus at once (LUCE's FY26 >£40m against £40.7m); collapsing them
    # into one field made the model pick one and silently drop the other,
    # which flipped LUCE's score run to run.
    user = _user_prompt()
    for v in ("raised", "reiterated", "lowered", "new", "unknown"):
        assert v in user
    for v in ("above", "in_line", "below", "no_consensus_stated"):
        assert v in user
    assert "INDEPENDENT" in user


def test_scoring_rules_cover_both_failure_combinations():
    user = _user_prompt()
    # LUCE: unchanged guide that consensus has overtaken must read negative.
    assert "reiterated + below consensus is a NEGATIVE" in user
    # ULVR: a stated upgrade with no consensus footnote is still a catalyst.
    assert "raised + no_consensus_stated is still a genuine" in user


def test_guidance_checks_precedes_score_in_the_output_schema():
    # Generation order is the whole mechanism — enumerating after the score
    # would let the model rationalise a number it had already chosen.
    user = _user_prompt()
    schema = user.split("Produce a JSON object")[1]
    assert schema.index("guidance_checks") < schema.index("score")


def test_schema_asks_for_every_period_not_just_the_prominent_one():
    user = _user_prompt()
    assert "every period" in user.lower()


def test_system_prompt_warns_against_the_loudest_statement_winning():
    msgs = rns_llm._build_messages(_cand(), [], {})
    system = msgs[0]["content"]
    assert "guidance_checks" in system
    assert "before you choose a score" in system


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
