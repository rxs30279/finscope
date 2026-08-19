"""RNS (Regulatory News Service) screener.

Ingests the investegate.co.uk announcements feed, classifies each headline into
an importance tier with a rules-only scorer, and exposes API endpoints for the
morning screen.

Data source: investegate.co.uk list pages (no official API). Scraped HTML is
stable — rows live in a single <div class="announcement-table"> and each row is
a <tr> with timestamp / wire / company / headline columns. The headline link
URL carries both the ticker and the slug we classify on, which is more robust
than parsing localisation-sensitive headline text.
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, date, timedelta, time as _dt_time
from typing import Optional

from zoneinfo import ZoneInfo

_UK_TZ = ZoneInfo("Europe/London")

import psycopg2
import psycopg2.extras
import psycopg2.pool
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from dotenv import load_dotenv

from admin_auth import require_admin_token

load_dotenv()

router = APIRouter(prefix="/api/rns", tags=["rns"])


# ── DB — shared process-wide pool + query (see db.py). Re-exported under this
# module's historical names (rns_llm / email_rns_digest / refresh_rns import
# `_query` and `_get_pool` from here). ────────────────────────────────────────
from db import query as _query, get_pool as _get_pool


# ── Classifier (pure functions) ───────────────────────────────────────────────

# Category → (tier, match_patterns). Patterns match against the URL slug OR the
# lower-cased headline. First match wins, so list more specific entries first.
_CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    # "Notice of …" pre-announcements must be caught first — they're just scheduling,
    # not the event itself. Listed above the Tier A results categories so the slug
    # "notice-of-interim-results" doesn't match interim_results.
    (
        "notice_of_results",
        "C",
        (
            "notice-of-results",
            "notice-of-interim-results",
            "notice-of-final-results",
            "notice-of-full-year-results",
            "notice-of-half-year-results",
            "notice-of-annual-results",
            "notice-of-preliminary-results",
            "notice-of-quarterly-results",
            "notice-of-q1-results",
            "notice-of-q2-results",
            "notice-of-q3-results",
            "notice-of-q4-results",
            "notice of results",
            "notice of interim results",
            "notice of final results",
        ),
    ),
    # Tier A — always surface
    ("profit_warning", "A", ("profit-warning", "profit warning")),
    (
        "trading_update",
        "A",
        (
            "trading-update",
            "trading-statement",
            "q1-trading",
            "q3-trading",
            "q1-business-update",
            "q2-business-update",
            "q3-business-update",
            "q4-business-update",
            "business-update",
            "trading statement",
            "q1 trading",
            "q3 trading",
        ),
    ),
    (
        "final_results",
        "A",
        (
            "final-results",
            "annual-results",
            "full-year-results",
            "preliminary-results",
            "full year results",
            "annual results",
            "preliminary results",
        ),
    ),
    (
        "interim_results",
        "A",
        (
            "interim-results",
            "half-year-results",
            "half-yearly-report",
            "half-year-ended",
            "half-yearly-financial-report",
            "six-months-ended",
            "results-for-the-half-year",
            "results-for-the-six-months",
            "interim report",
            "half year results",
            "half year ended",
            "six months ended",
            "half-yearly report",
        ),
    ),
    (
        "quarterly",
        "A",
        (
            "q1-results",
            "q2-results",
            "q3-results",
            "q4-results",
            "first-quarter-results",
            "third-quarter-results",
            "quarterly-update",
        ),
    ),
    ("firm_offer", "A", ("rule-2.7", "rule-2-7", "rule 2.7", "firm-offer")),
    # "Combination"/"merger" are the all-share phrasing of the same Takeover Code
    # events as "offer" — SEGRO filed "Statement re Possible Combination" (22 Jul
    # 2026) and "Recommended Combination" (4 Aug 2026), a £13bn FTSE 100 merger
    # that both offer categories missed on the wording alone, twice.
    (
        "possible_offer",
        "A",
        (
            "rule-2.4",
            "rule-2-4",
            "rule 2.4",
            "possible-offer",
            "possible offer",
            "possible-combination",
            "possible combination",
            "possible-merger",
            "possible merger",
        ),
    ),
    (
        "recommended_offer",
        "A",
        (
            "recommended-offer",
            "recommended-cash-offer",
            "recommended offer",
            "recommended-combination",
            "recommended combination",
            "recommended-merger",
            "recommended merger",
        ),
    ),
    (
        "ma_update",
        "B",
        (
            "update-re-",
            "update-on-offer",
            "offer-update",
            "update-re offer",
            "update on offer",
        ),
    ),
    (
        "fund_winddown",
        "B",
        (
            "compulsory-redemption",
            "compulsory redemption",
            "managed-wind-down",
            "managed wind-down",
            "notice-of-wind-up",
            "notice of wind-up",
        ),
    ),
    (
        "strategic_review",
        "A",
        (
            "strategic-review",
            "formal-sale-process",
            "strategic review",
            "formal sale process",
        ),
    ),
    (
        "suspension",
        "A",
        (
            "suspension-of-",
            "temporary-suspension",
            "suspension of listing",
            "suspension of trading",
        ),
    ),
    ("going_concern", "A", ("going-concern", "going concern")),
    (
        "liquidation",
        "A",
        (
            "liquidation-announcement",
            "notice-of-liquidation",
            "administration",
            "going-into-administration",
            "liquidation announcement",
        ),
    ),
    (
        "delisting",
        "A",
        (
            "cancellation-of-admission",
            "cancellation-of-listing",
            "notice-of-cancellation",
            "cancellation - ",
            "cancellation-",
        ),
    ),
    (
        "response_to",
        "A",
        (
            "response-to-speculation",
            "response-to-press",
            "response-to-media",
            "response to speculation",
            "response to press",
        ),
    ),
    # Tier B — surface for larger caps
    (
        "capital_markets",
        "B",
        ("capital-markets-day", "investor-day", "capital markets day", "investor day"),
    ),
    (
        "capital_raise",
        "B",
        (
            "placing-",
            "-placing",
            "rights-issue",
            "open-offer",
            "subscription-and-",
            "-subscription",
            "fundraise",
            "fundraising",
            "result-of-retail-offer",
            "retail-offer",
            "debt-facility",
            "loan-facility",
            "stream-financing",
            "convertible-bond-issue",
            "senior-notes-issue",
            "placing and",
            "rights issue",
            "open offer",
            "placing &",
        ),
    ),
    (
        "acquisition",
        "B",
        (
            "acquisition-of",
            "-acquisition",
            "acquires-",
            "-acquires",
            "proposed-acquisition",
            "acquisition of",
            "proposed acquisition",
        ),
    ),
    (
        "disposal",
        "B",
        ("disposal-of", "-disposal", "sale-of-", "disposal of", "sale of"),
    ),
    (
        "contract_win",
        "B",
        (
            "contract-award",
            "contract-win",
            "-contract-",
            "framework-agreement",
            "mou-with",
            "partnership-agreement",
            "strategic-collaboration",
            "distribution-agreement",
            "contract award",
            "contract win",
            "framework agreement",
            "strategic collaboration",
        ),
    ),
    (
        "board_change",
        "B",
        (
            "ceo-appointment",
            "chief-executive",
            "chairman-succession",
            "chair-appointment",
            "cfo-appointment",
            "director-appointment",
            "director-resignation",
            "board-change",
            "-resigns",
            "steps-down",
            "directorate-change",
            "change-in-board",
            "confirmation-of-new-cfo",
            "confirmation-of-new-ceo",
            "new-ceo",
            "new-cfo",
            "appointment-of-board-director",
            "appointment-of-technical-director",
            "board-role-change",
            "leadership-update",
            "change-in-appointment-of-representative-directors",
            "change-in-appointment-of",
            "change in appointment of",
            "ceo appointment",
            "chief executive",
            "board change",
            "steps down",
            "directorate change",
            "retirement",
            "standing down",
            "standing-down",
            "stepping down",
            "stepping-down",
            "departure",
            "resignation",
            "succession",
        ),
    ),
    (
        "drug_approval",
        "B",
        (
            "fda-approval",
            "mhra-approval",
            "ce-mark-approval",
            "regulatory-approval",
            "fda approval",
            "mhra approval",
            "regulatory approval",
        ),
    ),
    (
        "clinical_trial",
        "B",
        (
            "phase-i",
            "phase-ii",
            "phase-iii",
            "clinical-trial",
            "trial-results",
            "topline-results",
            "phase i",
            "phase ii",
            "phase iii",
            "clinical trial",
            "trial results",
        ),
    ),
    (
        "drill_results",
        "B",
        (
            "drill-results",
            "exploration-results",
            "assay-results",
            "reserves-update",
            "resource-update",
            "drilling-update",
            "drill results",
            "exploration results",
        ),
    ),
    (
        "dividend_change",
        "B",
        (
            "dividend-increase",
            "special-dividend",
            "dividend-cut",
            "dividend suspended",
            "dividend increase",
            "special dividend",
        ),
    ),
    (
        "update_statement",
        "B",
        ("update-statement", "trading-and-operational-update", "operational-update"),
    ),
    # NOTE: product / new-business-line launches are handled by _PRODUCT_LAUNCH_RE in the
    # fallback block, NOT as an enumerated category. "launch" is too broad to sit in Tier B
    # ahead of the Tier C categories below — "Launch of share buyback programme" must stay
    # buyback/Tier C, "Launch of Placing" capital_raise, etc. Running it as a fallback means
    # it only fires when no enumerated category (including the Tier C ones) matched.
    # Tier C — routine noise
    (
        "buyback",
        "C",
        (
            "transaction-in-own-shares",
            "transactions-in-own-shares",
            "transaction-in-ow",  # covers truncated slugs ("...in-ow-")
            "share-buyback-programme",
            "share-buyback-program",
            "purchase-of-own-shares",
            "treasury-shares-issued",
            "ebt-share-purchase",
            "transaction in own shares",
        ),
    ),
    ("tvr", "C", ("total-voting-rights", "-tvr", "voting rights and capital")),
    (
        "holdings",
        "C",
        (
            "holding-s-in-company",  # "(s)" becomes "-s-" in slugs
            "holding(s)-in-company",
            "holdings-in-company",
            "form-tr-1",
            "notification-of-major-holdings",
            "tr-major-holding-notification",
            "major-shareholding-notification",
            "form tr-1",
            "holding in company",
        ),
    ),
    (
        "disclosure_8",
        "C",
        (
            "form-8.3",
            "form-8.5",
            "form-8-3",
            "form-8-5",
            "form-8-opd",
            "form-8-dd",
            "form-38-5",
            "form-38.5",
            "form 8.3",
            "form 8.5",
            "form 38.5",
        ),
    ),
    (
        "rule_2_9",
        "C",
        ("rule-2-9", "rule 2.9", "rule-2.9", "acceptance-level-update"),
    ),  # offer period disclosures
    (
        "director_pdmr",
        "C",
        (
            "director-pdmr-shareholding",
            "director/pdmr-shareholding",
            "pdmr-shareholding",
            "pdmr-transaction-notification",
            "director-declaration",
            "director-dealing",
            "director-dealings",
            "reporting-of-transactions-made-by-persons",
            "pdmr shareholding",
            "director dealing",
        ),
    ),
    ("block_listing", "C", ("block-listing", "block-admission", "block listing")),
    (
        "agm_notice",
        "C",
        (
            "notice-of-agm",
            "notice-of-gm",
            "annual-financial-report-and-notice",
            "notice-of-annual-general-meeting",
            "notice-of-annual-general",  # truncated slug
            "result-of-agm",
            "results-of-agm",
            "proceedings-of-postal-ballot",
            "shareholders-approve",
            "iss-voting-recommendation",
            "publishes-annual-report",
            "publication-of-the-annual-report",
            "publication-of-the-2025-annual-report",
            "publication-of-annual-report",
            "2025-annual-report",  # e.g. "2025-annual-report-*-di-"
            "annual-report-and-notice",
            "notice of agm",
            "result of agm",
            "notice of annual general meeting",
        ),
    ),
    (
        "equity_issue",
        "C",
        (
            "issue-of-equity",
            "admission-of-further-securities",
            "admission-of-further-shares",
            "admission-of-shares",
            "admission-to-trading",
            "grant-of-long-term-incentive",
            "grant-of-ltip",
            "grant-of-warrants",
            "grant-of-options",
            "grant-of-share-options",
            "ltip-grant",
            "long-term-incentive-plan-awards",
            "saye-option-plan",
            "share-incentive-plan",
            "purchase-of-shares-by-employee-benefit-trust",
            "issue-of-shares-on-conversion",
            "issue-of-awards-under-the-company-s-ltip",
            "application-for-quotation-of-securities",
            "cleansing-notice",
            "issue of equity",
            "admission of shares",
        ),
    ),
    (
        "dividend_routine",
        "C",
        (
            "dividend-declaration",
            "interim-dividend-declaration",
            "final-dividend-declaration",
            "dividend-payment-date",
            "interim-d-",  # truncated "interim-dividend"
            "dividend declaration",
        ),
    ),
    (
        "final_terms",
        "C",
        (
            "final-terms",
            "final terms",
            "notice-of-redemption",
            "notice of redemption",
            "early-redemption",
            "issuer-call-notice",
            "publication-of-a-supplementary-prospectus",
            "supplementary-prospectus",
        ),
    ),
    (
        "compliance",
        "C",
        (
            "compliance-with-market-abuse",
            "aim-rule-17",
            "mar-disclosure",
            "market abuse regulation",
            "eqs-pvr-",
        ),
    ),  # German voting rights disclosures
    (
        "fund_update",
        "C",
        (
            "monthly-factsheet",
            "factsheet-commentary",
            "monthly-investor-report",
            "portfolio-update",
            "monthly factsheet",
        ),
    ),
    (
        "investor_event",
        "C",
        (
            "investor-presentation-via-investor-meet-company",
            "investor-presentation",
            "investor-webinar",
            "investor-meet-company",
            "analyst-site-visit",
            "analyst-briefing",
            "quarterly-conference-call",
        ),
    ),
    (
        "nomad",
        "C",
        (
            "appointment-of-nominated-adviser",
            "appointment-of-nominated-financial-adviser",
            "change-of-nominated-adviser",
            "appointment of nominated",
        ),
    ),
    ("nav", "C", ("net-asset-value", "-nav-", "net asset value")),
]

# Keyword overlays (applied on lower-cased headline). Each hit adjusts the score.
_NEGATIVE_KEYWORDS = (
    "profit warning",
    "materially below",
    "below expectations",
    "below market",
    "challenging",
    "weaker",
    "going concern",
    "covenant",
    "suspended",
    "resigns",
    "resignation",
    "investigation",
    "cautious outlook",
    "significantly below",
    "downgrade",
    "impairment",
    "write-down",
    "write down",
    "under review",
)
_POSITIVE_KEYWORDS = (
    "ahead of expectations",
    "ahead of market",
    "significantly ahead",
    "upgraded guidance",
    "raised guidance",
    "raised outlook",
    "record",
    "strong trading",
    "beat expectations",
    "materially ahead",
    "ahead of consensus",
)
_CATALYTIC_KEYWORDS = (
    "recommended offer",
    "possible offer",
    "in discussions",
    "strategic review",
    "formal sale process",
    "firm offer",
)


# Full-year results take many headline shapes the enumerated final_results slugs
# ("final results", "annual results", "full-year results", …) all miss:
#   "FY26 Results" / "FY2026 Results" / "Results FY26"      — fiscal year + results
#   "FY Results"                                             — FY standalone + results
#   "FY results for the financial year ended 31/3/2026"     — full-year prose
#   "Financial Results for year ended 28 February 2026"     — "...year ended <date>"
#   "Results for the 52 week period ended 31 May 2026"      — 52/53-week retail fiscal year
# Enumerating every year × separator variant is fragile and needs a yearly bump,
# so match the shapes directly. \bfy\b keeps the word boundary so it never fires
# inside "satisfy"/"notify"/"comfy". The "year ended" form is the canonical full-year
# results phrasing; the half-year/six-months variants are caught above as interim_results
# first (so they never reach this fallback) and the "notice" guard keeps schedulers out.
# The "weeks ended" form covers UK retailers (Games Workshop, Next, M&S, …) that report
# on a 52/53-week fiscal calendar instead of a calendar year — "year ended" never
# appears in their headline at all (Games Workshop GAW, 2026-07-28, was dropped to
# Tier C and never scored because of this).
_FY_RESULTS_RE = re.compile(
    r"\bfy\d{0,4}\b.*\bresults?\b"
    r"|\bresults?\b.*\bfy\d{0,4}\b"
    r"|\byear ended\b.*\bresults?\b"
    r"|\bresults?\b.*\byear ended\b"
    r"|\bweeks?\s+(?:period\s+)?ended\b.*\bresults?\b"
    r"|\bresults?\b.*\bweeks?\s+(?:period\s+)?ended\b"
)

# Interim/half-year results take just as many shapes the enumerated interim_results
# slugs miss — "Half-year Financial Report", "Interim Report", "Half Yearly Report",
# "First Half Results" (Unilever ULVR, 2026-07-28 — dropped to Tier C and never
# scored because "half" here isn't attached to "year" at all).
# Match a half-year/six-months/interim/bare-half marker paired with a results/report/
# statement word. Checked BEFORE _FY_RESULTS_RE in the fallback because "half year
# ended" also contains "year ended", so the full-year regex would otherwise mislabel
# it. "interim" is safe here only because a results/report/statement word is required
# — "Interim Dividend" (→ dividend_routine) is already categorised above and never
# reaches this. Bare "half" is safe for the same reason: paired with results/report/
# statement, real false-positive candidates ("half of directors resign, statement
# follows") aren't real RNS headline phrasing.
_INTERIM_RESULTS_RE = re.compile(
    r"\b(?:half[- ]?year(?:ly)?|six[- ]?months?|interim|half)\b.*\b(?:results?|report|statement)\b"
)

# Contract wins phrased so the enumerated contract_win slugs miss them: the "award"
# and "contract" words split or reversed ("provisional award of 25yr LDES contract",
# Gresham House GRID 2026-06-29 — the slug ends "-contract" so the "-contract-"
# pattern, which needs hyphens both sides, can't match), or won/secured/preferred-
# bidder forms. Require BOTH an award/win verb AND "contract"/"tender" so it never
# fires on LTIP "awards" (no contract word) — those stay equity_issue/Tier C.
_CONTRACT_RE = re.compile(
    r"\b(?:award(?:ed|s)?|wins?|won|secur(?:e|es|ed)|selected)\b.*\b(?:contract|tender)\b"
    r"|\b(?:contract|tender)\b.*\b(?:award(?:ed|s)?|wins?|won|secur(?:e|es|ed)|selected)\b"
    r"|\bpreferred[- ]bidder\b"
)

# An "Annual Financial Report" / "Annual Report and Accounts" is the publication of
# the full annual report — for many issuers (esp. trusts/funds) it IS the full-year
# results, not AGM admin (Aberdeen City Council 54MP, 2026-06-26, was being grabbed by
# agm_notice/Tier C). Only the bare report forms; the genuine-admin variants
# ("publication of …", "… and notice of AGM") stay in agm_notice / are excluded by the
# notice+agm guard on the fallback so the bundled report-plus-meeting items stay Tier C.
_ANNUAL_REPORT_RE = re.compile(
    r"\bannual financial report\b"
    r"|\bannual report (?:and|&) (?:consolidated )?(?:accounts|financial statements)\b"
)

# Product / new-business-line launches and market expansion ("Plus500 launches sports
# event-based contracts", 2026-06-29). Deliberately broad — Tier B routes it to the LLM
# ranker to judge materiality. Run ONLY as a fallback (after every enumerated category)
# so it never out-ranks a more specific action: "Launch of share buyback programme"
# stays buyback/Tier C, "Launch of Placing" capital_raise, "launch of strategic review"
# strategic_review. \blaunch\b excludes "re-launch" mid-word is fine; the verb covers
# launch/launches/launched/launching.
_PRODUCT_LAUNCH_RE = re.compile(
    r"\blaunch(?:es|ed|ing)?\b"
    r"|\bnew (?:product|platform|service|range)\b"
    r"|\broll[- ]?out\b"
    r"|\bexpan(?:ds|sion) into\b"
    r"|\bmarket entry\b"
)

# US-style "earnings" headlines that every enumerated results category misses:
# Ryanair Holdings ("Q1 FY27 Ryanair Holdings plc Earnings", 2026-07-21) reports
# with an earnings-release headline that carries no "results"/"trading" word, so
# quarterly (needs "q1-results") and _FY_RESULTS_RE (needs "results") both fall
# through and the release drops to Tier C — never scored, never surfaced. Treat
# "earnings" as a results word when it's paired with a reporting-period marker
# (Q1–Q4 / FY / half-year / interim / annual / quarterly) or a release/report
# word. The "notice" guard on the fallback block keeps "Notice of Q1 Earnings"
# out; deliberately NOT matching bare "earnings call"/"presentation" so pure
# scheduling isn't promoted. Tier/category are picked from the period marker.
_EARNINGS_RE = re.compile(
    r"\bearnings\b.*\b(?:release|report|results|statement)\b"
    r"|\b(?:release|report|results|statement)\b.*\bearnings\b"
    r"|\bq[1-4]\b.*\bearnings\b"
    r"|\bfy\d{0,4}\b.*\bearnings\b"
    r"|\b(?:full[- ]?year|half[- ]?year|six[- ]?months?|first[- ]?quarter"
    r"|second[- ]?quarter|third[- ]?quarter|fourth[- ]?quarter|interim"
    r"|preliminary|quarterly|annual)\b.*\bearnings\b"
)

# bp files its quarterly results as "2Q26 BP PLC SEA" ("SEA" = Stock Exchange
# Announcement; 4 Aug 2026, −4.9% on the day). Both halves defeat the classifier
# today: every `quarterly` pattern is letter-first ("q2-results") so the
# digit-first "2Q26" never matches, and the headline carries no results word at
# all for the regex fallbacks to catch. Hence a period marker written
# digit-first, which also rescues plain "2Q 2026 Results" (39IB, Tier C today).
_DIGIT_QUARTER_RE = re.compile(r"\b[1-4]q[- ]?(?:19|20)?\d{0,4}\b")
_SHORT_FY_RE      = re.compile(r"\bfy[- ]?(?:19|20)?\d{2}\b")

# "SEA" earns its place as a results word only behind one of those markers —
# the bare token is far too ambiguous to trust on its own ("Update on Sea
# Concession 2A Technical Report", KZG, must stay Tier C).
_RESULTS_WORD_RE = re.compile(
    r"\b(?:results?|earnings|report|release|statement|sea)\b"
)

# Scheduling collateral published *around* a results release — invitations,
# decks, replays. Same intent as the "notice" guard on the fallback block, and
# as _EARNINGS_RE's deliberate refusal to match bare "earnings call" /
# "presentation": the event itself is Tier A, the diary furniture is not.
# Without this, "HR- 2Q26 Earnings Presentation" (BVA) and "1H and 2Q 2026
# Results Conference Call Invitation" (37QB) would both be promoted.
_RESULTS_COLLATERAL_RE = re.compile(
    r"\bpresentation\b|\bconference call\b|\bwebcast\b|\binvitation\b"
    r"|\btranscript\b|\bslides\b|\bcall details\b"
)


# Issuers routinely bundle the scheduling note onto the event itself: "Trading
# Update and Notice of Results" is a real trading update with a diary line
# attached, not diary admin. Because notice_of_results is listed first (so a
# bare "notice-of-interim-results" slug can't reach interim_results), the
# "notice" half won and 14 genuine updates in the 38 days the table retains as
# of 5 Aug 2026 — TRB, ACSO, APTD, FNTL, FSJ, UPR, FLO, EMR, BIG, FNX, AIEA,
# JDG, NXQ, TPFG — all dropped to Tier C, roughly one every 2.7 days, so the
# ranker never saw any of them. When a substantive update word sits
# alongside the notice, skip notice_of_results and let the loop fall through to
# trading_update. Deliberately narrow: only the words that are themselves a
# Tier A trading_update pattern, so "Notice of Results" alone stays Tier C.
_NOTICE_WITH_UPDATE_RE = re.compile(
    r"\btrading[- ](?:update|statement)\b|\bbusiness[- ]update\b"
)

# Single-word filings. Halma (4 Aug 2026, +5.5% on the day) and FirstGroup
# (29 Jul 2026) each filed a disposal under the bare headline "Disposal", with
# "disposal" as the whole slug too — every disposal pattern needs a companion
# word ("disposal of", "-disposal"), so both fell to Tier C. Matched on equality
# rather than substring so headlines that merely mention a disposal keep their
# own (usually Tier C) category.
_BARE_EVENT_CATEGORIES: dict[str, tuple[str, str]] = {
    "disposal": ("disposal", "B"),
    "acquisition": ("acquisition", "B"),
}


def _classify(headline: str, slug: str) -> dict:
    """Classify one announcement into tier/category/keyword hits/score.

    Pure function: no DB, no network. Takes headline text and URL slug.
    Returns dict with keys: tier, category, keyword_hits, score.
    """
    hay_slug = (slug or "").lower()
    hay_headline = (headline or "").lower()

    # Category match — slug first (more reliable), fall back to headline text
    category = None
    tier = "C"
    for cat, t, patterns in _CATEGORIES:
        if any(p in hay_slug or p in hay_headline for p in patterns):
            if cat == "notice_of_results" and _NOTICE_WITH_UPDATE_RE.search(
                f"{hay_slug} {hay_headline}"
            ):
                continue  # bundled with a real update — keep looking
            category = cat
            tier = t
            break

    # Bare one-word filings, before the results/contract regex fallbacks. Only
    # reached when nothing above matched, so it can never override a category.
    if category is None:
        for bare in (hay_headline.strip(), hay_slug.strip("- ")):
            if bare in _BARE_EVENT_CATEGORIES:
                category, tier = _BARE_EVENT_CATEGORIES[bare]
                break

    # Fallback: results announcements (e.g. "FY26 Results", "Half-year Financial
    # Report") that the enumerated final_results/interim_results slugs miss. Runs
    # only when nothing more specific matched. Skip when "notice" is present — a
    # "Notice of FY26 Results" is just scheduling (the notice_of_results slugs don't
    # cover these forms either, so without the guard the fallback would wrongly
    # promote it to Tier A). Interim is checked first: "half year ended" also
    # contains "year ended", which the full-year regex would otherwise grab.
    hay = f"{hay_slug} {hay_headline}"
    if category is None and "notice" not in hay:
        if _INTERIM_RESULTS_RE.search(hay):
            category, tier = "interim_results", "A"
        elif _FY_RESULTS_RE.search(hay):
            category, tier = "final_results", "A"
        elif (
            "agm" not in hay
            and "general meeting" not in hay
            and _ANNUAL_REPORT_RE.search(hay)
        ):
            category, tier = "final_results", "A"
        elif _EARNINGS_RE.search(hay):
            # Route by reporting period: half-year → interim, quarter → quarterly,
            # otherwise full-year. All Tier A (a real earnings release ranks with
            # results). Interim is tested first because "half year" contains "year".
            if re.search(r"\b(?:half[- ]?year|six[- ]?months?|interim)\b", hay):
                category, tier = "interim_results", "A"
            elif re.search(r"\bq[1-4]\b|\bquarter(?:ly)?\b", hay):
                category, tier = "quarterly", "A"
            else:
                category, tier = "final_results", "A"
        elif (
            _RESULTS_WORD_RE.search(hay)
            and not _RESULTS_COLLATERAL_RE.search(hay)
            and (_DIGIT_QUARTER_RE.search(hay) or _SHORT_FY_RE.search(hay))
        ):
            # Digit-first period marker + a results word. Routed by the marker,
            # matching how _EARNINGS_RE picks its category.
            if _DIGIT_QUARTER_RE.search(hay):
                category, tier = "quarterly", "A"
            else:
                category, tier = "final_results", "A"
        elif _CONTRACT_RE.search(hay):
            category, tier = "contract_win", "B"
        elif _PRODUCT_LAUNCH_RE.search(hay):
            category, tier = "product_launch", "B"

    # Keyword overlays on headline
    hits = []
    neg_hits = sum(1 for k in _NEGATIVE_KEYWORDS if k in hay_headline)
    pos_hits = sum(1 for k in _POSITIVE_KEYWORDS if k in hay_headline)
    cat_hits = sum(1 for k in _CATALYTIC_KEYWORDS if k in hay_headline)
    if neg_hits:
        hits.append(f"neg:{neg_hits}")
    if pos_hits:
        hits.append(f"pos:{pos_hits}")
    if cat_hits:
        hits.append(f"cat:{cat_hits}")

    # Score: tier base + capped overlay contribution
    base = {"A": 60, "B": 40, "C": 10}[tier]
    score = base + min(neg_hits, 2) * 15 + min(pos_hits, 2) * 15 + min(cat_hits, 2) * 10
    score = max(0, min(100, score))

    return {
        "tier": tier,
        "category": category,
        "keyword_hits": hits,
        "score": score,
    }


# ── HTML fetch + parse ────────────────────────────────────────────────────────

# Identify the crawler honestly. The pipeline makes ~130-210 requests/day on
# weekdays only (measured 2026-08-09: ~110 list pages + 20-100 detail pages),
# which is light enough that a spoofed browser string bought nothing and only
# looked evasive in someone else's logs. If investegate ever blocks on the UA,
# reverting this commit is the fix — but check the cron log for a 429/403
# first, since _urlopen_polite now reports throttling explicitly.
_USER_AGENT = "AlphaMoveAI/1.0 (+https://app.alphamoveai.co.uk; UK RNS aggregator)"
_BASE_URL = "https://www.investegate.co.uk"


class _RateLimited(Exception):
    """Investegate throttled us (429/403) — deliberately NOT a URLError subclass.

    HTTPError *is* a URLError, so before this existed a throttle was caught by
    the generic `except urllib.error.URLError` handlers and silently ended the
    run. A block and a quiet news day looked identical in the data. Callers
    must catch this separately and surface it.
    """

    def __init__(self, code: int, url: str, retry_after: Optional[float] = None):
        self.code = code
        self.url = url
        self.retry_after = retry_after
        super().__init__(f"HTTP {code} from {url} (retry_after={retry_after})")


_THROTTLE_CODES = {429, 403}
_THROTTLE_BACKOFF_S = (5.0, 20.0)   # waits before retry 1 and retry 2
_RETRY_AFTER_CAP_S = 60.0           # longer than this, give up to the next cron run

def _parse_send_time(raw: str) -> _dt_time:
    try:
        h, m = raw.strip().split(":")
        return _dt_time(int(h), int(m))
    except Exception:
        return _dt_time(7, 30)


# THE send time, in one place. cron-job.org holds the trigger (see main.py's
# /api/digest) and cannot import this, so the two must be kept in sync by
# hand — but everything INSIDE the backend derives from here: the fail-fast
# throttle window below, run_rns's deferral of post-ranking stages, and
# healthcheck's rns.morning_batch bar. If this runs ahead of the real
# cron-job.org trigger, all three misfire in the gap between them: the
# throttle window relaxes early (weaker protection right before the real
# send), the vet/gates/prune deferral stops early (reintroducing the lock
# contention it exists to avoid, now right before the real send), and
# morning_batch cries wolf against a bar the real send doesn't have to meet
# yet — the same class of bug as the 07:12-vs-07:30 mis-calibration fixed
# 2026-07-31, just pointed the other way.
#
# Defaults to matching the LIVE cron-job.org schedule (07:30) rather than the
# 07:15 target, precisely so this file staying ahead of an unmoved cron isn't
# the default state. Override with the DIGEST_SEND_UK env var (e.g. "07:15")
# to test a moved target without deploying — set it back once cron-job.org's
# own trigger actually moves to match, then this default can follow it.
DIGEST_SEND_UK = _parse_send_time(os.environ.get("DIGEST_SEND_UK", "07:30"))

# The 07:00 RNS drop has to be ingested, summarised and ranked before the
# digest send (email_rns_digest). Measured 2026-08-09 over 21 days: the 07:00
# batch finishes scoring at 07:05-07:08 on a normal day — but sleeping through
# a throttle is still the wrong trade inside this window. The */15 cron
# retries within 15 min, and a late row costs far less than a thin digest. So
# cap backoff hard here and fail fast to the next run.
_URGENT_WINDOW = (_dt_time(6, 30), DIGEST_SEND_UK)
_URGENT_BACKOFF_CAP_S = 5.0


def _backoff_cap_s(now: Optional[datetime] = None) -> float:
    """Longest single backoff we're willing to sleep at the current clock time."""
    t = (now or datetime.now(_UK_TZ)).time()
    lo, hi = _URGENT_WINDOW
    return _URGENT_BACKOFF_CAP_S if lo <= t < hi else _RETRY_AFTER_CAP_S


