"""Website feedback endpoint.

A tiny contact form lives on the site (FeedbackTab). It POSTs here, and we
relay the message to the owner's inbox via Resend — sending FROM the already
verified digest sender and setting Reply-To to the visitor's address (when
given) so a reply goes straight back to them. This keeps the owner's real
inbox address off the public page; the form is the proxy.

No database, no contact list — fire-and-forget relay, same raw-urllib Resend
pattern as email_rns_digest.py / subscribers.py.

Endpoint:
  POST /api/feedback   — body {"message": "...", "email": "...", "company": ""}

Env:
  RESEND_API_KEY   — required, same key the digest uses
  DIGEST_FROM      — verified sender (default: Alpha Move AI <digest@alphamoveai.co.uk>)
  FEEDBACK_TO      — where feedback lands (falls back to DIGEST_TO; one is required)
"""
import os
import re
import json
import html
import urllib.request
import urllib.error

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from request_utils import client_ip, SlidingWindowLimiter


router = APIRouter()

# Same shape check subscribers.py uses — good enough; Resend rejects malformed.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

_DEFAULT_FROM = "Alpha Move AI <digest@alphamoveai.co.uk>"

_MAX_MESSAGE = 5000

# The honeypot only stops dumb bots; without a rate limit a script that leaves
# it blank can pump unlimited mail through the Resend account into the owner's
# inbox. Nobody sends feedback five times in ten minutes legitimately.
_feedback_limiter = SlidingWindowLimiter(limit=5, window_seconds=600)


def _feedback_to() -> str:
    to = (os.environ.get("FEEDBACK_TO") or os.environ.get("DIGEST_TO") or "").strip()
    if not to:
        raise HTTPException(500, "FEEDBACK_TO / DIGEST_TO not configured")
    return to


def _send_via_resend(body: dict) -> dict:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise HTTPException(500, "RESEND_API_KEY not configured")

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            # Resend is fronted by Cloudflare; the default urllib UA trips bot
            # protection (CF 1010), so set an explicit one — as the digest does.
            "User-Agent":    "FINScope-Feedback/1.0",
            "Accept":        "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise HTTPException(502, f"Resend HTTP {e.code}: {raw}") from e


class FeedbackBody(BaseModel):
    message: str
    email: str | None = None
    # Honeypot: a hidden field real users never see. Bots fill every input, so
    # any non-empty value here is almost certainly spam — we accept-and-drop.
    company: str | None = None


@router.post("/api/feedback")
def submit_feedback(body: FeedbackBody, request: Request):
    # Honeypot tripped — pretend success so the bot doesn't retry/learn.
    if (body.company or "").strip():
        return {"ok": True}

    if not _feedback_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many messages — please wait a few minutes and try again")

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(400, "Message is required")
    if len(message) > _MAX_MESSAGE:
        raise HTTPException(400, f"Message too long (max {_MAX_MESSAGE} characters)")

    reply_to = (body.email or "").strip().lower()
    if reply_to and not _EMAIL_RE.match(reply_to):
        raise HTTPException(400, "Invalid email address")

    from_addr = os.environ.get("DIGEST_FROM", _DEFAULT_FROM)
    sender_line = reply_to or "(no email given)"

    text = f"From: {sender_line}\n\n{message}"
    html_body = (
        '<div style="font-family:monospace;font-size:14px;color:#111;">'
        f'<p style="color:#666;">From: {html.escape(sender_line)}</p>'
        f'<p style="white-space:pre-wrap;line-height:1.6;">{html.escape(message)}</p>'
        '</div>'
    )

    payload: dict = {
        "from":    from_addr,
        "to":      [_feedback_to()],
        "subject": "Website feedback — Alpha Move AI",
        "text":    text,
        "html":    html_body,
    }
    # Reply-To lets the owner answer the visitor directly from their inbox.
    if reply_to:
        payload["reply_to"] = reply_to

    _send_via_resend(payload)
    return {"ok": True}
