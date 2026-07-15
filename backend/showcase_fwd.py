"""Forward valuation multiple for High Impact RNS showcase entries.

The one hard rule here: the LLM never does arithmetic. It extracts a profit
figure the announcement STATES (guidance, a consensus footnote, or a reported
full-year actual) as structured fields plus a verbatim quote; Python then
computes EV (market_cap + net_debt from ttm_financials) and the multiple,
applying gates for every failure mode the 2026-07-08 feasibility study actually
observed in the wild:

  - non-GBP figures (Boku/Craneware guide in USD, Cairn in EUR) — dropped, no FX
    here, matching the fair-value module's deliberate no-FX stance;
  - part-year figures (H1 trading updates) and odd period lengths (Orchard's
    18-month FY, Venture Life's 17-month) — only ~12-month periods pass;
  - banks/insurers/trusts, where EV is meaningless — dropped entirely;
    Real Estate is dropped for EV-based metrics (book/NAV-valued);
  - "materially ahead of consensus £X" — the multiple against X is kept but
    flagged as an upper bound (fwd_is_bound);
  - degenerate results — the multiple must land in a sane 1-60x band.

Extraction reads the FULL announcement text fetched live from Investegate, not
the stored AI summary: the study found consensus footnotes ("market
expectations were... EBITDA £15.0m") survive only in the full text. The page is
fetched at flag time while the announcement is fresh; the summary is the
fallback when the fetch fails.

Everything returns None-shaped results rather than raising — a missing multiple
must never block a showcase flag (same contract as the advisory vet).
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Optional

# Metrics we can turn into a defensible multiple. EBITDA/EBIT divide into EV;
# PBT is post-interest so it divides into market cap instead (labelled P/PBT).
_EV_METRICS = ("ebitda", "ebit")
_METRICS = _EV_METRICS + ("pbt",)
_BASES = ("guidance", "consensus", "actual")

# Sanity band for the computed multiple. Outside it the stated figure and our
# EV almost certainly aren't on the same planet (unit slip, wrong period,
# degenerate denominator) — show nothing rather than a wrong number.
_MIN_MULTIPLE = 1.0
_MAX_MULTIPLE = 60.0

# Accept only ~annual periods; guidance for "the year ending ..." is 12 months
# but companies with odd year-ends report 17/18-month periods often enough
# that the study hit two in a 118-row sample.
_PERIOD_MONTHS_RANGE = (11, 13)

_FWD_FIELDS = (
    "fwd_metric", "fwd_value", "fwd_currency", "fwd_period", "fwd_basis",
    "fwd_is_bound", "fwd_quote", "fwd_ev", "fwd_multiple", "fwd_model",
    "fwd_processed_at",
)


def _empty(model: Optional[str] = None, processed: bool = True) -> dict:
    """All-None field dict. `processed=False` leaves fwd_processed_at NULL so
    a transient failure (API down, fetch error) stays eligible for the
    /extract-fwd backfill — only a completed extraction gets stamped."""
    out = {k: None for k in _FWD_FIELDS}
    out["fwd_model"] = model
    out["fwd_processed_at"] = datetime.now(timezone.utc) if processed else None
    return out


# ── Full-text fetch ───────────────────────────────────────────────────────────
def fetch_announcement_text(url: str, timeout: int = 20, max_chars: int = 15000) -> Optional[str]:
    """Fetch the announcement page and return its body text, or None.

    Investegate renders the announcement text inside div.fr-view-element
    (their rich-text viewer), which sits in div.news-window; both checked
    2026-07-08 against live pages. The wider .news-window fallback would also
    sweep in the page's own headline furniture — harmless for extraction.
    """
    if not url:
        return None
    from rns import _USER_AGENT  # deferred: rns pulls in bs4 etc.

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    node = (
        soup.find("div", class_="fr-view-element")
        or soup.find("div", class_="news-window")
        or soup.find("article")
    )
    if node is None:
        return None
    text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    return text[:max_chars] or None


# ── Extraction (LLM: copy figures out, nothing else) ──────────────────────────
def _extract_messages(cand: dict, text: str) -> list[dict]:
    system = (
        "You extract stated profit figures from UK RNS announcements for a "
        "valuation database. You NEVER calculate, derive, combine, annualise or "
        "recall figures — you only copy numbers that are explicitly stated in "
        "the text you are given. Deriving a profit from revenue and a margin, "
        "doubling a half-year figure, or filling a gap from memory of the "
        "company are all forbidden. If no qualifying figure is stated, say so. "
        "Return STRICT JSON only."
    )
    user = f"""Announcement
  Company:  {cand.get('company_name') or '?'} ({cand.get('symbol') or '?'})
  Headline: {cand.get('headline')}

Full text
{text}

Find the best FULL-YEAR profit-level figure stated in the text, choosing by:
  1. metric: prefer EBITDA, then EBIT/operating profit, then profit before tax.
     Adjusted/underlying versions count. Revenue, NAV, net fee income, EPS,
     dividends and cash figures do NOT count.
  2. period: prefer the current or next full financial year over a completed
     one. A half-year or quarterly figure only qualifies if nothing full-year
     is stated — report it honestly with its period_months.
  3. source: the company's own guidance, or market expectations/consensus
     quoted in the text (often a footnote), or a reported actual result.