def in_urgent_window(now: Optional[datetime] = None) -> bool:
    """True while the morning batch is racing the digest send.

    Public because run_rns uses it to defer post-ranking work: the vet, the
    gate sweep and the prune all run AFTER the digest's content is settled
    (the digest reads llm_score, never vet_score), but they hold the pipeline
    lock while they do it, which stops the next burst run ingesting.
    """
    t = (now or datetime.now(_UK_TZ)).time()
    lo, hi = _URGENT_WINDOW
    return lo <= t < hi


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a Retry-After header — either delta-seconds or an HTTP-date."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return float(v)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def _urlopen_polite(url: str, timeout: int) -> str:
    """GET a URL, backing off and retrying on 429/403 before giving up.

    Honours Retry-After when investegate sends one, but never sleeps longer
    than _backoff_cap_s() allows — waiting past the cap just collides with the
    next */15 cron run, and inside the 07:30 digest window it risks the send.
    Raises _RateLimited once retries are exhausted or a wait exceeds the cap;
    every other HTTP or network error propagates unchanged.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    cap = _backoff_cap_s()
    attempts = len(_THROTTLE_BACKOFF_S)
    for attempt in range(attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code not in _THROTTLE_CODES:
                raise
            retry_after = _parse_retry_after(e.headers.get("Retry-After"))
            # Exhaustion check first — _THROTTLE_BACKOFF_S has one entry per
            # retry, so there is no backoff to look up on the final attempt.
            if attempt == attempts:
                raise _RateLimited(e.code, url, retry_after) from e
            wait = retry_after if retry_after is not None else _THROTTLE_BACKOFF_S[attempt]
            if wait > cap:
                raise _RateLimited(e.code, url, retry_after) from e
            print(
                f"[rns] THROTTLED {e.code} on {url} — backing off {wait:.0f}s "
                f"(retry {attempt + 1}/{attempts}, cap {cap:.0f}s)"
            )
            time.sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover

# Investegate URL: /announcement/{wire}/{company-slug}--{ticker}/{headline-slug}/{id}
_ANN_URL_RE = re.compile(r"/announcement/([^/]+)/[^/]+--([^/]+)/([^/]+)/(\d+)")

# Wires to drop at ingest — non-regulatory PR/newswire feeds that never resolve to a
# company in our universe and are pure noise. FNW = "FinanceWire News" (ticker FNEWS):
# press releases for non-UK-listed entities (STARTRADER, PU Prime, …); 44 rows / 14 days,
# 0 symbol-resolved, 0 tier A/B of value. Excluded rows are skipped before upsert so they
# never enter the DB or reach the LLM/feed.
_EXCLUDED_WIRES = {"FNW"}


def _fetch_page(page: int = 1, timeout: int = 20) -> str:
    """Fetch one list page of the investegate announcement feed."""
    url = _BASE_URL + ("/" if page == 1 else f"/?page={page}")
    return _urlopen_polite(url, timeout)


def _parse_timestamp(text: str) -> Optional[datetime]:
    """Parse '17 Apr 2026 06:20 PM' → tz-aware datetime in Europe/London.

    Investegate renders timestamps in UK local time with no timezone marker.
    Attaching Europe/London tzinfo lets psycopg2 convert to UTC correctly on
    insert, handling BST/GMT transitions automatically.
    """
    if not text:
        return None
    text = text.strip()
    for fmt in ("%d %b %Y %I:%M %p", "%d %b %Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_UK_TZ)
        except ValueError:
            continue
    return None


def _parse_rows(html: str) -> list[dict]:
    """Extract announcement rows from a list-page HTML string.

    Returns a list of raw row dicts (not yet classified or upserted) with keys:
        id, published_at, wire, ticker, company_name, headline, headline_slug, url
    """
    from bs4 import BeautifulSoup  # deferred — only the ingest/scrape path needs it
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("div", class_="announcement-table")
    if table is None:
        # Fall back — some pages may have nested structure
        table = soup
    rows: list[dict] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 4:
            continue
        ts_text = tds[0].get_text(strip=True)
        published_at = _parse_timestamp(ts_text)
        if published_at is None:
            continue

        # Wire — source-XXX class on the regulatory <a>
        wire = None
        wire_a = tds[1].find("a")
        if wire_a:
            wire = wire_a.get_text(strip=True).upper() or None

        # Company column — first anchor href is /company/{TICKER}
        ticker = None
        company_name = None
        comp_links = tds[2].find_all("a")
        for a in comp_links:
            href = a.get("href", "") or ""
            if "/company/" in href:
                ticker = href.rsplit("/company/", 1)[-1].strip().upper() or None
            if a.get_text(strip=True):
                company_name = a.get_text(strip=True)
        # Company name usually includes "(TICKER)" suffix — strip it for cleanliness
        if company_name:
            company_name = re.sub(r"\s*\([^)]+\)\s*$", "", company_name).strip()

        # Headline link
        a_headline = tds[3].find("a", class_="announcement-link")
        if a_headline is None:
            continue
        url = (a_headline.get("href") or "").strip()
        headline = a_headline.get_text(strip=True)
        m = _ANN_URL_RE.search(url)
        if not m:
            continue
        url_wire, url_ticker, slug, ann_id = m.groups()
        if wire is None:
            wire = url_wire.upper()
        if ticker is None and url_ticker:
            ticker = url_ticker.upper()

        # Drop non-regulatory PR/newswire feeds (e.g. FinanceWire) — pure noise.
        if wire in _EXCLUDED_WIRES:
            continue

        rows.append(
            {
                "id": int(ann_id),
                "published_at": published_at,
                "wire": wire,
                "ticker": ticker,
                "company_name": company_name,
                "headline": headline,
                "headline_slug": slug.lower(),
                "url": url,
            }
        )
    return rows


# ── Ticker → symbol resolution ────────────────────────────────────────────────

_SYMBOL_CACHE: dict[str, Optional[str]] = {}


def _resolve_symbol(ticker: Optional[str]) -> Optional[str]:
    """Map an investegate ticker (e.g. KIE, JD.) to a stored yfinance symbol (e.g. KIE.L).

    Caches results in-process. Returns None if no match — the row is still stored.
    """
    if not ticker:
        return None
    if ticker in _SYMBOL_CACHE:
        return _SYMBOL_CACHE[ticker]

    # Investegate tickers drop the .L suffix; some include a trailing dot (JD.)
    t = ticker.rstrip(".")
    candidates = [f"{t}.L", f"{ticker}.L", ticker]
    # Share-class tickers (e.g. BT.A) use a dot on investegate but a hyphen on
    # Yahoo (BT-A.L) — try that form too.
    if "." in t:
        candidates.append(f"{t.replace('.', '-')}.L")
    rows = _query(
        "SELECT symbol FROM company_metadata WHERE symbol = ANY(%s) LIMIT 1",
        (candidates,),
    )
    resolved = rows[0]["symbol"] if rows else None
    _SYMBOL_CACHE[ticker] = resolved
    return resolved


# ── DB write ──────────────────────────────────────────────────────────────────


def _upsert(row: dict) -> bool:
    """Upsert one classified announcement. Returns True if newly inserted."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rns_announcements (
                id, published_at, wire, ticker, symbol, company_name,
                headline, headline_slug, url, tier, category, keyword_hits, score
            ) VALUES (
                %(id)s, %(published_at)s, %(wire)s, %(ticker)s, %(symbol)s, %(company_name)s,
                %(headline)s, %(headline_slug)s, %(url)s, %(tier)s, %(category)s,
                %(keyword_hits)s, %(score)s
            )
            ON CONFLICT (id) DO UPDATE SET
                tier         = EXCLUDED.tier,
                category     = EXCLUDED.category,
                keyword_hits = EXCLUDED.keyword_hits,
                score        = EXCLUDED.score,
                symbol       = EXCLUDED.symbol,
                fetched_at   = NOW()
            RETURNING (xmax = 0) AS inserted
        """,
            row,
        )
        (inserted,) = cur.fetchone()
        conn.commit()
        return bool(inserted)
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Ingest orchestration ──────────────────────────────────────────────────────


def _build_row(raw: dict) -> dict:
    """Combine parsed row + classifier + symbol resolution into a DB-ready dict."""
    cls = _classify(raw["headline"], raw["headline_slug"])
    return {
        **raw,
        "symbol": _resolve_symbol(raw.get("ticker")),
        "tier": cls["tier"],
        "category": cls["category"],
        "keyword_hits": cls["keyword_hits"],
        "score": cls["score"],
    }


def _prune_old(days: int = 14, body_days: int = 30) -> dict:
    """Hard-delete Tier C rns_announcements older than `days` (by published_at),
    and NULL out the `body` column on Tier A/B rows older than `body_days`.

    Tier C is routine paperwork (PDMR, TVR, buybacks) at high volume with no
    lasting value, so it's still bounded at `days`. Tier A/B rows are kept
    indefinitely — they carry llm_sentiment and are the prior-news history
    shown on the High Impact showcase and fed to the ranker's per-issuer
    history prompt (see rns_llm._load_history), so they must outlive the
    showcase's own tracking window instead of a fixed cutoff.

    The full announcement body is only needed at scoring time, though — kept
    indefinitely on every retained A/B row it would grow rns_announcements
    against Supabase's free-tier storage cap, so it's NULLed after
    `body_days` while body_chars/body_fetched_at survive for diagnostics.
    guidance_metric/value/period also survive — they're the per-issuer memory
    the NEXT announcement compares against (see rns_llm._load_prior_guidance)
    and cost negligible space compared to the body text itself. So does
    guidance_checks, which is the audit trail for why showcase did or didn't
    flag a row (see showcase._disqualifying_guidance).
    """
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM rns_announcements
            WHERE published_at < NOW() - (%s || ' days')::interval
              AND (tier IS NULL OR tier NOT IN ('A', 'B'))
            """,
            (str(days),),
        )
        deleted = cur.rowcount

        cur.execute(
            """
            UPDATE rns_announcements
            SET body = NULL
            WHERE tier IN ('A', 'B')
              AND body IS NOT NULL
              AND published_at < NOW() - (%s || ' days')::interval
            """,
            (str(body_days),),
        )
        body_pruned = cur.rowcount

        return {
            "deleted": deleted,
            "older_than_days": days,
            "body_pruned": body_pruned,
            "body_older_than_days": body_days,
        }
    finally:
        pool.putconn(conn)


