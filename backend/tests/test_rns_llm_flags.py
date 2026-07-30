"""Margin quality flag in the ranker prompt (rns_llm._build_messages).

The WEAK MARGINS flag is judged against the industry-peer median (computed in
the candidate query) with a capital-returns escape hatch — a profitable name
with ROCE >= 0.15 is never flagged for thin margins, but loss-makers always
are. Floors mirror the showcase selection gates in showcase.py.

It is now the ONLY weakness flag. The "!! LOW QUALITY (weak fundamentals)"
banner that used to fire on quality_score <= 3 was removed 2026-07-30 — half
that score's legs compare a company to its own history, so it branded sound
businesses having a below-peak year (Greggs, Shell, JD Sports, Persimmon) as
weak, and being the leading `if` it shadowed the peer-relative test for exactly
those names. The tests below therefore assert the peer-relative flag where they
used to assert the quality one; several fixtures trip it on the same inputs.
"""

import sys, os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rns_llm


def _user_prompt(**overrides) -> str:
    cand = {
        "ticker": "TST",
        "company_name": "Test plc",
        "headline": "Trading Statement",
        "category": "trading_update",
        "tier": "A",
        "market_cap": 500_000_000,
        "published_at": datetime(2026, 7, 9, 6, 0, tzinfo=timezone.utc),
        "roic": 0.20, "roic_median": 0.10,
        "roe": 0.20, "roe_median": 0.10,
    }
    cand.update(overrides)
    msgs = rns_llm._build_messages(cand, [], {})
    return msgs[1]["content"]


def test_thin_margin_high_roce_not_flagged():
    # CCC.L case: margin below the peer floor but strong capital returns —
    # a low-margin/high-ROCE model is structure, not fragility.
    user = _user_prompt(net_income_margin=0.0167, peer_margin_median=0.04, roce=0.24)
    assert "WEAK MARGINS" not in user


def test_thin_margin_weak_roce_flagged():
    user = _user_prompt(net_income_margin=0.0167, peer_margin_median=0.04, roce=0.07)
    assert "WEAK MARGINS (below industry median)" in user


def test_loss_maker_flagged_despite_high_roce():
    user = _user_prompt(net_income_margin=-0.05, peer_margin_median=0.04, roce=0.90)
    assert "WEAK MARGINS (loss-making)" in user


def test_margin_above_peer_median_not_flagged():
    user = _user_prompt(net_income_margin=0.06, peer_margin_median=0.04, roce=None)
    assert "WEAK MARGINS" not in user


def test_missing_peer_median_uses_absolute_fallback():
    # No usable peer group (industry too small): the 0.02 absolute floor
    # applies, and the hatch still rescues strong capital returns.
    user = _user_prompt(net_income_margin=0.015, peer_margin_median=None, roce=None)
    assert "WEAK MARGINS (below industry median)" in user
    user = _user_prompt(net_income_margin=0.015, peer_margin_median=None, roce=0.20)
    assert "WEAK MARGINS" not in user


def test_prompt_labels_median_as_industry():
    user = _user_prompt(net_income_margin=0.0167, peer_margin_median=0.04, roce=0.24)
    assert "(industry median +4.0%)" in user


def test_no_fundamentals_quality_is_na_not_zero():
    # CLBS case: out-of-universe ticker with no ttm_financials row — every
    # fundamental is None. Quality must render n/a, not 0/10, and absent data
    # must not trip any weakness flag.
    user = _user_prompt(roic=None, roic_median=None, roe=None, roe_median=None)
    assert "Quality:      n/a" in user
    assert "n/a (vs own history)" not in user  # nonsense suffix on a non-score
    assert "WEAK MARGINS" not in user


def test_quality_line_is_labelled_as_a_self_comparison():
    """The score must never be printed as a bare verdict on the business.

    Greggs scored 3/10 on it while running 19.5% ROE, 16.5% ROCE and net cash,
    and the model quoted "low quality score indicates weak fundamentals" back
    into llm_risks. The label is what stops a trend measure reading as a level.
    """
    user = _user_prompt(net_income_margin=0.06, peer_margin_median=0.04)
    assert "Quality:      8/10 (vs own history)" in user