Return a JSON object with exactly these fields:
  found          boolean — false if no qualifying profit figure is stated
  metric         "ebitda" | "ebit" | "pbt"
  value_low_m    number — the figure in MILLIONS of its stated currency; for a
                 range ("38-42m") the LOW end; for "at least X" / "not less
                 than X", X itself
  value_high_m   number or null — the high end of a range, else null
  currency       "GBP" | "USD" | "EUR" | the ISO code stated
  period_label   short label, e.g. "FY2026" or "H1 2026"
  period_months  integer — how many months the figure covers (12 = full year)
  source         "guidance" | "consensus" | "actual"
  relation       "eq" (stated as-is / approximately) | "min" ("at least X") |
                 "above" (results expected to be AHEAD of this consensus figure)
  quote          the verbatim sentence(s) the figure appears in, copied exactly

If found is false, every other field must be null.
Return JSON only — no preamble, no code fence."""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _run_extraction(cand: dict, text: str) -> tuple[Optional[dict], str]:
    """One DeepSeek call → (parsed extraction dict or None, model id)."""
    from rns_llm import _get_client, _DEEPSEEK_MODEL, _THINKING_OFF

    client = _get_client()
    resp = client.chat.completions.create(
        model=_DEEPSEEK_MODEL,
        messages=_extract_messages(cand, text),
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=400,
        extra_body=_THINKING_OFF,
    )
    result = json.loads(resp.choices[0].message.content)
    return (result if isinstance(result, dict) else None), _DEEPSEEK_MODEL


# ── Gates + arithmetic (Python only) ──────────────────────────────────────────
def _sector_model(cand: dict) -> str:
    """bank | insurer | trust | financial | other — the showcase only needs the
    coarse split; mirrors main._classify_risk_model's financial branches."""
    sector = (cand.get("sector") or "").lower()
    industry = (cand.get("industry") or "").lower()
    if not sector and not industry:
        return "trust"  # Yahoo gives funds/trusts no sector/industry
    if "bank" in industry or "bank" in sector:
        return "bank"
    if "insur" in industry or "insurance" in sector:
        return "insurer"
    if "financ" in sector:
        return "financial"
    return "other"


def _as_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def compute_fwd_multiple(extract: dict, cand: dict, model: str) -> dict:
    """Validate an extraction and compute the multiple. Returns the full
    fwd_* field dict; fwd_multiple is None whenever any gate fails, but the
    extraction itself (metric/value/quote) is still stored for audit."""
    out = _empty(model)
    if not extract or not extract.get("found"):
        return out

    metric = (extract.get("metric") or "").lower().strip()
    currency = (extract.get("currency") or "").upper().strip()
    basis = (extract.get("source") or "").lower().strip()
    relation = (extract.get("relation") or "").lower().strip()
    value_m = _as_float(extract.get("value_low_m"))
    months = extract.get("period_months")
    quote = (extract.get("quote") or "").strip()[:600] or None

    # Store what was extracted regardless of whether a multiple survives —
    # the quote is the audit trail and the currency/period explain a blank.
    out.update({
        "fwd_metric": metric if metric in _METRICS else None,
        "fwd_currency": currency or None,
        "fwd_period": (extract.get("period_label") or "").strip()[:40] or None,
        "fwd_basis": basis if basis in _BASES else None,
        "fwd_quote": quote,
        "fwd_value": value_m * 1e6 if value_m is not None else None,
    })

    # Gates — each one is a failure mode seen in the feasibility sample.
    if metric not in _METRICS or basis not in _BASES or value_m is None:
        return out
    if value_m <= 0:
        return out
    if currency != "GBP":
        return out  # no FX conversion here, by design (matches fair value)
    if not quote or not isinstance(months, (int, float)):
        return out
    if not (_PERIOD_MONTHS_RANGE[0] <= months <= _PERIOD_MONTHS_RANGE[1]):
        return out

    sm = _sector_model(cand)
    if sm in ("bank", "insurer", "trust"):
        return out  # EV and PBT multiples alike are junk for these

    mkt = _as_float(cand.get("market_cap"))
    if mkt is None or mkt <= 0:
        return out

    if metric in _EV_METRICS:
        # REITs/property are book-valued — EV/EBITDA misleads there.
        if (cand.get("sector") or "") == "Real Estate":
            return out
        numerator = mkt + (_as_float(cand.get("net_debt")) or 0.0)
    else:  # pbt — post-interest, so equity numerator
        numerator = mkt
    if numerator <= 0:
        return out

    multiple = numerator / (value_m * 1e6)
    if not (_MIN_MULTIPLE <= multiple <= _MAX_MULTIPLE):
        return out

    out["fwd_ev"] = numerator
    out["fwd_multiple"] = round(multiple, 2)
    # "ahead of consensus £X" → true multiple on the eventual figure is LOWER
    # than X's, so what we show is an upper bound. "at least X" guidance too.
    out["fwd_is_bound"] = relation in ("above", "min")
    return out


# ── Orchestrator ──────────────────────────────────────────────────────────────
def extract_fwd_fields(cand: dict) -> dict:
    """Fetch text, extract, gate, compute. Never raises; on any failure the
    fields come back None-shaped so the caller can store them as-is.

    `cand` needs: url, headline, symbol, company_name, summary (fallback text),
    sector, industry, market_cap, net_debt.
    """
    try:
        text = None
        try:
            text = fetch_announcement_text(cand.get("url"))
        except Exception as e:
            print(f"[showcase-fwd] full-text fetch failed for {cand.get('symbol')} (non-fatal) — {e}")
        if not text:
            text = cand.get("summary")
        if not text:
            return _empty()

        extract, model = _run_extraction(cand, text)
        return compute_fwd_multiple(extract, cand, model)
    except Exception as e:
        print(f"[showcase-fwd] extraction failed for {cand.get('symbol')} (non-fatal) — {e}")
        return _empty(processed=False)