def _run_ingest(
    max_pages: int = 7, stop_on_known: bool = True, sleep_s: float = 2.0
) -> dict:
    """Fetch up to max_pages of the feed, classify, and upsert.

    If stop_on_known is True, stops early once a whole page produced no new rows.
    """
    processed = inserted = updated = errors = 0
    rate_limited = False
    # Why the loop ended. "caught_up" is the only outcome that proves we saw
    # every new row: an abort leaves rows on the unread pages, and because the
    # next run's page 2 will be all-known, stop_on_known guarantees no future
    # run ever reaches them. The caller must force a deep sweep instead.
    stopped = "ceiling"
    for page in range(1, max_pages + 1):
        try:
            html = _fetch_page(page)
        except _RateLimited as e:
            # Distinct from a network failure: we were throttled, so the run is
            # short on data by decision rather than because the feed was quiet.
            print(f"[rns] RATE LIMITED on page {page} — aborting ingest ({e})")
            rate_limited = True
            errors += 1
            stopped = "rate_limited"
            break
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[rns] page {page} fetch failed: {e}")
            errors += 1
            stopped = "fetch_error"
            break
        raws = _parse_rows(html)
        if not raws:
            print(f"[rns] page {page}: no rows parsed")
            stopped = "caught_up"
            break
        page_new = 0
        for raw in raws:
            try:
                row = _build_row(raw)
                was_new = _upsert(row)
                processed += 1
                if was_new:
                    inserted += 1
                    page_new += 1
                else:
                    updated += 1
            except Exception as e:
                errors += 1
                print(f"[rns] upsert failed id={raw.get('id')}: {e}")
        print(f"[rns] page {page}: parsed={len(raws)} new={page_new}")
        if stop_on_known and page_new == 0 and page > 1:
            stopped = "caught_up"
            break
        if page < max_pages:
            time.sleep(sleep_s)
    result = {
        "processed": processed,
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
        "rate_limited": rate_limited,
        "stopped": stopped,
        "complete": stopped == "caught_up",
    }
    print(f"[rns] ingest done — {result}")
    return result


