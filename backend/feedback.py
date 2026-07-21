"""Website feedback endpoint.

A tiny contact form lives on the site (FeedbackTab). It POSTs here, and we
relay the message to the owner's inbox via emailer.send_email — sending FROM
the already verified digest sender and setting Reply-To to the visitor's
address (when given) so a reply goes straight back to them. This keeps the
owner's real inbox address off the public page; the form is the proxy.

No database, no contact list — fire-and-forget relay.

Endpoint:
  POST /api/feedback   — body {"message": "...", "email": "...", "company": ""}

Env:
  EMAIL_PROVIDER   — see emailer.py; decides which vendor carries this
  DIGEST_FROM      — verified sender (default: Alpha Move AI <digest@alphamoveai.co.uk>)
  FEEDBACK_TO      — where feedback lands (falls back to DIGEST_TO; one is required)
"""
import os
import re
import html

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from emailer import EmailSendError, send_email
from request_utils import client_ip, SlidingWindowLimiter


router = APIRouter()

# Same shape check subscribers.py uses — good enough; the provider rejects
# malformed addresses anyway.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

_DEFAULT_FROM = "Alpha Move AI <digest@alphamoveai.co.uk>"

_MAX_MESSAGE = 5000

# The honeypot only stops dumb bots; without a rate limit a script that leaves
# it blank can pump unlimited mail through our sending account into the owner's
# inbox. Nobody sends feedback five times in ten minutes legitimately.
_feedback_limiter = SlidingWindowLimiter(limit=5, window_seconds=600)


def _feedback_to() -> str:
    to = (os.environ.get("FEEDBACK_TO") or os.environ.get("DIGEST_TO") or "").strip()
    if not to:
        raise HTTPException(500, "FEEDBACK_TO / DIGEST_TO not configured")
    return to


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

    try:
        send_email(
            to=_feedback_to(),
            subject="Website feedback — Alpha Move AI",
            text=text,
            html=html_body,
            from_addr=from_addr,
            # Reply-To lets the owner answer the visitor directly from their inbox.
            reply_to=reply_to or None,
        )
    except EmailSendError as e:
        # Preserve the 502 the raw-urllib relay used to raise: the form shows a
        # "couldn't send" message on it, and a 500 would read as a bug in the
        # app rather than a provider problem.
        raise HTTPException(502, f"Could not send feedback: {e}") from e

    return {"ok": True}