def test_all_failing_metrics_flagged_via_peer_margin():
    # A company with real (bad) data keeps a low score, and is still flagged —
    # now by the peer-relative margin test rather than the quality score.
    #
    # Scores 3, not 0: this fixture supplies no *_median fields, so the five
    # "vs its own history" legs are unavailable rather than failed, and
    # quality.py credits an unavailable leg at the universe base rate.
    #
    # net_income_margin is set because the peer test needs it, and because a
    # row with roic present and net margin absent does not exist in the
    # universe (verified 2026-07-30: 0 of 713). 0.005 is below the 0.02
    # no-peer-group fallback floor.
    user = _user_prompt(
        roic=0.01, roic_median=None, roe=0.02, roe_median=None,
        gross_margin=0.05, operating_margin=0.01, fcf_margin=-0.02,
        net_income_margin=0.005,
    )
    assert "Quality:      3/10 (vs own history)" in user
    assert "WEAK MARGINS (below industry median)" in user


def test_failing_metrics_with_full_history_score_zero():
    # With the medians present every leg is available and genuinely failed,
    # so nothing is imputed and the score is a true 0/10. Still flagged: net
    # margin 0.01 sits under the 0.02 fallback floor with no ROCE hatch.
    user = _user_prompt(
        roic=0.01, roic_median=0.10, roe=0.02, roe_median=0.15,
        gross_margin=0.05, gross_margin_median=0.40,
        operating_margin=0.01, operating_margin_median=0.12,
        fcf_margin=-0.02, net_income_margin=0.01, net_margin_median=0.08,
    )
    assert "Quality:      0/10 (vs own history)" in user
    assert "WEAK MARGINS" in user


def test_strong_business_off_its_peak_is_not_flagged():
    """The regression this whole change exists to prevent — the Greggs case.

    Below its own historical median on every self-comparison leg (so a low
    quality score), but net cash, high ROCE and a net margin above its industry
    peers. It must reach the peer-relative test and pass it.
    """
    user = _user_prompt(
        roic=0.128, roic_median=0.181,
        roe=0.195, roe_median=0.269,
        gross_margin=0.615, gross_margin_median=0.616,
        operating_margin=0.087, operating_margin_median=0.096,
        fcf_margin=0.024,
        net_income_margin=0.057, net_margin_median=0.077,
        peer_margin_median=0.047, roce=0.165,
    )
    assert "Quality:      3/10 (vs own history)" in user
    assert "WEAK MARGINS" not in user
    assert "LOW QUALITY" not in user


def test_unknown_metadata_is_not_treated_as_a_trust():
    """An out-of-universe ticker must not be read as a closed-end fund.

    company_metadata is a LEFT JOIN here, so sector/industry are NULL for a
    ticker we don't cover. Classifying that as "trust" would blank its margins
    and render quality n/a — the CLBS-shaped failure the test above guards
    against — and would also strip the net margin the WEAK MARGINS test needs.
    """
    user = _user_prompt(
        sector=None, industry=None,
        roic=0.01, roic_median=0.10, roe=0.02, roe_median=0.15,
        gross_margin=0.05, gross_margin_median=0.40,
        operating_margin=0.01, operating_margin_median=0.12,
        fcf_margin=-0.02, net_income_margin=0.01, net_margin_median=0.08,
    )
    assert "Quality:      n/a" not in user
    assert "WEAK MARGINS" in user


def test_bank_is_not_scored_on_its_junk_fcf():
    """The ranker used to grade banks on raw, meaningless FCF/gross margin.

    A bank passing the legs that are honest for it (ROE, operating margin, net
    margin vs history) should read as decent quality and carry no weakness flag.
    """
    user = _user_prompt(
        sector="Financial Services", industry="Banks - Diversified",
        roic=None, roic_median=None, roe=0.25, roe_median=0.15,
        gross_margin=None, gross_margin_median=None,
        operating_margin=0.18, operating_margin_median=0.12,
        fcf_margin=7.34,  # the NatWest +734% case
        net_income_margin=0.11, net_margin_median=0.08,
    )
    assert "LOW QUALITY" not in user
    assert "WEAK MARGINS" not in user


def test_quality_score_none_when_no_inputs():
    assert rns_llm._quality_score({}) is None