# ── Summary + body scraper (investegate AI summary + full announcement text) ──

# Full-text container per wire, checked in order. Deliberately NOT `.art-board`
# — verified over 20 recent Tier A/B rows to match 6 nodes per page, the first
# being page chrome rather than the announcement.
_BODY_SELECTORS = (
    ("RNS", "fr-view-element"),
    ("PRN", "prn-announcement"),
)

# Generic fallback for the wires above's long tail. Investegate carries at least
# seven wires (rns, prn, eqs, gnw, bzw, mfn, ukn) and each non-RNS one wraps its
# text in its own `{wire}-announcement` / `mfn-body` div, so the two selectors
# above captured nothing at all for five of them — those bodies never reached the
# ranker or the vet. Rather than hardcode (and have to maintain) a class per
# wire, fall back to the one container common to every wire's page.
#
# Checked second, not first: on RNS pages `news-window` is a superset of
# `fr-view-element` that also picks up the registered-address header and the
# "This information is provided by RNS" footer (4709 vs 3918 chars on a sampled
# announcement), so the precise selectors stay ahead of it and only pages with no
# recognised container reach this. Measured over the 15 tier A/B rows that missed
# in the three days to 2026-08-14, it recovers 12 — including two half-year
# reports and a 49k-char interim — and costs no chrome on the wires that need it
# (on an eqs page `news-window` and `eqs-announcement` are the same 1627 chars).
#
# Guarded on an exact single match for the same reason `.art-board` was rejected:
# a layout change that turned this into a repeated wrapper would otherwise start
# silently returning page chrome as announcement text.
_BODY_FALLBACK_SELECTOR = "news-window"

