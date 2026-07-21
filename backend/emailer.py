"""Outbound email — one send function, two providers behind an env switch.

Every outbound email in the app goes through `send_email`. Which vendor
actually carries it is decided by EMAIL_PROVIDER at call time:

    EMAIL_PROVIDER=resend   (default)  → Resend HTTP API
    EMAIL_PROVIDER=ses                 → Amazon SES (eu-west-2), boto3 SESv2

That switch is the whole point of this module. Cutover and rollback are a
Dokploy env change plus a redeploy, not a code deploy — which matters because
the failure mode being guarded against is "the new sender is quietly worse at
reaching Microsoft mailboxes", and that is only observable in production, hours
after the fact.

SES sends RAW MIME, not SESv2's Simple content. Simple silently drops custom
headers, and List-Unsubscribe / List-Unsubscribe-Post are what give Gmail and
Outlook their native one-click unsubscribe button. Losing them would break RFC
8058 compliance for a bulk sender — a deliverability problem that looks exactly
like a reputation problem, and takes weeks to diagnose as anything else.

Env:
  EMAIL_PROVIDER         — "resend" (default) | "ses"
  RESEND_API_KEY         — required when provider is resend
  AWS_REGION             — SES region (default eu-west-2 / London)
  AWS_ACCESS_KEY_ID      — the alphamove-ses IAM user
  AWS_SECRET_ACCESS_KEY
  SES_CONFIGURATION_SET  — required for delivery events to reach SNS→SQS
  DIGEST_FROM            — default sender, used when a caller passes none
"""
import json
import os
import urllib.error
import urllib.request
from email.message import EmailMessage


DEFAULT_FROM = "Alpha Move AI <digest@alphamoveai.co.uk>"


class EmailSendError(RuntimeError):
    """A send failed at the provider.

    Subclasses RuntimeError on purpose: the digest's per-recipient `except
    Exception` and research.py's blanket notification catch both already treat
    a failed send as non-fatal, and neither should have to learn a new type.
    The HTTP callers (feedback, unsubscribe-self) translate this into a 502.
    """


