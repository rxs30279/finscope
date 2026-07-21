"""Daily RNS digest email.

Reads the last 24h of Tier A + B announcements from the existing
rns_announcements table, drops sub-£15m / unpriceable names, and emails an
HTML digest via Resend. Strictly
read-only — does not trigger ingest, summary fetching, or DeepSeek ranking.
The pipeline that populates llm_* columns runs on its own GitHub Actions
schedule (refresh-rns.yml).

Recipients come from a Resend Segment (`RESEND_SEGMENT_ID`). If unset,
falls back to the single `DIGEST_TO` address — useful for local dev and
as a safety net during rollout. Each email carries RFC 8058 one-click
List-Unsubscribe headers + a visible footer link.

Environment:
  RESEND_API_KEY        — required, https://resend.com/api-keys
  RESEND_SEGMENT_ID     — optional; if set, send to all active contacts
  UNSUBSCRIBE_SECRET    — required when segment mode is on (HMAC secret)
  PUBLIC_BASE_URL       — public app URL used in unsub links (e.g. https://...)
  DIGEST_TO             — fallback single recipient (used only when no segment)
  DIGEST_FROM           — sender   (default: digest@alphamoveai.co.uk)
  DIGEST_SEND_GAP_SECONDS        — min seconds between sends to the SAME mailbox
                                   provider (default 2; 0 disables pacing)
  DIGEST_SEND_GAP_BUDGET_SECONDS — cap on total time spent pacing (default 45)
  DB_*                  — same vars as the rest of the backend
"""
import sys, os
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import json
import html
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from rns import _query, _fetch_market_caps_batch
# Shared with the delivery-event webhook so the domain→provider mapping has one
# definition. Both sides must agree: pacing groups by it, and the /status panel
# reports deferral rates by it — a drift would make the fix and the measurement
# disagree about who "Microsoft" is.
from email_events import provider_of


_UK_TZ      = ZoneInfo("Europe/London")
_WINDOW_H   = 24
_MIN_MARKET_CAP = 15_000_000   # drop stories below £15m (and any with no determinable cap)
# Public app URL for company-page links; mirrors the frontend seo.ts default.
_SITE_URL   = (os.environ.get("PUBLIC_BASE_URL") or "https://app.alphamoveai.co.uk").rstrip("/")
_DEFAULT_FROM = "Alpha Move AI <digest@alphamoveai.co.uk>"
_KOFI_URL   = "https://ko-fi.com/alphamoveai"  # same page the in-app Support button links to


# ── Data ──────────────────────────────────────────────────────────────────────

def _fetch_rows(hours: int = _WINDOW_H) -> list[dict]:
    """Tier A + B in the last `hours`. AI-ranked rows first (by llm_score),
    then unranked by published_at desc. Mirrors the RnsTab default sort.

    Joins company_metadata for `ftse_index` (used to bucket rows into
    large/mid/small-cap sections) and ttm_financials for `market_cap`
    (shown inline next to the ticker). For rows missing ttm_financials
    coverage (mostly AIM / FTSE SmallCap), falls back to a parallel
    yfinance batch fetch — same helper rns_llm and /api/rns/market-caps
    use. Rows below `_MIN_MARKET_CAP` (or with no determinable cap) are
    then dropped."""
    rows = _query("""
        SELECT r.id, r.published_at, r.ticker, r.symbol, r.company_name,
               r.headline, r.url, r.tier, r.category, r.keyword_hits,
               r.score, r.llm_score, r.llm_thesis, r.llm_action, r.llm_risks,
               r.llm_sentiment, m.ftse_index, f.market_cap
          FROM rns_announcements r
          LEFT JOIN company_metadata m ON m.symbol = r.symbol
          LEFT JOIN ttm_financials   f ON f.company_symbol = r.symbol
         WHERE r.tier IN ('A', 'B')
           AND r.published_at >= NOW() - (%s || ' hours')::interval
         ORDER BY (r.llm_score IS NULL),  -- ranked first
                  r.llm_score   DESC NULLS LAST,
                  r.published_at DESC
         LIMIT 200
    """, (str(hours),))

    _backfill_market_caps(rows)

    # Drop micro-caps and anything we couldn't price at all.
    kept: list[dict] = []
    for r in rows:
        mc = r.get("market_cap")
        if mc is None:
            continue
        try:
            if float(mc) >= _MIN_MARKET_CAP:
                kept.append(r)
        except (TypeError, ValueError):
            continue
    return kept


def _count_all_rns(hours: int = _WINDOW_H) -> int:
    """Total RNS announcements in the window across *all* tiers — the
    denominator for the header's 'AI-ranked: X/Y' stat."""
    rows = _query("""
        SELECT COUNT(*) AS n
          FROM rns_announcements
         WHERE published_at >= NOW() - (%s || ' hours')::interval
    """, (str(hours),))
    return int(rows[0]["n"]) if rows else 0