# Bodies under this many chars are stubs — announcements that only point at an
# external PDF rather than carrying the text themselves.
_BODY_STUB_CHARS = 600

# Store (and prompt with) at most this many chars: head + tail, not head-only.
# Outlook statements and CEO quotes sit near the top; consensus footnotes and
# reiterated-guidance language have been seen ~85% of the way through a long
# results document, so head-only truncation would silently drop exactly the
# sentences this feature exists to surface.
_BODY_CAP = 24_000
_BODY_HEAD = 16_000
_BODY_TAIL = 8_000


def _extract_summary(soup) -> Optional[str]:
    """Pull the #collapseSummary text out of an already-parsed announcement page."""
    node = soup.find(id="collapseSummary")
    if node is None:
        return None
    # The disclaimer link is a child <p> — drop it before extracting text.
    for p in node.find_all("p", id="summary-disclaimer"):
        p.decompose()
    text = node.get_text(" ", strip=True)
    return text or None


def _fetch_body(soup) -> Optional[str]:
    """Pull the full announcement text out of an already-parsed announcement page.

    Tries each wire's container in turn, then the generic cross-wire fallback;
    returns None if none matched (page layout changed, or genuinely nothing
    there — a `ukn-announcement` div that is present but empty reaches here as
    None, which is correct: there is no text on the page to capture). A short
    body that DOES match a container is a stub, not a miss — see
    _BODY_STUB_CHARS / body_is_stub.
    """
    for _wire, cls in _BODY_SELECTORS:
        node = soup.find("div", class_=cls)
        if node is not None:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    nodes = soup.find_all("div", class_=_BODY_FALLBACK_SELECTOR)
    if len(nodes) == 1:
        text = nodes[0].get_text(" ", strip=True)
        if text:
            return text
    return None


