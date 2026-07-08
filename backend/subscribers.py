"""Email subscription endpoints — signup + unsubscribe.

Resend's Segments + workspace-scoped Contacts API is the source of truth
for the subscriber list (Audiences are deprecated). This module is a thin
proxy over those endpoints; we do not keep a parallel DB table.

Endpoints:
  POST /api/subscribers/signup          — body {"email": "..."}
  GET  /api/unsubscribe?email=&t=       — confirmation page + unsub
  POST /api/unsubscribe                 — RFC 8058 one-click unsub

Env:
  RESEND_API_KEY        — Resend API key (same one the digest uses)
  RESEND_SEGMENT_ID     — UUID of the segment in Resend dashboard
  UNSUBSCRIBE_SECRET    — random hex string for HMAC token signing
"""
import os
import re
import json
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import urllib.error

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


router = APIRouter()

# Simple email shape check — full RFC 5322 validation is not worth the
# email-validator dependency. Resend rejects malformed addresses anyway.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


# ── Resend HTTP (raw urllib — same pattern as email_rns_digest.py) ────────────

_RESEND_BASE = "https://api.resend.com"
_RESEND_UA   = "FINScope-Subscribers/1.0"


def _resend(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise HTTPException(500, "RESEND_API_KEY not configured")

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{_RESEND_BASE}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "User-Agent":    _RESEND_UA,
            "Accept":        "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


# ── Token signing ─────────────────────────────────────────────────────────────

def _unsubscribe_token(email: str) -> str:
    secret = os.environ.get("UNSUBSCRIBE_SECRET")
    if not secret:
        raise HTTPException(500, "UNSUBSCRIBE_SECRET not configured")
    mac = hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256)
    return mac.hexdigest()[:32]


def _verify_token(email: str, token: str) -> bool:
    try:
        expected = _unsubscribe_token(email)
    except HTTPException:
        return False
    return hmac.compare_digest(expected, token)


def _segment_id() -> str:
    sid = os.environ.get("RESEND_SEGMENT_ID")
    if not sid:
        raise HTTPException(500, "RESEND_SEGMENT_ID not configured")
    return sid


# Hard cap on the active subscriber list. Surfaced as a scarcity message on the
# signup forms; enforced here so the claim is real. Overridable via env without
# a code change (default 100).
def _max_subscribers() -> int:
    try:
        return int(os.environ.get("MAX_SUBSCRIBERS", "100"))
    except ValueError:
        return 100


# ── Signup ────────────────────────────────────────────────────────────────────

class SignupBody(BaseModel):
    email: str


@router.post("/api/subscribers/signup")
def signup(body: SignupBody):
    """Create a contact in the Resend segment, or re-activate if already
    present. Single opt-in — instantly subscribed."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")
    sid = _segment_id()

    # Capacity gate. An address that's already an active subscriber is
    # idempotent and never blocked; only a genuinely new (or returning,
    # previously-unsubscribed) address is rejected once the list is full.
    cap = _max_subscribers()
    try:
        active = list_active_contacts()
    except RuntimeError as e:
        raise HTTPException(502, f"Resend error: {e}")
    already_active = any((c.get("email") or "").lower() == email for c in active)
    if already_active:
        return {"ok": True, "status": "subscribed"}
    if len(active) >= cap:
        raise HTTPException(
            403,
            f"Sign-ups are full — all {cap} spots have been taken. "
            "Check back soon; we open more from time to time.",
        )

    # Contacts are workspace-scoped in the Segments model. We associate the
    # new contact with our segment via the `segments` array on create.
    # Resend expects each entry as an object {"id": "<uuid>"}, not a bare string.
    status, payload = _resend(
        "POST",
        "/contacts",
        {"email": email, "segments": [{"id": sid}], "unsubscribed": False},
    )
    if status in (200, 201):
        return {"ok": True, "status": "subscribed"}

    # Resend returns 409/422 if contact already exists — PATCH to re-activate.
    if status in (409, 422):
        upd_status, _ = _resend(
            "PATCH",
            f"/contacts/{urllib.parse.quote(email)}",
            {"unsubscribed": False, "segments": [{"id": sid}]},
        )
        if upd_status in (200, 201, 204):
            return {"ok": True, "status": "reactivated"}

    raise HTTPException(502, f"Resend error: {payload}")


# ── Live count (scarcity counter) ─────────────────────────────────────────────

# Counting active contacts hits Resend, so cache it in-process — every landing
# visitor reads this. Hosted on a long-lived process (Hetzner), so the module
# cache survives across requests; a short TTL keeps the number fresh enough.
_COUNT_TTL = 60.0
_count_cache: dict = {"ts": 0.0, "data": None}


# Scarcity-counter seeding. The *displayed* "taken" count is floored to this so
# the landing page shows visible traction while the real list is still small
# (default 22 → "78 of 100 free spots left"). This affects the DISPLAY ONLY —
# the real capacity gate in signup() counts genuine subscribers, so seeding can
# never block or double-count a real sign-up. Tunable via env with no redeploy:
# lower it any time to reset the number (e.g. back to 78) if it creeps too high.
def _count_floor() -> int:
    try:
        return max(0, int(os.environ.get("SUBSCRIBER_COUNT_FLOOR", "22")))
    except ValueError:
        return 22


@router.get("/api/subscribers/count")
def subscriber_count():
    """Public: active subscriber count + the cap, for the scarcity counter on
    the signup forms. Cached `_COUNT_TTL` seconds; serves stale on Resend error
    rather than failing the whole landing page."""
    now = time.time()
    cached = _count_cache["data"]
    if cached is not None and now - _count_cache["ts"] < _COUNT_TTL:
        return cached

    cap = _max_subscribers()
    try:
        active = list_active_contacts()
    except RuntimeError as e:
        if cached is not None:
            return cached
        raise HTTPException(502, f"Resend error: {e}")

    real = len(active)
    # Seed the displayed count with the floor for social proof, but never let
    # the floor alone show "full" — the form closes only when GENUINE
    # subscribers fill the list. While real < cap we always leave ≥1 spot
    # showing (ceiling cap-1), so seeding can't prematurely disable signups.
    count = max(real, _count_floor())
    if real < cap:
        count = min(count, cap - 1)
    data = {"count": count, "cap": cap, "remaining": max(0, cap - count)}
    _count_cache["ts"] = now
    _count_cache["data"] = data
    return data


# ── Unsubscribe ───────────────────────────────────────────────────────────────

_PAGE_OK = """<!doctype html><html><head><meta charset="utf-8">
<title>Unsubscribed · Alpha Move AI</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head><body style="margin:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
<div style="max-width:520px;margin:80px auto;padding:32px;background:#fff;border:1px solid #eee;border-radius:6px;text-align:center;">
  <h1 style="margin:0 0 12px;font-family:monospace;color:#f97316;letter-spacing:2px;font-size:16px;text-transform:uppercase;">Alpha Move AI</h1>
  <div style="height:2px;background:#f97316;width:60px;margin:0 auto 24px;"></div>
  <p style="color:#222;font-size:15px;line-height:1.5;">You've been unsubscribed.</p>
  <p style="color:#666;font-size:13px;line-height:1.5;">{email} will no longer receive the daily RNS digest.</p>
  <p style="margin-top:24px;color:#999;font-size:12px;">Changed your mind? <a href="/subscribe" style="color:#f97316;">Sign up again</a>.</p>