def _backfill_market_caps(rows: list[dict]) -> None:
    """Mutate `rows` in place: for any row with market_cap=None, try Yahoo.

    Best-effort — failures (network errors, missing tickers) are swallowed
    so the digest still sends without crashing."""
    missing: list[dict] = [
        r for r in rows
        if r.get("market_cap") is None and (r.get("symbol") or r.get("ticker"))
    ]
    if not missing:
        return

    yahoo_for: dict[int, str] = {}
    for r in missing:
        if r.get("symbol"):
            yahoo_for[id(r)] = r["symbol"]
        else:
            yahoo_for[id(r)] = f"{r['ticker'].rstrip('.')}.L"

    try:
        mc_map = _fetch_market_caps_batch(list(set(yahoo_for.values())))
    except Exception as e:
        print(f"[digest] yfinance market-cap backfill failed: {e}")
        return

    for r in missing:
        sym = yahoo_for.get(id(r))
        if sym and sym in mc_map:
            r["market_cap"] = mc_map[sym]


# ── Market-cap bucketing ──────────────────────────────────────────────────────

# Three sections. FTSE 100/250 map directly; everything else falls back to
# market cap because the universe now includes non-index names (LSE screen,
# migration 017) where a £10B WISE would otherwise land in Small. Thresholds
# approximate the FTSE 250 cap range. FTSE SmallCap / AIM 100 stay Small by
# construction (both sit under ~£1.5B).
# The floors and index carve-outs are mirrored in frontend/src/components/
# RnsTab.js (LARGE_CAP_FLOOR / MID_CAP_FLOOR) — keep the two in sync.
_CAP_BUCKETS = ("large", "mid", "small")
_CAP_META = {
    "large": {"label": "Large Cap", "sub": "FTSE 100 / £4bn+", "color": "#f97316"},
    "mid":   {"label": "Mid Cap",   "sub": "FTSE 250",         "color": "#60a5fa"},
    "small": {"label": "Small Cap", "sub": "SmallCap / AIM / other", "color": "#6b7280"},
}
_LARGE_CAP_FLOOR = 4_000_000_000
_MID_CAP_FLOOR = 350_000_000


def _cap_bucket(row: dict) -> str:
    idx = row.get("ftse_index")
    if idx == "FTSE 100":
        return "large"
    if idx == "FTSE 250":
        return "mid"
    if idx in ("FTSE SmallCap", "FTSE AIM 100"):
        return "small"
    try:
        mc = float(row.get("market_cap") or 0)
    except (TypeError, ValueError):
        mc = 0
    if mc >= _LARGE_CAP_FLOOR:
        return "large"
    if mc >= _MID_CAP_FLOOR:
        return "mid"
    return "small"


def _format_mc(mc) -> str:
    """Render market cap as a short string (£1.2bn / £480m / £52m)."""
    if mc is None:
        return ""
    try:
        v = float(mc)
    except (TypeError, ValueError):
        return ""
    if v >= 1e9:
        return f"£{v / 1e9:.1f}bn"
    if v >= 1e6:
        return f"£{v / 1e6:.0f}m"
    if v >= 1e3:
        return f"£{v / 1e3:.0f}k"
    return f"£{v:.0f}"


# ── HTML rendering ────────────────────────────────────────────────────────────

# ── Sentiment signal (ported verbatim from frontend RnsTab.js getSentiment) ────
_NEG_CATS = {
    "profit_warning", "going_concern", "liquidation", "delisting", "suspension",
}
_POS_CATS = {
    "firm_offer", "recommended_offer", "drug_approval", "contract_win",
}
# Keep in sync with showcase.py / RnsTab.js — edit all three together.
# "upgrad"/"downgrad"/"dilut"/"deteriorat" are stems (whole words never
# substring-match "upgrading"/"dilutive"/"deteriorating"). This scan is the
# fallback for rows ranked before llm_sentiment existed (migration 012).
_LLM_POS = ["positive", "upside", "beat", "above expectations", "outperform",
            "upgrad", "bullish", "boost", "opportunity", "record",
            "ahead of expectations", "ahead of consensus", "ahead of guidance",
            "swing to profit", "above consensus", "accretive", "surge",
            "de-risk", "unlock", "exceed", "better than expected",
            "at a premium", "significant premium", "higher offer",
            "re-rate", "re-rating"]
_LLM_NEG = ["negative", "pressure", "miss", "below expectations", "concern",
            "decline", "downgrad", "disappoint", "warning", "bearish", "weak",
            "dilut", "solvency", "distress", "slash", "headwind", "shortfall",
            "deteriorat", "impairment", "write-down", "write down",
            "below consensus", "below guidance", "collapse", "downside",
            "net loss", "suspend", "cash crunch", "deeply discounted"]

_SENTIMENT_STYLE = {
    "positive": ("▲", "#10b981"),
    "negative": ("▼", "#ef4444"),
    "neutral":  ("—", "#60a5fa"),
}


