"""Business-model classification and the quality score, shared by the screener
and the RNS ranker.

This module exists to stop the two from drifting. main.py imports rns_llm (for
its router), so rns_llm cannot import main back — which is why the ranker
historically carried its own hand-ported copy of _quality_score. That copy
summed the ten legs raw against UNSCRUBBED rows, so a bank was scored on its
meaningless FCF margin (the NatWest +734% case) while the screener blanked the
same field and then counted the blank as a failure. Same company, two different
quality scores, neither right.

Everything here is pure: no DB, no imports from main.
"""

import re
from typing import Optional

# ── Business-model classification ────────────────────────────────────────────

_ASSET_HEAVY_SECTORS = {"Utilities", "Real Estate", "Energy", "Basic Materials"}
# Below this revenue/total_assets the classic Z-Score is out of its calibration
# domain: asset/goodwill-heavy names outside the sectors above (Whitbread,
# Ocado, BATS) and float-heavy fintechs (Boku carries merchant float like a
# bank but is filed under Technology) all read as "distressed manufacturers".
_ASSET_HEAVY_TURNOVER = 0.4


def classify_risk_model(row, unknown_is_trust=True):
    """Route a company to the risk model that fits its business.

    Order matters: investment trusts first, banks/insurers by industry before
    the broad financial-sector catch-all, then asset-heavy by sector, telecom
    industry, or measured asset turnover.
    See docs/superpowers/specs/2026-07-03-risk-score-v2-design.md.

    Trusts are detected two ways. Migration 022 stamps them
    'Financial Services'/'Investment Trust' so they stop rendering as sector
    "Unknown"; that industry is ours, Yahoo never emits it. The older
    no-sector-and-no-industry test stays as the fallback, since that is still
    how a newly-added trust arrives from Yahoo before the backfill rule is
    re-run. Both must precede the "financ" in sector catch-all below, which
    would otherwise claim them and cost them the trust metric blanking.

    unknown_is_trust governs that fallback, because absent metadata means
    different things to different callers, and sector/industry alone cannot
    tell them apart:

      * Screener and risk score (default, True): rows come from the curated
        universe, so no sector AND no industry means a fund Yahoo won't
        classify. Keeping this the default matters — _attach_risk_score selects
        only sector and industry, so any cleverer heuristic based on other
        metadata columns would silently strip real trusts of their risk model.
      * RNS ranker (False): company_metadata is a LEFT JOIN and an
        out-of-universe ticker simply has no row. Reading that as a closed-end
        fund would blank its margins and render a genuinely weak company's
        quality as n/a, dropping the LOW QUALITY flag on exactly the
        announcements it should fire for.

    Trusts inside the universe are caught by the "investment trust" industry
    test above regardless, once migration 022 has been applied — which is what
    makes False safe for the ranker.
    """
    sector = (row.get("sector") or "").lower()
    industry = (row.get("industry") or "").lower()
    if "investment trust" in industry:
        return "trust"
    if not sector and not industry:
        return "trust" if unknown_is_trust else "general"
    if "bank" in industry:
        return "bank"
    if "insur" in industry:
        return "insurer"
    if "financ" in sector or "bank" in sector or "insurance" in sector:
        return "financial"
    if row.get("sector") in _ASSET_HEAVY_SECTORS or "telecom" in industry:
        return "asset_heavy"
    revenue, ta = row.get("revenue"), row.get("total_assets")
    if revenue is not None and ta and ta > 0 and revenue / ta < _ASSET_HEAVY_TURNOVER:
        return "asset_heavy"
    return "general"


# ── Metrics that are junk for a business model ───────────────────────────────
# Closed-end funds that Yahoo files under Financial Services / Asset Management
# come through classify_risk_model as "financial"; catch them by name so their
# investment-gain "revenue" doesn't screen as operating performance. Only ever
# tested against financial-model rows, so fund-flavoured words that exist in
# other sectors ("infrastructure") are safe here. Audited against the live
# Asset Management/Capital Markets cohort (2026-07-04): "Ord"/"Income"/
# "Infrastructure"/"Investments" appear exclusively in fund names there;
# word-boundaried so Liontrust ("trust") and City of London Investment Group
# (singular "Investment") don't match. Known escapees (Pershing Square, BH
# Macro, Syncona, …) are left to main.py's degenerate-value caps.
TRUST_NAME_RE = re.compile(
    r"\btrust\b|\bfund\b|\bvct\b|\bord\b|\bincome\b|\binvestments\b"
    r"|\binfrastructure\b|investment company|inv\.? company|private equity",
    re.I,
)