</div></body></html>"""

_PAGE_BAD = """<!doctype html><html><head><meta charset="utf-8">
<title>Invalid link · Alpha Move AI</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head><body style="margin:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
<div style="max-width:520px;margin:80px auto;padding:32px;background:#fff;border:1px solid #eee;border-radius:6px;text-align:center;">
  <h1 style="margin:0 0 12px;font-family:monospace;color:#f97316;letter-spacing:2px;font-size:16px;text-transform:uppercase;">Alpha Move AI</h1>
  <p style="color:#222;font-size:15px;line-height:1.5;">This unsubscribe link is invalid or expired.</p>
  <p style="margin-top:24px;color:#999;font-size:12px;"><a href="/subscribe" style="color:#f97316;">Manage subscription</a></p>
</div></body></html>"""


def _do_unsubscribe(email: str) -> None:
    status, payload = _resend(
        "PATCH",
        f"/contacts/{urllib.parse.quote(email)}",
        {"unsubscribed": True},
    )
    # 404 = contact never existed; treat as already-unsubscribed.
    if status not in (200, 201, 204, 404):
        raise HTTPException(502, f"Resend error: {payload}")


@router.get("/api/unsubscribe", response_class=HTMLResponse)
def unsubscribe_get(email: str = Query(...), t: str = Query(...)):
    email = email.lower()
    if not _verify_token(email, t):
        return HTMLResponse(_PAGE_BAD, status_code=400)
    _do_unsubscribe(email)
    return HTMLResponse(_PAGE_OK.format(email=email))


@router.post("/api/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_post(request: Request):
    """RFC 8058 one-click endpoint. Mail clients POST here with the
    email + token in either form-encoded body or query string."""
    email = request.query_params.get("email")
    token = request.query_params.get("t")

    if not (email and token):
        try:
            form = await request.form()
            email = email or form.get("email")
            token = token or form.get("t")
        except Exception:
            pass

    if not (email and token):
        return HTMLResponse(_PAGE_BAD, status_code=400)

    email = email.lower()
    if not _verify_token(email, token):
        return HTMLResponse(_PAGE_BAD, status_code=400)

    _do_unsubscribe(email)
    return HTMLResponse(_PAGE_OK.format(email=email))


class UnsubSelfBody(BaseModel):
    email: str


@router.post("/api/subscribers/unsubscribe-self")
def unsubscribe_self(body: UnsubSelfBody):
    """User-initiated unsubscribe from the website form. No HMAC token
    required (the user is already proving access to the email field) — we
    just verify the address shape and PATCH Resend."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")
    _do_unsubscribe(email)
    return {"ok": True, "status": "unsubscribed"}


# ── Helper exported for the digest sender ─────────────────────────────────────

def build_unsubscribe_url(email: str) -> str:
    """Return the public one-click unsubscribe URL for the given email.
    Used by email_rns_digest.py to insert into per-recipient List-Unsubscribe
    headers and HTML footers."""
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        # Fallback: relative URL works inside the app but not in emails.
        base = ""
    token = _unsubscribe_token(email)
    qs = urllib.parse.urlencode({"email": email.lower(), "t": token})
    return f"{base}/api/unsubscribe?{qs}"


def list_active_contacts() -> list[dict]:
    """Return all contacts in the segment that are NOT unsubscribed.
    Used by email_rns_digest.py to populate the recipient list.

    Paginates via Resend's cursor-based `after` param (max 100/page)."""
    sid = _segment_id()
    out: list[dict] = []
    after: str | None = None
    while True:
        path = f"/segments/{sid}/contacts?limit=100"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        status, payload = _resend("GET", path, None)
        if status != 200:
            raise RuntimeError(f"Resend list contacts failed: {status} {payload}")
        data = payload.get("data") or []
        out.extend(c for c in data if not c.get("unsubscribed"))
        if not payload.get("has_more") or not data:
            break
        after = data[-1].get("id")
        if not after:
            break
    return out