def _sentiment(r: dict) -> str:
    """Directional read on an announcement — matches the web RNS table.
    Layer 1: unambiguous category overrides. Layer 1.5: the ranker's own
    stored sentiment. Layer 2: scan the LLM thesis for directional language.
    Layer 3: fall back to keyword_hits tallies."""
    # Layer 1: category overrides
    if r.get("category") in _NEG_CATS:
        return "negative"
    if r.get("category") in _POS_CATS:
        return "positive"

    # Layer 1.5: the ranker read the full announcement — trust its direction
    # over any keyword scan of its prose. NULL on rows ranked pre-migration-012.
    llm_sent = (r.get("llm_sentiment") or "").lower()
    if llm_sent in ("positive", "negative", "neutral"):
        return llm_sent

    # Layer 2: LLM thesis language
    thesis = r.get("llm_thesis")
    if thesis:
        text = thesis.lower()
        pos = sum(1 for w in _LLM_POS if w in text)
        neg = sum(1 for w in _LLM_NEG if w in text)
        if neg > pos:
            return "negative"
        if pos > neg:
            return "positive"

    # Layer 3: keyword hits fallback
    hits = r.get("keyword_hits") or []
    neg = sum(1 for h in hits if h.startswith("neg:"))
    pos = sum(1 for h in hits if h.startswith("pos:"))
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def _render_sentiment(r: dict) -> str:
    symbol, color = _SENTIMENT_STYLE[_sentiment(r)]
    return (
        f'<span style="color:{color};font-family:monospace;'
        f'font-size:15px;font-weight:700;line-height:1;">{symbol}</span>'
    )


def _company_url(r: dict) -> str:
    """Company link for a row's ticker.

    In-universe rows (symbol resolved against company_metadata at ingest) link
    to our company page, mirroring the frontend tickerSlug(): strip the '.L'
    suffix, upper-case, URL-encode (e.g. TSCO.L -> /company/TSCO).

    Rows with a NULL symbol never resolved — the company isn't in our universe
    and its page would render empty, so link out to Yahoo Finance instead
    (same TICKER.L construction the market-cap backfill uses)."""
    sym = (r.get("symbol") or "").strip()
    if not sym:
        ticker = (r.get("ticker") or "").strip()
        yahoo = f"{ticker.rstrip('.').upper()}.L" if ticker else ""
        return f"https://finance.yahoo.com/quote/{urllib.parse.quote(yahoo)}"
    slug = sym[:-2] if sym.upper().endswith(".L") else sym
    return f"{_SITE_URL}/company/{urllib.parse.quote(slug.upper())}"


_ACTION_COLOR = {
    "research": "#f97316",
    "watch":    "#60a5fa",
    "ignore":   "#888888",
}
_CATEGORY_LABELS = {
    "profit_warning":    "Profit Warning",
    "trading_update":    "Trading Update",
    "final_results":     "Final Results",
    "interim_results":   "Interim Results",
    "quarterly":         "Quarterly",
    "firm_offer":        "Firm Offer (2.7)",
    "possible_offer":    "Possible Offer (2.4)",
    "recommended_offer": "Recommended Offer",
    "strategic_review":  "Strategic Review",
    "suspension":        "Suspension",
    "going_concern":     "Going Concern",
    "liquidation":       "Liquidation",
    "delisting":         "Delisting",
    "response_to":       "Response to Press",
    "capital_markets":   "Capital Markets Day",
    "capital_raise":     "Capital Raise",
    "acquisition":       "Acquisition",
    "disposal":          "Disposal",
    "contract_win":      "Contract / Partnership",
    "board_change":      "Board Change",
    "drug_approval":     "Drug Approval",
    "clinical_trial":    "Clinical Trial",
    "drill_results":     "Drill Results",
    "dividend_change":   "Dividend Change",
    "update_statement":  "Operational Update",
}


def _esc(v) -> str:
    return html.escape(str(v)) if v is not None else "—"


def _fmt_uk_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_UK_TZ).strftime("%H:%M")


