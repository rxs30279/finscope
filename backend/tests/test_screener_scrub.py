import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import _scrub_screener_metrics, _TRUST_NAME_RE


def _row(**overrides):
    """A plausible non-financial row; every scrubbed field present and sane."""
    base = {
        "symbol": "TEST.L",
        "name": "Test Industrials plc",
        "sector": "Industrials",
        "industry": "Specialty Business Services",
        "risk_model": "general",
        "revenue": 500_000_000,
        "st_debt": 10_000_000,
        "lt_debt": 90_000_000,
        "price_to_earnings": 14.0,
        "price_to_book": 2.1,
        "price_to_sales": 1.4,
        "dividend_yield": 0.03,
        "roe": 0.18,
        "roa": 0.07,
        "roic": 0.12,
        "roce": 0.15,
        "gross_margin": 0.42,
        "operating_margin": 0.13,
        "net_income_margin": 0.09,
        "fcf_margin": 0.08,
        "fcf": 40_000_000,
        "revenue_growth": 0.06,
        "eps_diluted_growth": 0.11,
        "fcf_growth": 0.2,
        "revenue_cagr_10": 0.07,
        "eps_cagr_10": 0.09,
        "debt_to_equity": 0.6,
        "current_ratio": 1.5,
        "piotroski_score": 6,
    }
    base.update(overrides)
    return base


def scrub(row):
    _scrub_screener_metrics([row])
    return row


# ── business-model blanking ───────────────────────────────────────────────────

def test_general_row_untouched():
    r = scrub(_row())
    assert r["fcf_margin"] == 0.08
    assert r["debt_to_equity"] == 0.6
    assert r["piotroski_score"] == 6
    assert r["price_to_sales"] == 1.4


def test_bank_blanks_fcf_liquidity_and_leverage():
    r = scrub(_row(risk_model="bank", sector="Financial Services",
                   industry="Banks - Regional", current_ratio=2462.7))
    for k in ("fcf_margin", "fcf_growth", "fcf", "gross_margin",
              "current_ratio", "roic", "roce", "debt_to_equity",
              "piotroski_score"):
        assert r[k] is None, k
    # efficiency-ratio-style fields survive for banks
    assert r["operating_margin"] is not None
    assert r["net_income_margin"] is not None
    assert r["price_to_sales"] is not None
    assert r["roe"] is not None


def test_insurer_matches_bank_policy():
    r = scrub(_row(risk_model="insurer"))
    assert r["fcf_margin"] is None
    assert r["current_ratio"] is None
    assert r["piotroski_score"] is None


def test_trust_blanks_all_income_statement_metrics():
    r = scrub(_row(risk_model="trust", sector=None, industry=None,
                   name="BlackRock World Mining Trust Ord"))
    for k in ("price_to_sales", "gross_margin", "operating_margin",
              "net_income_margin", "fcf_margin", "revenue_growth",
              "eps_diluted_growth", "fcf_growth", "revenue_cagr_10",
              "eps_cagr_10", "roic", "roce", "current_ratio",
              "debt_to_equity", "piotroski_score", "fcf"):
        assert r[k] is None, k
    # the honest lenses for a trust survive
    assert r["price_to_book"] is not None
    assert r["dividend_yield"] is not None
    assert r["roe"] is not None


def test_financial_blanks_only_fcf():
    r = scrub(_row(risk_model="financial", sector="Financial Services",
                   industry="Asset Management",
                   name="Liontrust Asset Management PLC"))
    assert r["fcf_margin"] is None
    assert r["fcf_growth"] is None
    assert r["fcf"] is None
    # fee revenue is real: margins/growth stand for genuine asset managers
    assert r["operating_margin"] is not None
    assert r["revenue_growth"] is not None
    assert r["piotroski_score"] is not None


def test_named_closed_end_fund_promoted_to_trust():
    # Yahoo files many closed-end funds under Financial Services / Asset
    # Management; the name test catches them (FEV, NESF, RICA, PPET class).
    r = scrub(_row(risk_model="financial", sector="Financial Services",
                   industry="Asset Management",
                   name="Fidelity European Trust Ord"))
    assert r["revenue_growth"] is None
    assert r["operating_margin"] is None
    assert r["price_to_sales"] is None


