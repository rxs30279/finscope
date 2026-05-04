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
from datetime import datetime
from typing import Optional

from zoneinfo import ZoneInfo

_UK_TZ = ZoneInfo("Europe/London")

import psycopg2
import psycopg2.extras
import psycopg2.pool
from bs4 import BeautifulSoup
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/rns", tags=["rns"])


# ── DB (own pool) ─────────────────────────────────────────────────────────────

_DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **_DB_CONFIG)
    return _pool


def _query(sql, params=None):
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


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
            "interim report",
            "half year results",
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
    (
        "possible_offer",
        "A",
        ("rule-2.4", "rule-2-4", "rule 2.4", "possible-offer", "possible offer"),
    ),
    (
        "recommended_offer",
        "A",
        ("recommended-offer", "recommended-cash-offer", "recommended offer"),
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
            "annual financial report",
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
            category = cat
            tier = t
            break

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

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_BASE_URL = "https://www.investegate.co.uk"

# Investegate URL: /announcement/{wire}/{company-slug}--{ticker}/{headline-slug}/{id}
_ANN_URL_RE = re.compile(r"/announcement/([^/]+)/[^/]+--([^/]+)/([^/]+)/(\d+)")


def _fetch_page(page: int = 1, timeout: int = 20) -> str:
    """Fetch one list page of the investegate announcement feed."""
    url = _BASE_URL + ("/" if page == 1 else f"/?page={page}")
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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


def _prune_old(days: int = 14) -> dict:
    """Hard-delete rns_announcements older than `days` (by published_at).

    Keeps storage bounded — RNS volume is a few hundred rows/day and the UI
    only ever reads the most recent window, so older rows have no value.
    """
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM rns_announcements WHERE published_at < NOW() - (%s || ' days')::interval",
            (str(days),),
        )
        deleted = cur.rowcount
        return {"deleted": deleted, "older_than_days": days}
    finally:
        pool.putconn(conn)


def _run_ingest(
    max_pages: int = 7, stop_on_known: bool = True, sleep_s: float = 2.0
) -> dict:
    """Fetch up to max_pages of the feed, classify, and upsert.

    If stop_on_known is True, stops early once a whole page produced no new rows.
    """
    processed = inserted = updated = errors = 0
    for page in range(1, max_pages + 1):
        try:
            html = _fetch_page(page)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[rns] page {page} fetch failed: {e}")
            errors += 1
            break
        raws = _parse_rows(html)
        if not raws:
            print(f"[rns] page {page}: no rows parsed")
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
            break
        if page < max_pages:
            time.sleep(sleep_s)
    result = {
        "processed": processed,
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
    }
    print(f"[rns] ingest done — {result}")
    return result


# ── Summary scraper (investegate AI summary) ──────────────────────────────────


def _fetch_summary(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch one announcement page and extract the #collapseSummary text.

    Returns stripped summary text, or None if the page has no AI summary.
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id="collapseSummary")
    if node is None:
        return None
    # The disclaimer link is a child <p> — drop it before extracting text.
    for p in node.find_all("p", id="summary-disclaimer"):
        p.decompose()
    text = node.get_text(" ", strip=True)
    return text or None


def _update_summary(ann_id: int, summary: Optional[str]) -> None:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE rns_announcements
            SET summary = %s, summary_fetched_at = NOW()
            WHERE id = %s
        """,
            (summary, ann_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _backfill_summaries(
    limit: int = 50, sleep_s: float = 1.5, tiers: tuple = ("A", "B")
) -> dict:
    """Fetch investegate AI summaries for recent tier A/B rows that lack one.

    Rate-limited by sleep_s between fetches. Feeds the LLM ranker with context.
    """
    rows = _query(
        """
        SELECT id, url
        FROM rns_announcements
        WHERE summary_fetched_at IS NULL
          AND tier = ANY(%s)
        ORDER BY published_at DESC
        LIMIT %s
    """,
        (list(tiers), limit),
    )

    fetched = with_summary = missing = errors = 0
    for r in rows:
        try:
            summary = _fetch_summary(r["url"])
            _update_summary(r["id"], summary)
            fetched += 1
            if summary:
                with_summary += 1
            else:
                missing += 1
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[rns] summary fetch failed for {r['id']}: {e}")
            errors += 1
        time.sleep(sleep_s)
    result = {
        "candidates": len(rows),
        "fetched": fetched,
        "with_summary": with_summary,
        "missing": missing,
        "errors": errors,
    }
    print(f"[rns] summary backfill done — {result}")
    return result


# ── API endpoints ─────────────────────────────────────────────────────────────


@router.get("/latest")
def get_latest(
    min_score: int = Query(40, ge=0, le=100),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(200, ge=1, le=1000),
):
    """Recent announcements above min_score threshold, newest first.

    Includes market_cap from ttm_financials (DB) with a yfinance fallback for
    companies that don't have financial data stored yet.
    """
    return _query(
        """
        SELECT r.id, r.published_at, r.wire, r.ticker, r.symbol, r.company_name,
               r.headline, r.url, r.tier, r.category, r.keyword_hits, r.score,
               r.llm_score, r.llm_confidence, r.llm_thesis, r.llm_action, r.llm_risks,
               r.llm_model, r.llm_processed_at, r.fetched_at,
               f.market_cap
        FROM rns_announcements r
        LEFT JOIN ttm_financials f ON f.company_symbol = r.symbol
        WHERE r.published_at >= NOW() - (%s || ' hours')::interval
          AND r.score >= %s
        ORDER BY r.published_at DESC
        LIMIT %s
    """,
        (str(hours), min_score, limit),
    )


@router.get("/significant")
def get_significant(hours: int = Query(24, ge=1, le=168)):
    """Tier-A-only feed: the morning 'must-read' list."""
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
def get_by_symbol(symbol: str, limit: int = Query(50, ge=1, le=500)):
    """All announcements for one resolved symbol, newest first."""
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


@router.post("/refresh")
def refresh(background_tasks: BackgroundTasks, max_pages: int = Query(7, ge=1, le=20)):
    """Kick off an ingest in the background."""
    background_tasks.add_task(_run_ingest, max_pages)
    return {"status": "ingest started", "max_pages": max_pages}


@router.post("/backfill-summaries")
def backfill_summaries(
    background_tasks: BackgroundTasks, limit: int = Query(50, ge=1, le=500)
):
    """Fetch investegate AI summaries for recent tier-A/B rows that lack one."""
    background_tasks.add_task(_backfill_summaries, limit)
    return {"status": "summary backfill started", "limit": limit}


@router.get("/market-caps")
def get_market_caps(
    hours: int = Query(72, ge=1, le=168),
    min_score: int = Query(0, ge=0, le=100),
):
    """Fetch market caps for rows that don't have one in the DB yet.

    Returns a dict of {ticker_or_symbol: market_cap} for rows in the given
    window that are missing market_cap. The frontend calls this after the
    initial page load to fill in the column without blocking the main query.

    Currently returns {} — market caps come from the DB (ttm_financials) or
    are filled client-side. Yahoo Finance lookups were removed because they
    caused timeouts on the server.
    """
    return {}


@router.get("/pipeline/status")
def pipeline_status():
    """Return the status of the last pipeline run."""
    return _pipeline_state