def _render_row(r: dict) -> str:
    """Renders BOTH the desktop table row AND the mobile card for one item.
    Each is wrapped in a class that the media query toggles between
    display:none and display:table-row / display:block."""
    action   = r.get("llm_action") or ""
    action_c = _ACTION_COLOR.get(action, "#888")
    category = _CATEGORY_LABELS.get(r.get("category"), r.get("category") or "—")
    time_s   = _fmt_uk_time(r['published_at'])

    # ── shared snippets ──
    thesis_block = ""
    if r.get("llm_thesis"):
        thesis_block = (
            f'<div style="margin-top:6px;color:#555;font-size:12px;line-height:1.4;">'
            f'{_esc(r["llm_thesis"])}'
        )
        if r.get("llm_risks"):
            thesis_block += (
                f'<div style="margin-top:3px;color:#888;font-size:11px;">'
                f'<span style="color:#dc2626;">risk:</span> {_esc(r["llm_risks"])}'
                f'</div>'
            )
        thesis_block += "</div>"

    ai_score = r.get("llm_score")
    ai_cell  = f'<b style="color:#f97316;">{ai_score}</b>' if ai_score is not None else '<span style="color:#bbb;">—</span>'

    # Dim low-signal rows — those the AI flagged as "ignore".
    dim = action == "ignore"
    dim_style = "opacity:0.5;" if dim else ""

    action_cell = (
        f'<span style="background:{action_c}20;color:{action_c};'
        f'padding:2px 8px;border-radius:3px;font-size:10px;'
        f'font-family:monospace;text-transform:uppercase;letter-spacing:1px;">{_esc(action)}</span>'
        if action else '<span style="color:#bbb;">—</span>'
    )

    sentiment_badge = _render_sentiment(r)
    company_url     = _company_url(r)

    mc_s = _format_mc(r.get("market_cap"))
    mc_line = (
        f'<div style="font-family:monospace;color:#888;font-size:10px;margin-top:2px;">{mc_s}</div>'
        if mc_s else ""
    )
    mc_inline = (
        f'<span style="font-family:monospace;color:#888;font-size:11px;">{mc_s}</span>'
        if mc_s else ""
    )

    # ── desktop row (hidden on mobile) ──
    desktop = f"""
      <tr class="dt-row" style="border-bottom:1px solid #eee;{dim_style}">
        <td style="padding:10px 8px;font-family:monospace;color:#666;font-size:12px;white-space:nowrap;vertical-align:baseline;">{time_s}</td>
        <td style="padding:10px 8px;text-align:center;vertical-align:baseline;">{sentiment_badge}</td>
        <td style="padding:10px 8px;font-family:monospace;font-weight:700;color:#111;font-size:13px;white-space:nowrap;vertical-align:baseline;">
          <a href="{_esc(company_url)}" style="color:#111;text-decoration:none;">{_esc(r.get('ticker'))}</a>
          {mc_line}
        </td>
        <td style="padding:10px 8px;color:#444;font-size:12px;vertical-align:top;">
          <div style="font-weight:500;color:#222;">{_esc(r.get('company_name'))}</div>
          <a href="{_esc(r['url'])}" style="color:#1d4ed8;text-decoration:none;font-size:13px;">{_esc(r['headline'])}</a>
          {thesis_block}
        </td>
        <td style="padding:10px 8px;color:#666;font-size:11px;font-family:monospace;vertical-align:top;white-space:nowrap;">{_esc(category)}</td>
        <td style="padding:10px 8px;text-align:right;font-family:monospace;vertical-align:top;">{ai_cell}</td>
        <td style="padding:10px 8px;text-align:center;vertical-align:top;">{action_cell}</td>
      </tr>"""

    # ── mobile card (hidden on desktop) ──
    # Stacks vertically inside a single full-width <td>. Header strip carries
    # time + tier + ticker + AI score so the eye gets all the meta in one row.
    # NB: padding-right on each item (rather than flex `gap`) so spacing survives
    # in clients that ignore display:flex / gap (notably Outlook).
    mobile = f"""
      <tr class="mb-row" style="display:none;">
        <td style="padding:0;">
          <div style="border:1px solid #eee;border-radius:6px;margin-bottom:10px;background:#fff;overflow:hidden;{dim_style}">
            <div style="padding:8px 12px;background:#fafafa;border-bottom:1px solid #eee;display:flex;align-items:baseline;flex-wrap:wrap;">
              <span style="font-family:monospace;color:#666;font-size:12px;padding-right:10px;">{time_s}</span>
              <span style="display:inline-block;padding-right:10px;">{sentiment_badge}</span>
              <span style="font-family:monospace;font-weight:700;color:#111;font-size:13px;padding-right:10px;"><a href="{_esc(company_url)}" style="color:#111;text-decoration:none;">{_esc(r.get('ticker'))}</a></span>
              {f'<span style="font-family:monospace;color:#888;font-size:11px;padding-right:10px;">{mc_s}</span>' if mc_s else ""}
              <span style="margin-left:auto;font-family:monospace;font-size:13px;">{ai_cell}</span>
            </div>
            <div style="padding:10px 12px;">
              <div style="display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;margin-bottom:2px;">
                <span style="font-weight:500;color:#222;font-size:13px;padding-right:10px;">{_esc(r.get('company_name'))}</span>
                <span style="color:#f97316;font-size:11px;font-family:monospace;">{_esc(category)}</span>
              </div>
              <a href="{_esc(r['url'])}" style="color:#1d4ed8;text-decoration:none;font-size:14px;line-height:1.35;display:block;">{_esc(r['headline'])}</a>
              <div style="margin-top:6px;text-align:left;">
                {action_cell}
              </div>
              {thesis_block}
            </div>
          </div>
        </td>
      </tr>"""

    return desktop + mobile


