"""Daily RNS digest email.

Reads the last 24h of Tier A + B announcements from the existing
rns_announcements table and emails an HTML digest via Resend. Strictly
read-only — does not trigger ingest, summary fetching, or DeepSeek ranking.
The pipeline that populates llm_* columns runs on its own GitHub Actions
schedule (refresh-rns.yml).

Environment:
  RESEND_API_KEY   — required, https://resend.com/api-keys
  DIGEST_TO        — recipient (default: richard_stephens@hotmail.co.uk)
  DIGEST_FROM      — sender   (default: onboarding@resend.dev — Resend's
                     shared test sender; replace once a domain is verified)
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
# Resend's shared test sender — works without domain verification.
# Replace once the user verifies their own domain on resend.com/domains.
_DEFAULT_FROM = "Alpha Move AI <onboarding@resend.dev>"


# ── Data ──────────────────────────────────────────────────────────────────────

def _fetch_rows(hours: int = _WINDOW_H) -> list[dict]:
    """Tier A + B in the last `hours`. AI-ranked rows first (by llm_score),
    then unranked by published_at desc. Mirrors the RnsTab default sort."""
    return _query("""
        SELECT id, published_at, ticker, symbol, company_name,
               headline, url, tier, category,
               score, llm_score, llm_thesis, llm_action, llm_risks
          FROM rns_announcements
         WHERE tier IN ('A', 'B')
           AND published_at >= NOW() - (%s || ' hours')::interval
         ORDER BY (llm_score IS NULL),    -- ranked first
                  llm_score   DESC NULLS LAST,
                  published_at DESC
         LIMIT 200
    """, (str(hours),))


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
    tier_c   = _TIER_COLOR.get(r["tier"], "#888")
    action   = r.get("llm_action") or ""
    action_c = _ACTION_COLOR.get(action, "#888")
    category = _CATEGORY_LABELS.get(r.get("category"), r.get("category") or "—")

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

    return f"""
      <tr style="border-bottom:1px solid #eee;">
        <td style="padding:10px 8px;font-family:monospace;color:#666;font-size:12px;white-space:nowrap;vertical-align:top;">{_fmt_uk_time(r['published_at'])}</td>
        <td style="padding:10px 8px;vertical-align:top;">
          <span style="background:{tier_c}20;color:{tier_c};padding:2px 6px;border-radius:2px;font-family:monospace;font-size:10px;font-weight:700;">{r['tier']}</span>
        </td>
        <td style="padding:10px 8px;font-family:monospace;font-weight:700;color:#111;font-size:13px;white-space:nowrap;vertical-align:top;">{_esc(r.get('ticker'))}</td>
        <td style="padding:10px 8px;color:#444;font-size:12px;vertical-align:top;">
          <div style="font-weight:500;color:#222;">{_esc(r.get('company_name'))}</div>
          <a href="{_esc(r['url'])}" style="color:#1d4ed8;text-decoration:none;font-size:13px;">{_esc(r['headline'])}</a>
          {thesis_block}
        </td>
        <td style="padding:10px 8px;color:#666;font-size:11px;font-family:monospace;vertical-align:top;white-space:nowrap;">{_esc(category)}</td>
        <td style="padding:10px 8px;text-align:right;font-family:monospace;vertical-align:top;">{ai_cell}</td>
        <td style="padding:10px 8px;text-align:center;vertical-align:top;">{action_cell}</td>
      </tr>"""


def _render_html(rows: list[dict], window_h: int) -> str:
    now_uk = datetime.now(_UK_TZ)
    date_s = now_uk.strftime("%A %d %B %Y")

    if not rows:
        body = (
            '<div style="padding:40px 20px;text-align:center;color:#666;'
            'font-family:monospace;font-size:14px;">No significant items today.</div>'
        )
    else:
        body = f"""
        <table style="width:100%;border-collapse:collapse;background:#fff;">
          <thead>
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

    n_a = sum(1 for r in rows if r["tier"] == "A")
    n_b = sum(1 for r in rows if r["tier"] == "B")
    n_ranked = sum(1 for r in rows if r.get("llm_score") is not None)

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
  <div style="max-width:920px;margin:0 auto;padding:24px;">
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
