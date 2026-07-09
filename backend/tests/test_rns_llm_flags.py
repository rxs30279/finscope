"""Margin quality flag in the ranker prompt (rns_llm._build_messages).

The WEAK MARGINS flag is judged against the industry-peer median (computed in
the candidate query) with a capital-returns escape hatch — a profitable name
with ROCE >= 0.15 is never flagged for thin margins, but loss-makers always
are. Floors mirror the showcase selection gates in showcase.py.
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
        # Keep the generic quality score above the LOW QUALITY cutoff (<=3) so
        # these tests exercise the margin branch of the flag, not the quality one.
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