# Everything income-statement-derived is meaningless for a closed-end fund:
# "revenue" is investment gains/losses (BRWM printed +1,158% revenue growth,
# FEV a P/S of 1.6e-08), so margins, P/S and every growth rate are noise, and
# Piotroski leans on the same fields. P/B, dividend yield, ROE/ROA and
# volatility stay — those are the honest lenses for a trust.
TRUST_NA_FIELDS = (
    "price_to_sales", "gross_margin", "operating_margin", "net_income_margin",
    "fcf_margin", "revenue_growth", "eps_diluted_growth", "fcf_growth",
    "revenue_cagr_10", "eps_cagr_10", "roic", "roce", "current_ratio",
    "debt_to_equity", "piotroski_score", "fcf",
)
# Banks/insurers: FCF is meaningless (deposit/claims flows swamp it — the
# NatWest +734% case), current assets/liabilities aren't reported so the
# current ratio is absent or junk (TBCG: 2,462), D/E's numerator misses the
# funding book entirely, and ROIC/ROCE have no sensible denominator. Piotroski
# loses its liquidity/margin legs and reads structurally weak (Financials
# median 3 vs 5 elsewhere) — blanked too. Operating/net margin and P/S are
# kept: for a bank they behave like efficiency ratios and are comparable.
BANK_INSURER_NA_FIELDS = (
    "fcf_margin", "fcf_growth", "fcf", "gross_margin", "current_ratio",
    "roic", "roce", "debt_to_equity", "piotroski_score",
)
# Other financials (asset managers, capital markets, credit services): fee
# revenue is real, so margins and growth stand; only the FCF lens is junk
# (client/fund cash movements dominate the cash-flow statement).
FINANCIAL_NA_FIELDS = ("fcf_margin", "fcf_growth", "fcf")

NA_FIELDS_BY_MODEL = {
    "trust": TRUST_NA_FIELDS,
    "bank": BANK_INSURER_NA_FIELDS,
    "insurer": BANK_INSURER_NA_FIELDS,
    "financial": FINANCIAL_NA_FIELDS,
}


def _fund_name_upgrade(model, row):
    """Promote a fund filed as an ordinary financial to "trust".

    Yahoo files most UK closed-end funds under Financial Services / Asset
    Management, so neither the sector nor the industry gives them away — only
    the name does (TRUST_NAME_RE). Applied to a stored model as well as a fresh
    one: screener_scores holds 'financial' for 108 of them.

    The name is read from `name` or `company_name`: the screener selects
    company_metadata.name, while an RNS candidate carries the announcement's
    company_name. A row carrying NEITHER silently misses the upgrade, so any
    query feeding this must select a name — see _MQVR_SQL and
    _attach_risk_score's own SELECT, neither of which did.
    """
    if model == "financial" and TRUST_NAME_RE.search(
        row.get("name") or row.get("company_name") or ""
    ):
        return "trust"
    return model


def classify_model(row, unknown_is_trust=True):
    """Fresh classification including the fund-name upgrade.

    For callers that are *computing* the model — notably _attach_risk_score,
    which then stores it. Deliberately ignores any stored risk_model on the row,
    so adding that column to a compute query can never make the derivation
    circular.
    """
    return _fund_name_upgrade(classify_risk_model(row, unknown_is_trust), row)


def effective_model(row, unknown_is_trust=True):
    """The model whose rules actually apply to this row, for callers *reading* it.

    Prefers the stored risk_model, falling back to a fresh classification for
    rows screener_scores hasn't covered yet; the fund-name upgrade applies
    either way. This lived inside blank_model_fields until the scrub and
    _value_score both needed the same answer and could disagree about it.
    """
    return _fund_name_upgrade(
        row.get("risk_model") or classify_risk_model(row, unknown_is_trust), row)


def blank_model_fields(row, unknown_is_trust=True):
    """Null out the metrics that are meaningless for this row's business model.

    Mutates and returns `row`.
    """
    for field in NA_FIELDS_BY_MODEL.get(effective_model(row, unknown_is_trust), ()):
        row[field] = None
    return row


# ── Quality score ────────────────────────────────────────────────────────────