def _truncate_body(text: str) -> tuple[str, int, bool]:
    """Cap body text for storage/prompting.

    Returns (stored_text, original_chars, is_stub). Under the cap the text is
    kept whole; over it, head+tail with an explicit omission marker so the
    model knows the middle was cut rather than silently trusting a truncated
    document as complete.
    """
    n = len(text)
    is_stub = n < _BODY_STUB_CHARS
    if n <= _BODY_CAP:
        return text, n, is_stub
    omitted = n - _BODY_HEAD - _BODY_TAIL
    stored = (
        text[:_BODY_HEAD]
        + f"\n\n[… {omitted} chars omitted …]\n\n"
        + text[-_BODY_TAIL:]
    )
    return stored, n, is_stub


# ── PDF-follow: results published as a link rather than as text ───────────────
#
# A material minority of issuers file results as a one-page RNS carrying only the
# dividend, the webcast dial-in and a link — the numbers live in a PDF on the
# LSE's own host. Measured over 2026-06-29..2026-08-19: 13% of in-universe
# results announcements arrive with no full text anywhere within +/-2 days, and
# the tradeable half of those (RKT, CNA, SDR, AV, HLN, TCAP, OCDO) all point at
# rns-pdf.londonstockexchange.com. Reckitt's half-year scored 30 with the
# ranker's own thesis reading "full financials not disclosed in this RNS", while
# page 1 of the linked PDF opens "FY OUTLOOK REITERATED" — precisely the
# guidance_checks signal the showcase gate exists to catch.
#
# These are NOT caught by body_is_stub: at 1.1k-3.3k chars they sit well above
# _BODY_STUB_CHARS, so without this path the pipeline treats the pointer as the
# document and the ranker scores the furniture.

# Both scheme and the www. host prefix vary in the wild; the `_N` suffix and the
# filing date in the stem are what the gates below key on.
_LSE_PDF_RE = re.compile(
    r"https?://(?:www\.)?rns-pdf\.londonstockexchange\.com/rns/"
    r"[A-Za-z0-9]+_(\d+)-(\d{4})-(\d{1,2})-(\d{1,2})\.pdf",
    re.I,
)

# Only follow the link when the announcement does not already carry its own
# results. Measured gain (PDF chars / body chars): AZN 131k body x1.2 — the same
# document re-attached, pure waste — against SDR 1.7k x49, HLN 3.3k x37, LGEN
# 4.7k x67. Above this threshold the fetch buys nothing, and can actively harm:
# Burford's linked PDF is a shareholder slide deck, not the results statement.
_BODY_PDF_MAX_BODY = 12_000

# The filename is stamped with the day the release was FILED, typically the
# evening before it publishes (a 29 Jul release links ..._1-2026-7-28.pdf).
# Heathrow's half-year body cited SIX PDFs, all from prior months — one from the
# previous December — so an unwindowed match would ingest a stale document.
_PDF_DATE_LOOKBACK_DAYS = 2

# Refuse to store text that did not really extract. Diageo's prelims PDF uses a
# custom font encoding with no ToUnicode map and comes out as mush
# ("#   +0,=09/0/  @90  @2@>?"). PyMuPDF and pdfplumber return the same mush, so
# this is a property of the file, not of the library — there is no parser swap
# that rescues it. Stop-word density per 1k chars, measured: garbage 0.0, every
# good extraction in the sample 23-26. The threshold sits far from both.
_PDF_PROSE_WORDS = re.compile(
    r"\b(?:the|and|of|for|to|in|results|revenue|profit|year)\b", re.I
)
_PDF_PROSE_MIN_PER_1K = 5.0

# Observed results PDFs run 254KB-4.4MB; the cap is headroom, not a target.
_PDF_MAX_BYTES = 32 * 1024 * 1024
_PDF_TIMEOUT_S = 30

# The LSE PDF host sits behind Cloudflare and blips. L&G's half-year PDF returned
# a clean 200 (1.35MB), then HTTP 500 on the same URL twenty minutes later, then
# 200 again on every one of six retries. Because the backfill stamps
# body_fetched_at either way, a row that meets the blip keeps its pointer body
# forever — so a transient failure is worth a couple of seconds to retry in-run.
# Retried only on 5xx and network errors; a 404 or a malformed PDF is final.
_PDF_RETRY_BACKOFF_S = (2.0, 6.0)


def _lse_pdf_urls(body: str, published_at) -> list[str]:
    """LSE-hosted PDF links in `body` that belong to THIS announcement.

    Ordered by the filename's `_N` suffix rather than by length or document
    order: Aviva files `_1` (a 53k News Release carrying the CEO commentary and
    outlook) alongside `_2` (a 361k financial data pack). Longest-wins would
    take the tables and drop the narrative the ranker actually reads.
    """
    if not body or published_at is None:
        return []
    published = published_at.date() if hasattr(published_at, "date") else published_at
    found: dict[str, int] = {}
    for m in _LSE_PDF_RE.finditer(body):
        suffix, y, mo, d = m.groups()
        try:
            filed = date(int(y), int(mo), int(d))
        except ValueError:
            continue
        # A PDF filed after publication belongs to a later announcement; one
        # filed well before it is a back-reference, not this release.
        if not (published - timedelta(days=_PDF_DATE_LOOKBACK_DAYS) <= filed <= published):
            continue
        found.setdefault(m.group(0), int(suffix))
    return sorted(found, key=lambda u: (found[u], u))


def _looks_like_prose(text: str) -> bool:
    """True when extracted PDF text is readable English rather than mojibake."""
    if not text:
        return False
    hits = len(_PDF_PROSE_WORDS.findall(text))
    return 1000.0 * hits / len(text) >= _PDF_PROSE_MIN_PER_1K


