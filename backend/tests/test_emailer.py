"""emailer.send_email — provider dispatch and MIME assembly.

The MIME tests are the important half. SES sends raw bytes, so anything these
tests let through goes out on the wire exactly as written: a dropped
List-Unsubscribe header silently removes Gmail's one-click unsubscribe button,
which is an RFC 8058 compliance failure for a bulk sender and reads to a
mailbox provider as a reputation problem, not a bug.
"""
import email
import pytest

import emailer


HEADERS = {
    "List-Unsubscribe": "<https://app.alphamoveai.co.uk/api/unsubscribe?email=a%40b.com&t=abc>, "
                        "<mailto:unsubscribe@alphamoveai.co.uk>",
    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
}


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    """The SES client is memoised per process; drop it between tests so a stub
    from one test can't leak into another."""
    monkeypatch.setattr(emailer, "_ses_client", None)
    yield
    emailer._ses_client = None


# ── Dispatch ──────────────────────────────────────────────────────────────────

def test_defaults_to_resend(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    called = {}
    monkeypatch.setattr(emailer, "_send_resend", lambda **kw: called.update(kw) or "id_1")

    assert emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>") == "id_1"
    assert called["to"] == "a@b.com"


def test_ses_provider_routes_to_ses(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.setattr(emailer, "_send_ses", lambda **kw: "ses_id")
    monkeypatch.setattr(emailer, "_send_resend", lambda **kw: pytest.fail("used Resend"))

    assert emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>") == "ses_id"


def test_unknown_provider_raises(monkeypatch):
    """Fail loudly. A typo'd EMAIL_PROVIDER silently falling back to Resend is
    how you discover after cutover that nothing actually moved."""
    monkeypatch.setenv("EMAIL_PROVIDER", "sendgrid")
    with pytest.raises(emailer.EmailSendError, match="Unknown EMAIL_PROVIDER"):
        emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>")


def test_provider_name_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "  SES ")
    monkeypatch.setattr(emailer, "_send_ses", lambda **kw: "ses_id")
    assert emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>") == "ses_id"


def test_from_addr_defaults_to_digest_from(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("DIGEST_FROM", "Alpha <digest@alphamoveai.co.uk>")
    seen = {}
    monkeypatch.setattr(emailer, "_send_resend", lambda **kw: seen.update(kw) or "i")

    emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>")
    assert seen["from_addr"] == "Alpha <digest@alphamoveai.co.uk>"


# ── MIME assembly ─────────────────────────────────────────────────────────────

def _parsed(**overrides):
    kwargs = dict(to="a@b.com", subject="S", html="<p>hi</p>", text="hi",
                  from_addr="Alpha Move AI <digest@alphamoveai.co.uk>",
                  reply_to=None, headers=None)
    kwargs.update(overrides)
    return email.message_from_bytes(emailer.build_mime(**kwargs).as_bytes())


def _unfold(value: str | None) -> str | None:
    """Collapse RFC 5322 folding whitespace back into one logical line.

    List-Unsubscribe is long enough that EmailMessage folds it across lines.
    That is legal and every receiver unfolds before parsing, so the tests
    compare what a parser sees rather than the wire bytes.
    """
    if value is None:
        return None
    return " ".join(value.split())


def test_mime_preserves_unsubscribe_headers():
    msg = _parsed(headers=HEADERS)
    assert _unfold(msg["List-Unsubscribe"]) == _unfold(HEADERS["List-Unsubscribe"])
    assert _unfold(msg["List-Unsubscribe-Post"]) == "List-Unsubscribe=One-Click"


def test_unsubscribe_url_is_not_broken_by_folding():
    """Folding must land on the comma between the two URIs, never inside one —
    a line break mid-URL yields an unsubscribe link that 404s."""
    raw = emailer.build_mime(
        to="a@b.com", subject="S", html="<p>hi</p>", text="hi",
        from_addr="Alpha <digest@alphamoveai.co.uk>",
        reply_to=None, headers=HEADERS,
    ).as_bytes().decode()
    assert "https://app.alphamoveai.co.uk/api/unsubscribe?email=a%40b.com&t=abc" in raw


def test_mime_does_not_duplicate_headers():
    """EmailMessage APPENDS on assignment to an existing key. Two
    List-Unsubscribe headers is not a cosmetic problem — clients that see
    ambiguity drop the unsubscribe button entirely."""
    msg = _parsed(headers={**HEADERS, "To": "someone-else@example.com"})
    assert msg.get_all("To") == ["someone-else@example.com"]
    assert len(msg.get_all("List-Unsubscribe")) == 1


def test_mime_sets_reply_to():
    msg = _parsed(reply_to="visitor@example.com")
    assert msg["Reply-To"] == "visitor@example.com"


def test_mime_omits_reply_to_when_absent():
    assert _parsed()["Reply-To"] is None


def test_mime_keeps_display_name_from_line():
    msg = _parsed()
    assert msg["From"] == "Alpha Move AI <digest@alphamoveai.co.uk>"


def test_mime_encodes_non_ascii_subject():
    """£ and — appear in real digest subjects. The header must be RFC 2047
    encoded, and must decode back to the original."""
    subject = "RNS Digest — 12 items · £15m+"
    msg = _parsed(subject=subject)
    decoded = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
    assert decoded == subject


def test_mime_is_multipart_alternative_with_plain_first():
    """Order matters: mail clients render the LAST part they understand, so
    html must come second or everyone reads the plain-text fallback."""
    msg = _parsed()
    assert msg.get_content_type() == "multipart/alternative"
    subtypes = [p.get_content_subtype() for p in msg.get_payload()]
    assert subtypes == ["plain", "html"]


def test_mime_supplies_plain_fallback_when_caller_gives_none():
    """The digest passes html only. Sending html-only mail scores worse with
    spam filters, so a fallback is synthesised rather than omitted."""
    msg = _parsed(text=None)
    plain = msg.get_payload()[0].get_payload(decode=True).decode()
    assert plain.strip()


def test_mime_html_survives_intact():
    html = '<p>Sentiment: <span style="color:#0a0">positive</span> &amp; rising</p>'
    msg = _parsed(html=html)
    body = msg.get_payload()[1].get_payload(decode=True).decode()
    assert "positive" in body and "&amp; rising" in body


# ── SES call shape ────────────────────────────────────────────────────────────

class _StubSES:
    def __init__(self):
        self.kwargs = None

    def send_email(self, **kwargs):
        self.kwargs = kwargs
        return {"MessageId": "0100018f-ses"}


def test_ses_send_passes_raw_content_and_config_set(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.setenv("SES_CONFIGURATION_SET", "alphamove-digest")
    stub = _StubSES()
    monkeypatch.setattr(emailer, "_client", lambda: stub)

    msg_id = emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>",
                                from_addr="Alpha <digest@alphamoveai.co.uk>",
                                headers=HEADERS)

    assert msg_id == "0100018f-ses"
    assert stub.kwargs["ConfigurationSetName"] == "alphamove-digest"
    assert stub.kwargs["Destination"] == {"ToAddresses": ["a@b.com"]}
    # Raw, never Simple — Simple drops the unsubscribe headers.
    assert "Raw" in stub.kwargs["Content"]
    assert b"List-Unsubscribe-Post" in stub.kwargs["Content"]["Raw"]["Data"]


def test_ses_send_omits_config_set_when_unset(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.delenv("SES_CONFIGURATION_SET", raising=False)
    stub = _StubSES()
    monkeypatch.setattr(emailer, "_client", lambda: stub)

    emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>")
    assert "ConfigurationSetName" not in stub.kwargs


def test_ses_failure_becomes_email_send_error(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")

    class _Boom:
        def send_email(self, **kwargs):
            raise RuntimeError("AccessDenied")

    monkeypatch.setattr(emailer, "_client", lambda: _Boom())
    with pytest.raises(emailer.EmailSendError, match="AccessDenied"):
        emailer.send_email(to="a@b.com", subject="S", html="<p>h</p>")


# ── preflight ─────────────────────────────────────────────────────────────────

def test_preflight_flags_missing_resend_key(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert "RESEND_API_KEY" in emailer.preflight()


def test_preflight_flags_missing_aws_credentials(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    problem = emailer.preflight()
    assert "AWS_ACCESS_KEY_ID" in problem and "AWS_SECRET_ACCESS_KEY" in problem


def test_preflight_passes_when_configured(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA...")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    assert emailer.preflight() is None


def test_preflight_does_not_check_resend_key_under_ses(monkeypatch):
    """The whole point of the switch: after cutover there is no Resend key, and
    the digest must not abort looking for one."""
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA...")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    assert emailer.preflight() is None