# Universe pass rate for each quality leg, over the rows where the leg is
# available. Used to credit legs that model blanking removed (see
# quality_score). Hardcoded rather than computed per request because callers
# score a single row (/api/snapshot, the RNS ranker) — a rate derived from
# whatever rows a caller happens to hold would make the company page, the
# screener and the ranker disagree about the same company.
# Regenerate with: python backend/analysis/quality_score_normalisation.py
QUALITY_LEG_BASE_RATES = {
    "roic_abs": 0.43,
    "roic_med": 0.53,
    "roe_abs": 0.31,
    "roe_med": 0.59,
    "gm_abs": 0.74,
    "gm_med": 0.58,
    "om_abs": 0.55,
    "om_med": 0.62,
    "fcfm_abs": 0.66,
    "nm_med": 0.56,
}
# Below this many available legs the score is noise, so emit None rather than a
# number. Closed-end funds only ever have ROE and ROE-vs-median (everything
# income-statement-derived is blanked by TRUST_NA_FIELDS), so they land here;
# banks and insurers reliably carry five and stay scored.
QUALITY_MIN_LEGS = 3


def quality_legs(r):
    """The ten one-point quality tests as (name, available, passed).

    A leg is available when the inputs it reads survived blanking. Note the
    final leg is independent of fcf_margin: net margin vs its own history has
    nothing to do with cash flow, and nesting it under the FCF branch meant
    blanking a bank's FCF silently cost it that point too.
    """
    roic, roic_med = r.get("roic"), r.get("roic_median")
    roe, roe_med = r.get("roe"), r.get("roe_median")
    gm, gm_med = r.get("gross_margin"), r.get("gross_margin_median")
    om, om_med = r.get("operating_margin"), r.get("operating_margin_median")
    fcfm = r.get("fcf_margin")
    nm, nm_med = r.get("net_income_margin"), r.get("net_margin_median")

    return (
        ("roic_abs", roic is not None, roic is not None and roic > 0.10),
        ("roic_med", roic is not None and roic_med is not None,
         roic is not None and roic_med is not None and roic >= roic_med),
        ("roe_abs", roe is not None, roe is not None and roe > 0.15),
        ("roe_med", roe is not None and roe_med is not None,
         roe is not None and roe_med is not None and roe >= roe_med),
        ("gm_abs", gm is not None, gm is not None and gm > 0.30),
        ("gm_med", gm is not None and gm_med is not None,
         gm is not None and gm_med is not None and gm >= gm_med),
        ("om_abs", om is not None, om is not None and om > 0.10),
        ("om_med", om is not None and om_med is not None,
         om is not None and om_med is not None and om >= om_med),
        ("fcfm_abs", fcfm is not None, fcfm is not None and fcfm > 0.05),
        ("nm_med", nm is not None and nm_med is not None,
         nm is not None and nm_med is not None and nm >= nm_med),
    )


def quality_score(r) -> Optional[int]:
    """Quality score 0-10: rewards high AND consistent returns/margins.

    Ten one-point legs (see quality_legs). Legs whose inputs were blanked as
    meaningless for the business model are credited at the universe pass rate
    for that leg rather than scored 0 — so a metric we deliberately deleted
    neither rewards nor punishes.

    That matters because quality's gaps are systematic, not random: every bank
    is missing exactly the same five legs (FCF margin, gross margin, ROIC and
    the two medians beneath them). Summing the raw legs therefore hard-capped
    banks/insurers at 4/10 and closed-end funds at 2/10, and financials screened
    at a median quality of 1 against 4-6 everywhere else — reading as "poor
    quality" when it only ever meant "not measured".

    Deliberately NOT the renormalise-over-survivors approach used by
    _value_score and _weighted_blend. Those redistribute because their missing
    inputs are missing roughly at random (a loss-maker has no P/E); dividing by
    a systematically-selected subset instead hands any bank that passes all
    five of its legs a perfect 10, which five tests do not evidence.

    Expects a row that has already been through blank_model_fields (the
    screener's scrub does this; ranker callers should use
    quality_score_from_raw). Returns None below QUALITY_MIN_LEGS legs.
    """
    legs = quality_legs(r)
    available = [name for name, avail, _ in legs if avail]
    if len(available) < QUALITY_MIN_LEGS:
        return None
    earned = sum(1 for _, avail, passed in legs if avail and passed)
    imputed = sum(
        QUALITY_LEG_BASE_RATES[name] for name, avail, _ in legs if not avail
    )
    return round(min(10.0, earned + imputed))


def quality_score_from_raw(row) -> Optional[int]:
    """quality_score for callers holding an unscrubbed ttm_financials row.

    Blanks a COPY, so the caller's own dict is untouched — the RNS ranker still
    prints the raw figures into its prompt, and changing what the model sees is
    a separate decision from fixing the score.

    unknown_is_trust=False: these rows reach us through a LEFT JOIN, so missing
    sector/industry means "outside our universe", not "closed-end fund". See
    classify_risk_model.
    """
    return quality_score(blank_model_fields(dict(row), unknown_is_trust=False))