def _render_section(bucket: str, rows: list[dict]) -> str:
    """Render one cap-bucket section: a heading bar followed by a table of rows
    (or a muted 'no items' note if the bucket is empty)."""
    meta = _CAP_META[bucket]
    color = meta["color"]

    # NB: margin-left on the children (rather than flex `gap`) keeps the
    # spacing intact in Outlook desktop, which ignores `display:flex`.
    heading = f"""
      <div style="margin:24px 0 8px 0;padding:8px 12px;background:{color}15;
                  border-left:4px solid {color};display:flex;align-items:baseline;
                  flex-wrap:wrap;">
        <span style="font-family:monospace;font-weight:700;color:{color};
                     font-size:13px;letter-spacing:2px;text-transform:uppercase;
                     padding-right:6px;">{meta['label']}</span>
        <span style="font-family:monospace;color:#888;font-size:11px;
                     margin-left:14px;">{meta['sub']}</span>
        <span style="margin-left:auto;font-family:monospace;color:#666;font-size:11px;
                     padding-left:14px;">{len(rows)} item{'s' if len(rows) != 1 else ''}</span>
      </div>"""

    if not rows:
        body = (
            '<div style="padding:16px 12px;text-align:center;color:#aaa;'
            'font-family:monospace;font-size:12px;font-style:italic;">no items</div>'
        )
    else:
        body = f"""
        <table class="digest-table" style="width:100%;border-collapse:collapse;background:#fff;">
          <thead class="dt-head">
            <tr style="background:#f5f5f5;border-bottom:2px solid #ddd;">
              <th style="padding:10px 8px;text-align:left;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Time</th>
              <th style="padding:10px 8px;text-align:center;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Signal</th>
              <th style="padding:10px 8px;text-align:left;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Ticker</th>
              <th style="padding:10px 8px;text-align:left;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Company / Headline</th>
              <th style="padding:10px 8px;text-align:left;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Category</th>
              <th style="padding:10px 8px;text-align:right;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">AI</th>
              <th style="padding:10px 8px;text-align:center;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Action</th>
            </tr>
          </thead>
          <tbody>
            {''.join(_render_row(r) for r in rows)}
          </tbody>
        </table>"""

    return heading + body