def _provider() -> str:
    return (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()


# ── Resend ────────────────────────────────────────────────────────────────────

def _send_resend(*, to: str, subject: str, html: str, text: str | None,
                 from_addr: str, reply_to: str | None,
                 headers: dict | None) -> str:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EmailSendError("RESEND_API_KEY not configured")

    body: dict = {"from": from_addr, "to": [to], "subject": subject, "html": html}
    if text:
        body["text"] = text
    if reply_to:
        body["reply_to"] = reply_to
    if headers:
        # Resend's /emails endpoint takes custom RFC 5322 headers as a
        # top-level object.
        body["headers"] = headers

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            # Resend is fronted by Cloudflare; the default urllib UA
            # ("Python-urllib/3.x") trips bot protection (CF error 1010).
            "User-Agent":    "FINScope-Mailer/1.0",
            "Accept":        "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise EmailSendError(f"Resend HTTP {e.code}: {raw}") from e
    except Exception as e:
        raise EmailSendError(f"Resend request failed: {type(e).__name__}: {e}") from e
    return str(payload.get("id") or "")


# ── Amazon SES ────────────────────────────────────────────────────────────────

_ses_client = None


def _client():
    """Lazily build one SESv2 client per process.

    Lazy rather than module-level so importing this module never requires boto3
    or AWS credentials — the Resend path, the test suite and every unrelated
    backend module import it freely while SES is still being rolled out.
    """
    global _ses_client
    if _ses_client is None:
        import boto3  # imported here, not at module scope — see above
        _ses_client = boto3.client(
            "sesv2",
            region_name=os.environ.get("AWS_REGION", "eu-west-2"),
        )
    return _ses_client


def build_mime(*, to: str, subject: str, html: str, text: str | None,
               from_addr: str, reply_to: str | None,
               headers: dict | None) -> EmailMessage:
    """Assemble the raw MIME message SES sends.

    Separate from _send_ses so the header handling can be unit-tested without
    boto3 or credentials — this is the part that silently breaks unsubscribe.

    EmailMessage handles RFC 2047 encoding of non-ASCII subjects and correct
    quoting of "Display Name <addr>" senders; hand-rolling either is a
    well-known way to produce mail that renders as mojibake in some clients.
    """
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    for key, value in (headers or {}).items():
        # del first: assigning an existing key APPENDS a duplicate header in
        # EmailMessage rather than replacing it, and two List-Unsubscribe
        # headers make the one-click button disappear entirely.
        del msg[key]
        msg[key] = value

    # A text/plain alternative is always set: html-only mail scores worse with
    # spam filters, and set_content-then-add_alternative is the only ordering
    # that yields a correct multipart/alternative (plain first, html second).
    msg.set_content(text or "This email requires an HTML-capable mail client.")
    msg.add_alternative(html, subtype="html")
    return msg


def _send_ses(*, to: str, subject: str, html: str, text: str | None,
              from_addr: str, reply_to: str | None,
              headers: dict | None) -> str:
    msg = build_mime(to=to, subject=subject, html=html, text=text,
                     from_addr=from_addr, reply_to=reply_to, headers=headers)

    kwargs: dict = {
        "FromEmailAddress": from_addr,
        "Destination": {"ToAddresses": [to]},
        "Content": {"Raw": {"Data": msg.as_bytes()}},
    }
    # Without the config set SES still sends, but emits no events — so the
    # delivery record silently stops existing. Since SES has no message log of
    # its own, that is the entire audit trail gone; warn loudly rather than
    # discover it a week later.
    config_set = os.environ.get("SES_CONFIGURATION_SET")
    if config_set:
        kwargs["ConfigurationSetName"] = config_set
    else:
        print("[emailer] WARNING: SES_CONFIGURATION_SET unset — "
              "this send will produce no delivery events")

    try:
        resp = _client().send_email(**kwargs)
    except Exception as e:
        raise EmailSendError(f"SES send failed: {type(e).__name__}: {e}") from e
    return str(resp.get("MessageId") or "")


# ── Public API ────────────────────────────────────────────────────────────────

def send_email(*, to: str, subject: str, html: str, text: str | None = None,
               from_addr: str | None = None, reply_to: str | None = None,
               headers: dict | None = None) -> str:
    """Send one email to one recipient. Returns the provider's message id.

    Single recipient by design: all four call sites send to exactly one address,
    and the digest needs a per-recipient unsubscribe link in the headers, which
    a multi-recipient send cannot express.

    Raises EmailSendError on any provider failure.
    """
    from_addr = from_addr or os.environ.get("DIGEST_FROM", DEFAULT_FROM)
    provider = _provider()

    if provider == "ses":
        send = _send_ses
    elif provider == "resend":
        send = _send_resend
    else:
        raise EmailSendError(
            f"Unknown EMAIL_PROVIDER {provider!r} (expected 'resend' or 'ses')"
        )

    return send(to=to, subject=subject, html=html, text=text,
                from_addr=from_addr, reply_to=reply_to, headers=headers)


def preflight() -> str | None:
    """Return a human-readable reason the configured provider cannot send, or
    None if it looks usable.

    Exists so the digest can abort cleanly on a missing credential instead of
    failing 54 times in a row — one per recipient — and reporting a partial
    send. Deliberately checks only for presence, not validity: proving a key
    works means sending an email.
    """
    provider = _provider()
    if provider == "resend":
        if not os.environ.get("RESEND_API_KEY"):
            return "RESEND_API_KEY missing"
        return None
    if provider == "ses":
        missing = [v for v in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
                   if not os.environ.get(v)]
        if missing:
            return f"{', '.join(missing)} missing"
        return None
    return f"unknown EMAIL_PROVIDER {provider!r}"