def _pdf_download(url: str, timeout: int) -> bytes:
    """GET a PDF, retrying transient 5xx/network failures. See _PDF_RETRY_BACKOFF_S."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    attempts = len(_PDF_RETRY_BACKOFF_S)
    for attempt in range(attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(_PDF_MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            # 404/403 mean the document is not there for us; only server-side
            # faults are worth a second look.
            if e.code < 500 or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts:
                raise
        wait = _PDF_RETRY_BACKOFF_S[attempt]
        print(f"[rns] PDF fetch blipped, retrying in {wait:.0f}s ({attempt + 1}/{attempts}) — {url}")
        time.sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def _pdf_text(url: str, timeout: int = _PDF_TIMEOUT_S) -> Optional[str]:
    """Download one PDF and return its whitespace-collapsed text, or None."""
    raw = _pdf_download(url, timeout)
    if len(raw) > _PDF_MAX_BYTES:
        print(f"[rns] PDF exceeds {_PDF_MAX_BYTES} byte cap, skipping — {url}")
        return None
    import fitz  # deferred — only the ingest/scrape path needs PyMuPDF

    with fitz.open(stream=raw, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
    return re.sub(r"\s+", " ", text).strip() or None


def _body_from_pdf(body: str, published_at) -> Optional[str]:
    """Announcement text recovered from the PDF a pointer body links to.

    Returns None whenever the body we already have should be kept: no link, a
    link belonging to another announcement, a body that already carries the
    results, an unextractable PDF, a PDF no longer than the body, or a failed
    fetch. Non-fatal throughout by design — a pointer body is a valid capture,
    so nothing on this path may cost a row its ingest.
    """
    if not body or len(body) >= _BODY_PDF_MAX_BODY:
        return None
    for url in _lse_pdf_urls(body, published_at):
        try:
            text = _pdf_text(url)
        except Exception as e:  # network, HTTP, malformed PDF — all non-fatal
            print(f"[rns] PDF fetch failed (non-fatal) {url} — {e}")
            continue
        if not text:
            continue
        if not _looks_like_prose(text):
            print(f"[rns] PDF text failed the prose check, keeping body — {url}")
            continue
        if len(text) <= len(body):
            continue
        print(f"[rns] followed PDF {url} — body {len(body)} -> {len(text)} chars")
        return text
    return None


def _fetch_summary_and_body(url: str, timeout: int = 15) -> tuple[Optional[str], Optional[str]]:
    """Fetch one announcement page once and extract both the AI summary and
    the full announcement body text.

    Returns (summary, body) — either may be None (no AI summary on this wire,
    or no recognised body container on the page).
    """
    html = _urlopen_polite(url, timeout)
    from bs4 import BeautifulSoup  # deferred — only the ingest/scrape path needs it
    soup = BeautifulSoup(html, "html.parser")
    return _extract_summary(soup), _fetch_body(soup)


def _update_summary_and_body(
    ann_id: int,
    summary: Optional[str],
    body: Optional[str],
    body_chars: Optional[int],
    body_is_stub: Optional[bool],
) -> None:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE rns_announcements
            SET summary = %s, summary_fetched_at = NOW(),
                body = %s, body_chars = %s, body_fetched_at = NOW(),
                body_is_stub = %s
            WHERE id = %s
        """,
            (summary, body, body_chars, body_is_stub, ann_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# Consecutive throttled rows before we accept the host is blocking us wholesale
# and abort the run. 1 was too eager: a single URL that 403s while the host is
# otherwise healthy would abort every run forever, and because the queue is
# ordered published_at DESC and a failed row keeps body_fetched_at NULL, that
# row sits at the head of it permanently. Announcement 9713425 did exactly this
# from 2026-08-11 to 08-19 — eight days in which no row older than it could ever
# be backfilled. Costs one extra probe row against a genuine block: ~10s inside
# the urgent window (_URGENT_BACKOFF_CAP_S), ~50s outside it.
_RL_ABORT_STREAK = 2


def _mark_body_unavailable(ann_id: int) -> None:
    """Stamp body_fetched_at so a row that cannot be fetched leaves the queue.

    Deliberately touches ONLY body_fetched_at. The obvious alternative — reusing
    _update_summary_and_body with empty values — also nulls `summary` and
    restamps summary_fetched_at, and rows predating body capture already carry a
    perfectly good summary that the ranker still uses. Retiring a row must not
    cost us the text we do have.

    The row lands in the same state as any other extraction miss (fetched, no
    body), which rns.body_capture already counts and reports.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE rns_announcements SET body_fetched_at = NOW() WHERE id = %s",
            (ann_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _host_responds(timeout: int = 15) -> bool:
    """Is investegate serving us at all right now?

    The tie-breaker for a run whose only throttled row was also its only row:
    with no successful fetch to compare against, a 403 is ambiguous between "this
    URL is refused" and "we are blocked". One request to the feed index settles
    it. Only called when the run has no in-run evidence either way, so it costs
    nothing on a normal run.
    """
    try:
        _urlopen_polite(_BASE_URL, timeout)
        return True
    except Exception:
        return False


def _backfill_summaries(
    limit: int = 50, sleep_s: float = 1.5, tiers: tuple = ("A", "B")
) -> dict:
    """Fetch investegate AI summaries + full body text for recent tier A/B
    rows that lack one. Rate-limited by sleep_s between fetches. Feeds both
    the LLM ranker and the showcase vet with context.

    Keyed on body_fetched_at (not summary_fetched_at): every row ingested
    before the body-capture column existed already has summary_fetched_at
    set, so gating on that would never backfill their (missing) body. Keying
    on body_fetched_at catches both those rows and genuinely new ones in one
    pass — the same single fetch fills both columns regardless of which was
    already present.
    """
    rows = _query(
        """
        SELECT id, url, published_at
        FROM rns_announcements
        WHERE body_fetched_at IS NULL
          AND tier = ANY(%s)
        ORDER BY published_at DESC
        LIMIT %s
    """,
        (list(tiers), limit),
    )

    fetched = with_summary = missing = errors = 0
    with_body = stub = from_pdf = retired = 0
    rate_limited = False
    consecutive_rl = 0
    suspects: list[int] = []
    for r in rows:
        try:
            summary, body_raw = _fetch_summary_and_body(r["url"])
            body_stored = body_chars = None
            body_is_stub = None
            if body_raw:
                # Pointer bodies carry the dividend and the dial-in but not the
                # numbers; when they link the LSE-hosted PDF, that is the real
                # announcement. Swapped in BEFORE _truncate_body so the PDF text
                # flows through the same head+tail cap and every consumer
                # downstream — prompt, vet, body_is_stub, the 30-day prune — is
                # unchanged.
                pdf_body = _body_from_pdf(body_raw, r["published_at"])
                if pdf_body:
                    body_raw = pdf_body
                    from_pdf += 1
                body_stored, body_chars, body_is_stub = _truncate_body(body_raw)
                with_body += 1
                if body_is_stub:
                    stub += 1
            _update_summary_and_body(r["id"], summary, body_stored, body_chars, body_is_stub)
            fetched += 1
            # A success proves the host is serving us, so anything that was
            # refused earlier in this run was refused on its own merits.
            if suspects:
                for sid in suspects:
                    _mark_body_unavailable(sid)
                print(f"[rns] host is healthy — retired {len(suspects)} refused "
                      f"row(s) so they stop blocking the queue: {suspects}")
                retired += len(suspects)
                suspects = []
            consecutive_rl = 0
            if summary:
                with_summary += 1
            else:
                missing += 1
        except _RateLimited as e:
            # One refused row is NOT evidence the host is blocking us — see
            # _RL_ABORT_STREAK. Hold it as a suspect and try the next row: if
            # that one succeeds the suspect is retired, and if the whole streak
            # is refused we accept the block and stop. Only a run that ends with
            # suspects and no verdict leaves them pending, adjudicated below.
            errors += 1
            consecutive_rl += 1
            suspects.append(r["id"])
            if consecutive_rl >= _RL_ABORT_STREAK:
                print(f"[rns] RATE LIMITED {consecutive_rl}x consecutively — "
                      f"aborting summary backfill ({e})")
                rate_limited = True
                # Never retire during a block: these rows are almost certainly
                # fine and would lose their body permanently.
                suspects = []
                break
            print(f"[rns] throttled on {r['id']} — probing the next row before "
                  f"deciding whether the host is blocking us ({e})")
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[rns] summary fetch failed for {r['id']}: {e}")
            errors += 1
        time.sleep(sleep_s)

    # No row succeeded, so the loop never learned whether the host was the
    # problem. One request to the feed index decides it rather than leaving a
    # dead URL to block every future run.
    if suspects and not rate_limited:
        if _host_responds():
            for sid in suspects:
                _mark_body_unavailable(sid)
            print(f"[rns] feed index responds — retired {len(suspects)} refused "
                  f"row(s): {suspects}")
            retired += len(suspects)
        else:
            rate_limited = True
            print(f"[rns] feed index also refused — host is blocking us, "
                  f"leaving {len(suspects)} row(s) pending for the next run")
    result = {
        "candidates": len(rows),
        "fetched": fetched,
        "with_summary": with_summary,
        "missing": missing,
        "with_body": with_body,
        "body_stub": stub,
        "body_from_pdf": from_pdf,
        "errors": errors,
        "retired": retired,
        "rate_limited": rate_limited,
    }
    print(f"[rns] summary backfill done — {result}")
    return result


# ── API endpoints ─────────────────────────────────────────────────────────────


@router.get("/latest")
def get_latest(
    min_score: int = Query(40, ge=0, le=100),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(200, ge=1, le=5000),
    response: Response = None,
):
    """Recent announcements above min_score threshold, newest first.

    Includes market_cap from ttm_financials (DB) with a yfinance fallback for
    companies that don't have financial data stored yet.
    """
    # RNS lands intraday — a short edge cache collapses repeat polls/views.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=300"
    return _query(
        """
        SELECT r.id, r.published_at, r.wire, r.ticker, r.symbol, r.company_name,
               r.headline, r.url, r.tier, r.category, r.keyword_hits, r.score,
               r.llm_score, r.llm_confidence, r.llm_thesis, r.llm_action, r.llm_risks,
               r.llm_sentiment, r.llm_model, r.llm_processed_at, r.fetched_at,
               f.market_cap, m.ftse_index
        FROM rns_announcements r
        LEFT JOIN ttm_financials   f ON f.company_symbol = r.symbol
        LEFT JOIN company_metadata m ON m.symbol = r.symbol
        WHERE r.published_at >= NOW() - (%s || ' hours')::interval
          AND r.score >= %s
        ORDER BY r.published_at DESC
        LIMIT %s
    """,
        (str(hours), min_score, limit),
    )


@router.get("/significant")
def get_significant(hours: int = Query(24, ge=1, le=168), response: Response = None):
    """Tier-A-only feed: the morning 'must-read' list."""
    # RNS lands intraday — a short edge cache collapses repeat polls/views.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=300"
    return _query(
        """
        SELECT id, published_at, wire, ticker, symbol, company_name, headline,
               url, tier, category, keyword_hits, score
        FROM rns_announcements
        WHERE published_at >= NOW() - (%s || ' hours')::interval
          AND tier = 'A'
        ORDER BY score DESC, published_at DESC
    """,
        (str(hours),),
    )


@router.get("/by-symbol/{symbol}")
def get_by_symbol(symbol: str, limit: int = Query(50, ge=1, le=500), response: Response = None):
    """All announcements for one resolved symbol, newest first."""
    # RNS lands intraday — hold 15 min at the edge.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=900, stale-while-revalidate=3600"
    rows = _query(
        """
        SELECT id, published_at, wire, headline, url, tier, category, score
        FROM rns_announcements
        WHERE symbol = %s
        ORDER BY published_at DESC
        LIMIT %s
    """,
        (symbol, limit),
    )
    if not rows:
        raise HTTPException(404, "No announcements for this symbol")
    return rows


@router.post("/refresh", dependencies=[Depends(require_admin_token)])
def refresh(background_tasks: BackgroundTasks, max_pages: int = Query(7, ge=1, le=20)):
    """Kick off an ingest in the background."""
    background_tasks.add_task(_run_ingest, max_pages)
    return {"status": "ingest started", "max_pages": max_pages}


@router.post("/backfill-summaries", dependencies=[Depends(require_admin_token)])
def backfill_summaries(
    background_tasks: BackgroundTasks, limit: int = Query(50, ge=1, le=500)
):
    """Fetch investegate AI summaries for recent tier-A/B rows that lack one."""
    background_tasks.add_task(_backfill_summaries, limit)
    return {"status": "summary backfill started", "limit": limit}


# ── Market-cap cache (in-memory, 15 min TTL) ──────────────────────────────────

_MC_CACHE: dict[str, tuple[float, float]] = {}  # symbol -> (market_cap, timestamp)
_MC_CACHE_TTL = 900  # 15 minutes

# Symbols that Yahoo has told us don't exist (e.g. unresolved RNS tickers we
# guessed a ".L" suffix for). These are almost always permanently invalid
# (foreign CDIs, ETCs, bonds, AQSE-only names never onboarded into
# company_metadata) rather than a transient miss, so the TTL is long — a 6h
# window still means every one of them gets re-hit against Yahoo (and 404s)
# 4x/day forever. 30 days still self-heals if a ticker later gets onboarded,
# without the constant log spam.
_MC_FAIL_CACHE: dict[str, float] = {}  # symbol -> timestamp
_MC_FAIL_TTL = 30 * 86400  # 30 days


def _fetch_market_caps_batch(symbols: list[str]) -> dict[str, float]:
    """Fetch market caps from Yahoo Finance for a batch of symbols.

    Uses ThreadPoolExecutor for concurrency. Returns {symbol: market_cap}.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    now = time.time()
    result: dict[str, float] = {}

    # Check cache first
    uncached: list[str] = []
    for sym in symbols:
        if sym in _MC_CACHE and now - _MC_CACHE[sym][1] < _MC_CACHE_TTL:
            result[sym] = _MC_CACHE[sym][0]
        elif sym in _MC_FAIL_CACHE and now - _MC_FAIL_CACHE[sym] < _MC_FAIL_TTL:
            continue
        else:
            uncached.append(sym)

    if not uncached:
        return result

    def _fetch_one(sym: str) -> tuple[str, float | None]:
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info if ticker else {}
            mc = info.get("marketCap") if info else None
            return sym, mc
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in uncached}
        for future in as_completed(futures):
            sym, mc = future.result()
            if mc is not None:
                result[sym] = mc
                _MC_CACHE[sym] = (mc, now)
            else:
                _MC_FAIL_CACHE[sym] = now

    return result