def test_trust_name_regex_word_boundaries():
    assert _TRUST_NAME_RE.search("NextEnergy Solar Fund Limited")
    assert _TRUST_NAME_RE.search("Ruffer Investment Company Limited")
    assert _TRUST_NAME_RE.search("Patria Private Equity Trust plc")
    # Yahoo's closed-end-fund naming: share-class suffix / income / holdings
    assert _TRUST_NAME_RE.search("Utilico Emerging Markets Ord")
    assert _TRUST_NAME_RE.search("Henderson Far East Income Limited")
    assert _TRUST_NAME_RE.search("Oakley Capital Investments Limited")
    assert _TRUST_NAME_RE.search("3i Infrastructure plc")
    assert _TRUST_NAME_RE.search("Schroder Asian Total Return Inv. Company")
    # real operators must not match: "trust"/"investment" inside words or
    # singular forms stay untouched
    assert not _TRUST_NAME_RE.search("Liontrust Asset Management PLC")
    assert not _TRUST_NAME_RE.search("City of London Investment Group Plc")
    assert not _TRUST_NAME_RE.search("Man Group Plc")
    assert not _TRUST_NAME_RE.search("St. James's Place plc")


def test_missing_risk_model_falls_back_to_classifier():
    # No screener_scores row yet: bank routing must still come from industry.
    r = scrub(_row(risk_model=None, sector="Financial Services",
                   industry="Banks - Diversified"))
    assert r["fcf_margin"] is None
    assert r["current_ratio"] is None


def test_null_sector_null_industry_classified_as_trust():
    r = scrub(_row(risk_model=None, sector=None, industry=None,
                   name="Some Capital Ord"))
    assert r["revenue_growth"] is None
    assert r["price_to_sales"] is None


# ── degenerate-value guards ───────────────────────────────────────────────────

def test_shell_revenue_blanks_revenue_ratios():
    r = scrub(_row(revenue=113_000, net_income_margin=-341.7,
                   price_to_sales=3275.7, gross_margin=1.0))
    for k in ("price_to_sales", "gross_margin", "operating_margin",
              "net_income_margin", "fcf_margin", "revenue_growth"):
        assert r[k] is None, k
    # non-revenue metrics survive
    assert r["roe"] is not None
    assert r["debt_to_equity"] is not None


def test_negative_revenue_blanks_revenue_ratios():
    r = scrub(_row(revenue=-456_110_000, price_to_sales=255.6))
    assert r["price_to_sales"] is None


def test_missing_revenue_keeps_margins_but_ps_cap_still_applies():
    # revenue None: margins are None upstream anyway; a Yahoo P/S snapshot can
    # still exist and only the absurdity cap can catch it (MKA: P/S 3,341).
    r = scrub(_row(revenue=None, price_to_sales=3341.3))
    assert r["price_to_sales"] is None


def test_negative_price_to_book_blanked():
    assert scrub(_row(price_to_book=-9.5))["price_to_book"] is None
    assert scrub(_row(price_to_book=0))["price_to_book"] is None
    assert scrub(_row(price_to_book=0.4))["price_to_book"] == 0.4


def test_price_to_sales_negative_or_absurd_blanked():
    assert scrub(_row(price_to_sales=-15.3))["price_to_sales"] is None
    assert scrub(_row(price_to_sales=301.0))["price_to_sales"] is None
    assert scrub(_row(price_to_sales=299.0))["price_to_sales"] == 299.0


def test_absurd_current_ratio_blanked():
    # client-money floats masquerading as liquidity (Quilter: 115.9)
    assert scrub(_row(current_ratio=115.9))["current_ratio"] is None
    assert scrub(_row(current_ratio=3.2))["current_ratio"] == 3.2


def test_base_effect_growth_capped():
    r = scrub(_row(revenue_growth=76.14, eps_diluted_growth=-12.2, fcf_growth=4.9))
    assert r["revenue_growth"] is None
    assert r["eps_diluted_growth"] is None
    assert r["fcf_growth"] == 4.9  # within ±500%


def test_broken_cagr_capped():
    r = scrub(_row(revenue_cagr_10=12.6, eps_cagr_10=0.9))
    assert r["revenue_cagr_10"] is None
    assert r["eps_cagr_10"] == 0.9  # within ±100%/yr


def test_phantom_debt_free_de_blanked():
    # both debt fields missing + D/E 0.0 → unreported debt, not debt-free
    r = scrub(_row(st_debt=None, lt_debt=None, debt_to_equity=0.0))
    assert r["debt_to_equity"] is None


def test_reported_zero_debt_keeps_de_zero():
    r = scrub(_row(st_debt=0, lt_debt=None, debt_to_equity=0.0))
    assert r["debt_to_equity"] == 0.0


def test_de_from_lse_merge_survives_missing_debt_fields():
    # D/E nonzero with no debt fields (e.g. LSE-merged ratio) is kept
    r = scrub(_row(st_debt=None, lt_debt=None, debt_to_equity=0.8))
    assert r["debt_to_equity"] == 0.8


def test_debt_helper_fields_removed_from_response():
    r = scrub(_row())
    assert "st_debt" not in r
    assert "lt_debt" not in r
