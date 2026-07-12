"""Exercise the email-digest path end-to-end without sending mail.

Closes the gap documented in backend/healthcheck.py: the digest was previously
unverifiable because hitting /api/digest would actually email subscribers. The
dry_run flag fetches + renders + validates and returns before any Resend call.

Needs DIGEST_CRON_TOKEN (same value as the backend's env var); skipped when
unset so a local `pytest smoke` run without the secret still passes.
"""
import os

import pytest


def test_digest_dry_run_renders(client):
    token = os.environ.get("DIGEST_CRON_TOKEN")
    if not token:
        pytest.skip("DIGEST_CRON_TOKEN not set")

    r = client.get("/api/digest", params={"dry_run": "true"},
                   headers={"X-Digest-Token": token})
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True, body
    assert body.get("dry_run") is True, body
