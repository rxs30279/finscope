"""Daily RNS digest email.

Reads the last 24h of Tier A + B announcements from the existing
rns_announcements table and emails an HTML digest via Resend. Strictly
read-only — does not trigger ingest, summary fetching, or DeepSeek ranking.
The pipeline that populates llm_* columns runs on its own GitHub Actions
schedule (refresh-rns.yml).

Environment:
  RESEND_API_KEY   — required, https://resend.com/api-keys
  DIGEST_TO        — recipient (default: richard_stephens@hotmail.co.uk)
  DIGEST_FROM      — sender   (default: digest@alphamoveai.co.uk)
  DB_*             — same vars as the rest of the backend
"""
import sys, os
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import json
import html
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from rns import _query


_UK_TZ      = ZoneInfo("Europe/London")
_WINDOW_H   = 24
_DEFAULT_TO = "richard_stephens@hotmail.co.uk"
_DEFAULT_FROM = "Alpha Move AI <digest@alphamoveai.co.uk>"


# ── Data ──────────────────────────────────────────────────────────────────────

def _fetch_rows(hours: int = _WINDOW_H) -> list[dict]:
    """Tier A + B in the last `hours`. AI-ranked rows first (by llm_score),
    then unranked by published_at desc. Mirrors the RnsTab default sort.

    Joins company_metadata for `ftse_index` (used to bucket rows into
    large/mid/small-cap sections) and ttm_financials for `market_cap`
    (shown inline next to the ticker)."""
    return _query("""
        SELECT r.id, r.published_at, r.ticker, r.symbol, r.company_name,
               r.headline, r.url, r.tier, r.category,
               r.score, r.llm_score, r.llm_thesis, r.llm_action, r.llm_risks,
               m.ftse_index, f.market_cap
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


# ── Market-cap bucketing ──────────────────────────────────────────────────────

# Three sections. Anything not explicitly Large or Mid (incl. FTSE SmallCap,
# AIM 100, AIM All-Share, unlisted, NULL) falls into Small.
_CAP_BUCKETS = ("large", "mid", "small")
_CAP_META = {
    "large": {"label": "Large Cap", "sub": "FTSE 100",       "color": "#f97316"},
    "mid":   {"label": "Mid Cap",   "sub": "FTSE 250",       "color": "#60a5fa"},
    "small": {"label": "Small Cap", "sub": "SmallCap / AIM / other", "color": "#6b7280"},
}


def _cap_bucket(row: dict) -> str:
    idx = row.get("ftse_index")
    if idx == "FTSE 100":
        return "large"
    if idx == "FTSE 250":
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

_TIER_COLOR  = {"A": "#f97316", "B": "#60a5fa"}
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
    tier_c   = _TIER_COLOR.get(r["tier"], "#888")
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

    action_cell = (
        f'<span style="background:{action_c}20;color:{action_c};'
        f'padding:2px 8px;border-radius:3px;font-size:10px;'
        f'font-family:monospace;text-transform:uppercase;letter-spacing:1px;">{_esc(action)}</span>'
        if action else '<span style="color:#bbb;">—</span>'
    )

    tier_pill = (
        f'<span style="background:{tier_c}20;color:{tier_c};padding:2px 6px;'
        f'border-radius:2px;font-family:monospace;font-size:10px;font-weight:700;">{r["tier"]}</span>'
    )

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
      <tr class="dt-row" style="border-bottom:1px solid #eee;">
        <td style="padding:10px 8px;font-family:monospace;color:#666;font-size:12px;white-space:nowrap;vertical-align:top;">{time_s}</td>
        <td style="padding:10px 8px;vertical-align:top;">{tier_pill}</td>
        <td style="padding:10px 8px;font-family:monospace;font-weight:700;color:#111;font-size:13px;white-space:nowrap;vertical-align:top;">
          {_esc(r.get('ticker'))}
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
    mobile = f"""
      <tr class="mb-row" style="display:none;">
        <td style="padding:0;">
          <div style="border:1px solid #eee;border-radius:6px;margin-bottom:10px;background:#fff;overflow:hidden;">
            <div style="padding:8px 12px;background:#fafafa;border-bottom:1px solid #eee;display:flex;align-items:center;flex-wrap:wrap;gap:8px;">
              <span style="font-family:monospace;color:#666;font-size:12px;">{time_s}</span>
              {tier_pill}
              <span style="font-family:monospace;font-weight:700;color:#111;font-size:13px;">{_esc(r.get('ticker'))}</span>
              {mc_inline}
              <span style="margin-left:auto;font-family:monospace;font-size:13px;">{ai_cell}</span>
            </div>
            <div style="padding:10px 12px;">
              <div style="font-weight:500;color:#222;font-size:13px;margin-bottom:2px;">{_esc(r.get('company_name'))}</div>
              <a href="{_esc(r['url'])}" style="color:#1d4ed8;text-decoration:none;font-size:14px;line-height:1.35;display:block;">{_esc(r['headline'])}</a>
              {thesis_block}
              <div style="margin-top:8px;display:flex;align-items:center;justify-content:space-between;gap:8px;">
                <span style="color:#666;font-size:11px;font-family:monospace;">{_esc(category)}</span>
                {action_cell}
              </div>
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

    heading = f"""
      <div style="margin:24px 0 8px 0;padding:8px 12px;background:{color}15;
                  border-left:4px solid {color};display:flex;align-items:baseline;
                  flex-wrap:wrap;gap:10px;">
        <span style="font-family:monospace;font-weight:700;color:{color};
                     font-size:13px;letter-spacing:2px;text-transform:uppercase;">{meta['label']}</span>
        <span style="font-family:monospace;color:#888;font-size:11px;">{meta['sub']}</span>
        <span style="margin-left:auto;font-family:monospace;color:#666;font-size:11px;">{len(rows)} item{'s' if len(rows) != 1 else ''}</span>
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
              <th style="padding:10px 8px;text-align:left;font-family:monospace;font-size:10px;color:#555;letter-spacing:1px;text-transform:uppercase;">Tier</th>
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


def _render_html(rows: list[dict], window_h: int) -> str:
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

    n_a = sum(1 for r in rows if r["tier"] == "A")
    n_b = sum(1 for r in rows if r["tier"] == "B")
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
      <div style="margin-top:4px;color:#666;font-size:12px;">{date_s} · last {window_h}h · Tier A: <b>{n_a}</b> · Tier B: <b>{n_b}</b> · AI-ranked: <b>{n_ranked}</b></div>
    </div>
    {body}
    <div style="margin-top:20px;padding-top:12px;border-top:1px solid #eee;color:#999;font-size:11px;font-family:monospace;text-align:center;">
      Generated by Alpha Move AI · {now_uk.strftime('%Y-%m-%d %H:%M %Z')}
    </div>
  </div>
</body></html>"""


# ── Resend ────────────────────────────────────────────────────────────────────

def _send_via_resend(subject: str, html_body: str, to_addr: str, from_addr: str, api_key: str) -> dict:
    payload = json.dumps({
        "from":    from_addr,
        "to":      [to_addr],
        "subject": subject,
        "html":    html_body,
    }).encode("utf-8")

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

def main() -> int:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("[digest] RESEND_API_KEY missing — aborting")
        return 1

    to_addr   = os.environ.get("DIGEST_TO",   _DEFAULT_TO)
    from_addr = os.environ.get("DIGEST_FROM", _DEFAULT_FROM)

    rows = _fetch_rows(_WINDOW_H)
    print(f"[digest] {len(rows)} rows in last {_WINDOW_H}h (Tier A+B)")

    now_uk = datetime.now(_UK_TZ)
    if rows:
        subject = f"RNS Digest {now_uk.strftime('%a %d %b')} — {len(rows)} items"
    else:
        subject = f"RNS Digest {now_uk.strftime('%a %d %b')} — no significant items"

    html_body = _render_html(rows, _WINDOW_H)

    result = _send_via_resend(subject, html_body, to_addr, from_addr, api_key)
    print(f"[digest] sent to {to_addr} — id={result.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