def _render_html(rows: list[dict], total_all: int = 0, sub_footer_html: str = "") -> str:
    now_uk = datetime.now(_UK_TZ)
    date_s = now_uk.strftime("%A %d %B %Y")

    if not rows:
        body = (
            '<div style="padding:40px 20px;text-align:center;color:#666;'
            'font-family:monospace;font-size:14px;">No significant items today.</div>'
        )
    else:
        buckets: dict[str, list[dict]] = {b: [] for b in _CAP_BUCKETS}
        for r in rows:
            buckets[_cap_bucket(r)].append(r)
        body = "".join(_render_section(b, buckets[b]) for b in _CAP_BUCKETS)

    n_pos = sum(1 for r in rows if _sentiment(r) == "positive")
    n_neg = sum(1 for r in rows if _sentiment(r) == "negative")
    n_neu = sum(1 for r in rows if _sentiment(r) == "neutral")
    n_ranked = sum(1 for r in rows if r.get("llm_score") is not None)

    # NB: <style> in <head> + media queries are supported by every major
    # mobile mail client (Apple Mail, Gmail iOS/Android, Outlook iOS/Android,
    # Spark, etc). Outlook desktop on Windows uses Word's renderer and ignores
    # them — which is fine, it gets the desktop layout regardless.
    return f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  /* Default = desktop layout */
  .mb-row {{ display: none !important; }}
  .dt-row {{ display: table-row !important; }}
  .dt-head {{ display: table-header-group !important; }}

  @media only screen and (max-width: 600px) {{
    .digest-wrap   {{ padding: 12px !important; }}
    .digest-table  {{ display: block !important; }}
    .digest-table tbody {{ display: block !important; }}
    .dt-head       {{ display: none !important; }}
    .dt-row        {{ display: none !important; }}
    .mb-row        {{ display: block !important; }}
    .mb-row > td   {{ display: block !important; width: 100% !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
  <div class="digest-wrap" style="max-width:920px;margin:0 auto;padding:24px;">
    <div style="border-bottom:2px solid #f97316;padding-bottom:12px;margin-bottom:16px;">
      <h1 style="margin:0;font-size:18px;font-family:monospace;color:#f97316;letter-spacing:2px;text-transform:uppercase;">Alpha Move AI · RNS Morning Digest</h1>
      <div style="margin-top:4px;color:#666;font-size:12px;">{date_s} · last 24h · {len(rows)} items · <span style="color:#10b981;">&#9650; {n_pos}</span> · <span style="color:#ef4444;">&#9660; {n_neg}</span> · <span style="color:#60a5fa;">&mdash; {n_neu}</span> · AI-ranked: <b>{n_ranked}/{total_all}</b></div>
    </div>
    {body}
    <div style="margin-top:24px;text-align:center;">
      <a href="{_KOFI_URL}" style="display:inline-block;background:#f97316;color:#ffffff;text-decoration:none;font-family:monospace;font-size:13px;font-weight:700;letter-spacing:1px;padding:11px 24px;border-radius:4px;">&hearts; Support Alpha Move AI</a>
      <div style="margin-top:8px;color:#999;font-size:11px;font-family:monospace;">Free, no ads &mdash; kept running by readers like you.</div>
    </div>
    <div style="margin-top:20px;padding-top:12px;border-top:1px solid #eee;color:#999;font-size:11px;font-family:monospace;text-align:center;">
      Generated by Alpha Move AI · {now_uk.strftime('%Y-%m-%d %H:%M %Z')}
    </div>
    {sub_footer_html}
  </div>
</body></html>"""


# ── Resend ────────────────────────────────────────────────────────────────────

def _send_via_resend(
    subject: str,
    html_body: str,
    to_addr: str,
    from_addr: str,
    api_key: str,
    extra_headers: dict | None = None,
) -> dict:
    body: dict = {
        "from":    from_addr,
        "to":      [to_addr],
        "subject": subject,
        "html":    html_body,
    }
    if extra_headers:
        # Resend's /emails endpoint accepts a top-level `headers` object
        # of custom RFC 5322 headers (List-Unsubscribe, etc).
        body["headers"] = extra_headers

    payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            # Resend is fronted by Cloudflare; the default urllib UA
            # ("Python-urllib/3.x") trips bot protection (CF error 1010).
            "User-Agent":    "FINScope-RNS-Digest/1.0",
            "Accept":        "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend HTTP {e.code}: {body}") from e


# ── Entry point ───────────────────────────────────────────────────────────────

def _sub_footer(unsub_url: str, manage_url: str) -> str:
    """Per-recipient footer with subscribe-management + unsubscribe links."""
    return (
        '<div style="margin-top:8px;color:#999;font-size:11px;'
        'font-family:monospace;text-align:center;">'
        f'<a href="{html.escape(manage_url)}" style="color:#999;">Subscribe</a>'
        ' &middot; '
        f'<a href="{html.escape(unsub_url)}" style="color:#999;">Unsubscribe</a>'
        '</div>'
    )


# ── Send pacing ───────────────────────────────────────────────────────────────
#
# Mailbox providers throttle per (sending IP × recipient domain), and we send
# from Resend's *shared* SES pool. On 21 Jul 2026 all 54 recipients went out in
# a 21s burst and 6 of the 9 Microsoft addresses came back delivery_delayed
# (4xx soft-deferral) while all 45 non-Microsoft recipients delivered on time.
#
# Two mechanisms, in order of importance:
#   1. Interleaving — reorder so consecutive sends hit different providers.
#      Costs nothing and does most of the work: with 9 Microsoft in 54, it puts
#      ~5 other sends between each pair, which at ~0.4s per send is about as
#      wide as the gap below, so the sleep barely fires on today's list.
#   2. A minimum same-provider gap, as a floor for when interleaving can't help
#      (a list that is mostly one provider).
#
# The gap deliberately applies to Microsoft only. Pacing every provider sounds
# more principled but is unaffordable: 45 of the 54 recipients are Google, and
# holding them 2s apart would cost ~72s on its own — over the budget below, and
# spent on a provider that delivered 45/45 on the day Microsoft deferred 6 of 9.
# Outlook.com being the aggressive one is a standing industry fact, not a
# one-off. Add providers here if the /status deferral panel starts implicating
# them; that panel and this set both key off email_events.provider_of.
_PACED_PROVIDERS   = {"microsoft"}
_SEND_GAP_S        = float(os.environ.get("DIGEST_SEND_GAP_SECONDS", "2"))
# The budget exists because the digest is driven by an HTTP request from
# cron-job.org, which times out well under two minutes. Blowing that wouldn't
# lose the send (the handler runs to completion after the client disconnects)
# but it would lose the stored-response audit trail that made the 2026-06/07
# silent-fallback bug findable — see the segment-mode notes above.
_SEND_GAP_BUDGET_S = float(os.environ.get("DIGEST_SEND_GAP_BUDGET_SECONDS", "45"))


def _interleave_by_provider(emails: list[str]) -> list[str]:
    """Reorder so same-provider recipients are spread across the whole run.

    Each address is placed at its fractional position within its own provider
    group, then all groups are merged by that fraction — so a group of 9 lands
    every ~1/9th of the way through regardless of how big the other groups are.
    (Naive round-robin would instead cluster the small group at the front.)

    Order within a provider is preserved, and the result is a permutation of the
    input: no address is dropped or duplicated.
    """
    buckets: dict[str, list[str]] = {}
    for email in emails:
        domain = email.rsplit("@", 1)[-1] if "@" in email else None
        buckets.setdefault(provider_of(domain), []).append(email)

    ranked: list[tuple[float, str, str]] = []
    for provider, bucket in buckets.items():
        n = len(bucket)
        for i, email in enumerate(bucket):
            # +0.5 centres each slot in its share of the run, so two groups of
            # equal size interleave instead of colliding on identical keys.
            ranked.append(((i + 0.5) / n, provider, email))
    # Provider name is a tiebreak purely so the order is deterministic in tests.
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [email for _, _, email in ranked]


def _pace(provider: str, last_send_at: dict[str, float], slept: float) -> float:
    """Sleep just long enough to keep `provider` sends _SEND_GAP_S apart.

    Only throttling providers (_PACED_PROVIDERS) are paced; everyone else
    returns immediately. Returns the new cumulative sleep total, and no-ops once
    the budget is spent, so a pathological list degrades to "send fast" rather
    than "miss the cron timeout" — deliverability is best-effort, the send
    itself is not.
    """
    if provider not in _PACED_PROVIDERS or _SEND_GAP_S <= 0 or slept >= _SEND_GAP_BUDGET_S:
        return slept
    previous = last_send_at.get(provider)
    if previous is None:
        return slept
    wait = _SEND_GAP_S - (time.monotonic() - previous)
    if wait <= 0:
        return slept
    wait = min(wait, _SEND_GAP_BUDGET_S - slept)
    time.sleep(wait)
    return slept + wait


def _send_one(api_key: str, from_addr: str, subject: str, rows: list[dict],
              to_email: str, base_url: str, total_all: int = 0) -> bool:
    """Render + send one digest email with per-recipient unsub plumbing.
    Returns True on success, False on failure (errors logged, not raised)."""
    try:
        from subscribers import build_unsubscribe_url  # local import to avoid cycles
        unsub_url  = build_unsubscribe_url(to_email)
        manage_url = f"{base_url.rstrip('/')}/subscribe" if base_url else "/subscribe"
        footer = _sub_footer(unsub_url, manage_url)
        headers = {
            "List-Unsubscribe":      f"<{unsub_url}>, <mailto:unsubscribe@alphamoveai.co.uk>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
        html_body = _render_html(rows, total_all, sub_footer_html=footer)
        result = _send_via_resend(subject, html_body, to_email, from_addr, api_key, extra_headers=headers)
        print(f"[digest] sent to {to_email} — id={result.get('id')}")
        return True
    except Exception as e:
        print(f"[digest] FAILED for {to_email}: {e}")
        return False


def _dry_run_report(rows: list[dict], total_all: int, subject: str,
                    segment_id: str | None, api_key: str | None) -> dict:
    """Render the digest and report what a real send *would* do, without ever
    calling Resend. Backs `--dry-run` and /api/digest?dry_run=true so the full
    fetch → render path can be exercised as a smoke check without emailing
    anyone. Returns a stats dict (see main()); exit_code 0 on a valid render,
    1 if the render or validation fails."""
    try:
        html_body = _render_html(rows, total_all)
    except Exception as e:
        print(f"[digest] DRY RUN: render FAILED: {e}")
        return {"exit_code": 1, "mode": "dry_run", "recipients": 0}
    if not subject or len(html_body) < 200:
        print(f"[digest] DRY RUN: validation FAILED "
              f"(subject={subject!r}, html_len={len(html_body)})")
        return {"exit_code": 1, "mode": "dry_run", "recipients": 0}

    # How many recipients a real send would hit right now.
    recipients = 0
    if segment_id and api_key:
        try:
            from subscribers import list_active_contacts
            recipients = sum(
                1 for c in list_active_contacts() if (c.get("email") or "").strip()
            )
        except Exception as e:
            print(f"[digest] DRY RUN: could not count segment contacts: {e}")
    elif (os.environ.get("DIGEST_TO") or "").strip():
        recipients = 1

    print(f'[digest] DRY RUN: would send "{subject}" '
          f'({len(rows)} rows, {len(html_body)} bytes) to '
          f'{recipients} recipient(s) — no email sent')
    return {"exit_code": 0, "mode": "dry_run", "recipients": recipients}


def _send_digest(dry_run: bool = False) -> dict:
    """Fetch, render and send (or dry-run) the digest.

    Returns a stats dict surfaced by /api/digest so cron-job.org's execution
    history records which path ran and to how many recipients:
      exit_code   — 0 ok, 1 config/render failure, 2 partial segment send
      mode        — "segment" | "fallback" | "none" | "dry_run"
      recipients  — addresses a send targeted (or would target, for dry_run)
      sent/failed — per-recipient outcomes (segment mode only)
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key and not dry_run:
        print("[digest] RESEND_API_KEY missing — aborting")
        return {"exit_code": 1, "mode": "none", "recipients": 0}

    from_addr = os.environ.get("DIGEST_FROM", _DEFAULT_FROM)
    segment_id = os.environ.get("RESEND_SEGMENT_ID")
    base_url   = os.environ.get("PUBLIC_BASE_URL", "")

    rows = _fetch_rows(_WINDOW_H)
    total_all = _count_all_rns(_WINDOW_H)
    print(f"[digest] {len(rows)} rows in last {_WINDOW_H}h (Tier A+B, cap ≥ £{_MIN_MARKET_CAP // 1_000_000}m) of {total_all} total")

    now_uk = datetime.now(_UK_TZ)
    if rows:
        subject = f"RNS Digest {now_uk.strftime('%a %d %b')} — {len(rows)} items"
    else:
        subject = f"RNS Digest {now_uk.strftime('%a %d %b')} — no significant items"

    # ── Dry run: render + validate, never send ────────────────────────────────
    if dry_run:
        return _dry_run_report(rows, total_all, subject, segment_id, api_key)

    # ── Segment mode ──────────────────────────────────────────────────────────
    if segment_id:
        try:
            from subscribers import list_active_contacts
            contacts = list_active_contacts()
        except Exception as e:
            print(f"[digest] FAILED to list contacts: {e} — falling back to DIGEST_TO")
            contacts = []

        if contacts:
            sent = failed = 0
            emails = [e for c in contacts if (e := (c.get("email") or "").strip())]
            # Spread same-provider recipients across the run, then hold a floor
            # between them — see the pacing notes above _send_one.
            ordered = _interleave_by_provider(emails)
            last_send_at: dict[str, float] = {}
            slept = 0.0
            for email in ordered:
                provider = provider_of(email.rsplit("@", 1)[-1] if "@" in email else None)
                slept = _pace(provider, last_send_at, slept)
                last_send_at[provider] = time.monotonic()
                if _send_one(api_key, from_addr, subject, rows, email, base_url, total_all):
                    sent += 1
                else:
                    failed += 1
            if slept:
                print(f"[digest] paced sends: slept {slept:.1f}s total "
                      f"(gap {_SEND_GAP_S}s, budget {_SEND_GAP_BUDGET_S}s)")
            print(f"[digest] segment send complete: {sent} sent, {failed} failed (of {len(contacts)})")
            return {"exit_code": 0 if failed == 0 else 2, "mode": "segment",
                    "recipients": len(contacts), "sent": sent, "failed": failed}

        print("[digest] segment configured but empty — falling back to DIGEST_TO")

    # ── Single-recipient fallback (original behaviour) ────────────────────────
    to_addr = (os.environ.get("DIGEST_TO") or "").strip()
    if not to_addr:
        print("[digest] no DIGEST_TO configured and no segment recipients — nothing to send")
        return {"exit_code": 0, "mode": "none", "recipients": 0}
    # Best-effort unsub footer for the fallback recipient (only if base + secret set).
    footer = ""
    headers: dict | None = None
    try:
        if base_url and os.environ.get("UNSUBSCRIBE_SECRET"):
            from subscribers import build_unsubscribe_url
            unsub_url  = build_unsubscribe_url(to_addr)
            manage_url = f"{base_url.rstrip('/')}/subscribe"
            footer = _sub_footer(unsub_url, manage_url)
            headers = {
                "List-Unsubscribe":      f"<{unsub_url}>, <mailto:unsubscribe@alphamoveai.co.uk>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
    except Exception as e:
        print(f"[digest] could not build unsub footer for fallback: {e}")

    html_body = _render_html(rows, total_all, sub_footer_html=footer)
    result = _send_via_resend(subject, html_body, to_addr, from_addr, api_key, extra_headers=headers)
    print(f"[digest] sent to {to_addr} — id={result.get('id')}")
    return {"exit_code": 0, "mode": "fallback", "recipients": 1, "sent": 1, "failed": 0}


def _send_status(stats: dict) -> str:
    """Map a send stats dict to a pipeline_runs status. Pure (no I/O) so the
    ok/degraded/failed decision can be unit-tested.

      'ok'       — clean segment send to every recipient
      'degraded' — fallback mode, partial segment send, or nothing sent (the
                   silent-fallback failure mode; healthcheck forces FAIL on it)
      'failed'   — config/render failure, no mail went out
    """
    if stats.get("exit_code", 1) == 1:
        return "failed"
    if stats.get("mode") == "segment" and stats.get("failed", 0) == 0:
        return "ok"
    return "degraded"  # partial send (exit 2), fallback mode, or nothing sent


def _record_send(stats: dict) -> None:
    """Stamp pipeline_runs('rns_digest') so the send leaves a DB trace that
    healthcheck.py's `digest.sent` check and the /status page can read — Resend
    was previously the only record, so a silent DIGEST_TO fallback (03 Jun–10
    Jul 2026) was indistinguishable from a healthy send. Migration-008
    convention; mirrors dividends.record_run(). Best-effort: a marker failure
    must never fail (or appear to fail) an otherwise-good send.
    """
    try:
        status = _send_status(stats)
        detail = {
            "mode": stats.get("mode"),
            "recipients": stats.get("recipients", 0),
            "sent": stats.get("sent"),
            "failed": stats.get("failed"),
        }
        import psycopg2.extras
        from db import connection
        with connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pipeline_runs (pipeline, last_run_at, status, detail)
                VALUES ('rns_digest', NOW(), %s, %s)
                ON CONFLICT (pipeline) DO UPDATE SET
                    last_run_at = EXCLUDED.last_run_at,
                    status      = EXCLUDED.status,
                    detail      = EXCLUDED.detail
                """,
                (status, psycopg2.extras.Json(detail)),
            )
            conn.commit()
    except Exception as e:
        print(f"[digest] WARNING: could not record pipeline_runs marker: {e}")


def main(dry_run: bool = False) -> dict:
    """Run the digest and, for real sends only, record a pipeline_runs marker.

    Thin wrapper over `_send_digest` so /api/digest and the CLI get the same
    stats dict as before while every non-dry-run send now leaves a DB trace.
    """
    stats = _send_digest(dry_run=dry_run)
    if not dry_run:
        _record_send(stats)
    return stats


if __name__ == "__main__":
    # `--dry-run` renders + validates the digest and prints what would be sent,
    # without contacting Resend. Everything else is a normal send.
    sys.exit(main(dry_run="--dry-run" in sys.argv)["exit_code"])
