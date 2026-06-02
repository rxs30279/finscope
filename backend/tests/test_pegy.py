import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import _attach_pegy, _forward_pe, _PEGY_GROWTH_CAP

_f = lambda x: float(x) if x is not None else None


def _row(**kw):
    """Build a screener row with sensible PEGY-relevant defaults.

    With eps_diluted / eps_est_current_yr left None, _attach_pegy falls back to the
    trailing price_to_earnings, so the basic tests below exercise that path.
    """
    base = {
        "price_to_earnings": 20.0,
        "eps_diluted": None,
        "eps_est_current_yr": None,
        "eps_growth_next_yr": None,
        "eps_cagr_10": None,
        "total_analysts": 0,
        "dividend_yield": None,
        "dividends_per_share": None,
        "period_end_price": None,
    }
    base.update(kw)
    return base


def _pegy(**kw):
    rows = _attach_pegy([_row(**kw)])
    return rows[0]["pegy"]


# ── Basic formula ───────────────────────────────────────────────────────────────

def test_pegy_basic_from_cagr():
    # PE=20, growth=10% (cagr, <3 analysts path), no yield → 20 / 10 = 2.0
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=0.10) == 2.0


def test_pegy_uses_dividend_yield_field():
    # growth=10%, dividend_yield=0.05 (5%) → denom 15% → 20/15 = 1.33
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=0.10, dividend_yield=0.05) == 1.33


def test_pegy_falls_back_to_dps_over_price_when_yield_absent():
    # No dividend_yield → derive from dps/price: 5/100 = 5% → denom 15% → 1.33
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=0.10,
                 dividends_per_share=5.0, period_end_price=100.0) == 1.33


def test_dividend_yield_field_takes_precedence_over_dps():
    # When both present, the clean dividend_yield (8%) wins over dps/price (5%):
    # denom 18% → 20/18 = 1.11
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=0.10, dividend_yield=0.08,
                 dividends_per_share=5.0, period_end_price=100.0) == 1.11


# ── Growth capping ──────────────────────────────────────────────────────────────

def test_growth_is_capped_so_recovery_bounce_does_not_look_cheap():
    # Forward growth of 150% should be capped at 30% → denom 30, not 150.
    # 20 / 30 = 0.67, not the misleadingly cheap 20/150 = 0.13.
    assert _pegy(price_to_earnings=20.0, eps_growth_next_yr=1.50, total_analysts=5) \
        == round(20.0 / (_PEGY_GROWTH_CAP * 100), 2)


# ── Blend of forward + trailing ─────────────────────────────────────────────────

def test_blends_forward_and_trailing_when_both_present():
    # fwd=20% (>=3 analysts), cagr=10% → blend 15% → 20/15 = 1.33
    assert _pegy(price_to_earnings=20.0, eps_growth_next_yr=0.20,
                 eps_cagr_10=0.10, total_analysts=5) == 1.33


def test_forward_ignored_when_too_few_analysts():
    # <3 analysts → forward dropped, falls back to cagr=10% → 20/10 = 2.0
    assert _pegy(price_to_earnings=20.0, eps_growth_next_yr=0.20,
                 eps_cagr_10=0.10, total_analysts=2) == 2.0


# ── Positive growth floor ───────────────────────────────────────────────────────

def test_negative_growth_yields_none_even_with_fat_yield():
    # Shrinking earnings (-8%) + 12% yield must NOT produce a PEGY.
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=-0.08,
                 dividends_per_share=12.0, period_end_price=100.0) is None


def test_zero_growth_yields_none():
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=0.0) is None


# ── Guards ──────────────────────────────────────────────────────────────────────

def test_none_when_pe_missing():
    assert _pegy(price_to_earnings=None, eps_cagr_10=0.10) is None


def test_none_when_pe_negative():
    assert _pegy(price_to_earnings=-5.0, eps_cagr_10=0.10) is None


def test_none_when_no_growth_data():
    assert _pegy(price_to_earnings=20.0) is None


def test_none_when_denominator_too_small():
    # growth 1% (positive but tiny), no yield → denom 1 < 2 → None
    assert _pegy(price_to_earnings=20.0, eps_cagr_10=0.01) is None


# ── Forward P/E rebasing ─────────────────────────────────────────────────────────

def test_forward_pe_rebases_onto_analyst_estimate():
    # Rolls-Royce shape: statutory EPS (0.69) inflated by one-offs vs forward
    # estimate (0.37). Trailing P/E 16.5 → forward P/E ~30.7.
    row = _row(price_to_earnings=16.52, eps_diluted=0.6914, eps_est_current_yr=0.37087)
    fpe = _forward_pe(row, _f)
    assert round(fpe, 1) == round(16.52 * 0.6914 / 0.37087, 1) == 30.8


def test_forward_pe_is_currency_safe_via_ratio():
    # USD reporter: eps_diluted and estimate share the (USD) currency so the ratio
    # is unitless; trailing_PE already handled the GBp-price conversion.
    # AZN shape: trailing 28.0, eps_dil 6.54 (USD), est 10.30 (USD) → ~17.8.
    row = _row(price_to_earnings=27.98, eps_diluted=6.54, eps_est_current_yr=10.29951)
    assert round(_forward_pe(row, _f), 1) == 17.8


def test_forward_pe_falls_back_to_trailing_without_estimate():
    row = _row(price_to_earnings=20.0)  # no eps_diluted / estimate
    assert _forward_pe(row, _f) == 20.0


def test_pegy_uses_forward_pe_so_one_off_inflated_eps_is_not_cheap():
    # Same RR shape with +16.8% growth. Trailing-PE PEGY would be ~0.98 (false
    # cheap); forward-PE PEGY is ~1.8 (correctly not cheap).
    pegy = _pegy(price_to_earnings=16.52, eps_diluted=0.6914, eps_est_current_yr=0.37087,
                 eps_growth_next_yr=0.1677, total_analysts=20)
    assert pegy > 1.5


def test_forward_pe_ignored_when_eps_diluted_non_positive():
    # Loss-making statutory year (eps_diluted <= 0): can't form a safe ratio, so
    # fall back to trailing P/E.
    row = _row(price_to_earnings=20.0, eps_diluted=-0.5, eps_est_current_yr=0.4)
    assert _forward_pe(row, _f) == 20.0