@router.get("/market-caps")
def get_market_caps(
    hours: int = Query(72, ge=1, le=168),
    min_score: int = Query(0, ge=0, le=100),
    response: Response = None,
):
    """Fetch market caps for rows that don't have one in the DB yet.

    Returns a dict of {key: market_cap} where key is the symbol (e.g. ALBA.L)
    if available, otherwise the ticker (e.g. ALBA). The frontend uses
    `r.symbol || r.ticker` as the lookup key, so this matches.

    Uses Yahoo Finance with a ThreadPoolExecutor and in-memory cache.
    """
    # Intraday data and the miss path does per-symbol yfinance calls — a short
    # edge cache collapses repeat requests and saves those fetches.
    if response is not None:
        response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=300"
    # Find rows in the window that are missing market_cap in ttm_financials.
    # Two cases:
    #   1. symbol IS NOT NULL but no matching ttm_financials row
    #   2. symbol IS NULL (ticker not resolved in company_metadata) — use ticker
    rows = _query(
        """
        SELECT DISTINCT
            COALESCE(r.symbol, r.ticker) AS lookup_key,
            r.symbol,
            r.ticker
        FROM rns_announcements r
        LEFT JOIN ttm_financials f ON f.company_symbol = r.symbol
        WHERE r.published_at >= NOW() - (%s || ' hours')::interval
          AND r.score >= %s
          AND r.ticker IS NOT NULL
          AND f.market_cap IS NULL
        LIMIT 100
    """,
        (str(hours), min_score),
    )

    if not rows:
        return {}

    # Build the list of Yahoo Finance symbols to fetch.
    # For rows with a resolved symbol (e.g. KIE.L) use it directly.
    # For rows with only a ticker (e.g. ALBA), append .L
    yahoo_symbols: list[str] = []
    key_to_yahoo: dict[str, str] = {}
    for r in rows:
        key = r["lookup_key"]
        if not key:
            continue
        if r["symbol"]:
            yahoo_sym = r["symbol"]
        else:
            # Ticker-only: strip trailing dots and append .L
            ticker = r["ticker"].rstrip(".")
            yahoo_sym = f"{ticker}.L"
        yahoo_symbols.append(yahoo_sym)
        key_to_yahoo[key] = yahoo_sym

    mc_map = _fetch_market_caps_batch(yahoo_symbols)

    # Re-key the result using the original lookup_key (symbol or ticker)
    # so the frontend can find it with r.symbol || r.ticker
    result: dict[str, float] = {}
    for key, yahoo_sym in key_to_yahoo.items():
        if yahoo_sym in mc_map:
            result[key] = mc_map[yahoo_sym]

    return result


@router.get("/pipeline/status")
def pipeline_status():
    """Report ingest health derived from the DB.

    The pipeline runs as a separate cron process (run_rns.py), not in this API
    process, so there is no in-memory run state to report. Instead we surface
    the freshest stored data — last fetch, last publish, and 24h counts — which
    reflects pipeline health regardless of which process did the ingest.
    """
    rows = _query(
        """
        SELECT
            MAX(fetched_at)                                            AS last_fetched_at,
            MAX(published_at)                                          AS last_published_at,
            COUNT(*) FILTER (WHERE published_at >= NOW() - INTERVAL '24 hours') AS count_24h,
            COUNT(*) FILTER (
                WHERE published_at >= NOW() - INTERVAL '24 hours' AND tier = 'A'
            )                                                          AS tier_a_24h
        FROM rns_announcements
    """
    )
    stats = rows[0] if rows else {}
    last_fetched = stats.get("last_fetched_at")
    age_minutes = (
        (datetime.now(_UK_TZ) - last_fetched).total_seconds() / 60
        if last_fetched
        else None
    )
    return {
        "last_fetched_at": last_fetched,
        "last_published_at": stats.get("last_published_at"),
        "fetch_age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "count_24h": stats.get("count_24h", 0),
        "tier_a_24h": stats.get("tier_a_24h", 0),
    }
