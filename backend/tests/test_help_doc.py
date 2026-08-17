"""/api/help-doc — the stored user manual.

The document is ~1.8 MB of BYTEA, which psycopg2 reads back hex-encoded, so a
fetch costs ~3.6 MB off the database. The endpoint sets max-age=0,
must-revalidate, meaning browsers send a conditional request on *every* view, so
a 304 that still selected the bytes paid full price to send nothing. These tests
pin the split: metadata query always, blob query only when a body goes out.
"""
import sys, os
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UPDATED_AT = datetime(2026, 7, 30, 17, 52, 10, 258441, tzinfo=timezone.utc)
ETAG = f'"user-manual-{int(UPDATED_AT.timestamp())}"'

_META = {
    "filename": "Alpha_Move_AI_User_Manual.pdf",
    "content_type": "application/pdf",
    "updated_at": UPDATED_AT,
}
_BODY = b"%PDF-1.7 pretend this is 1.8 MB"


def _meta_select(call):
    """True if the SQL in this recorded call() is the cheap metadata query."""
    return "data" not in call.args[0]


def test_help_doc_200_sends_body_and_validators(client):
    with patch("main.query", side_effect=[[_META], [{"data": _BODY}]]) as q:
        r = client.get("/api/help-doc")

    assert r.status_code == 200
    assert r.content == _BODY
    assert r.headers["ETag"] == ETAG
    assert r.headers["Cache-Control"] == "public, max-age=0, must-revalidate"
    assert r.headers["Content-Type"].startswith("application/pdf")
    assert "inline" in r.headers["Content-Disposition"]
    # Two queries: metadata, then the blob.
    assert q.call_count == 2
    assert _meta_select(q.call_args_list[0])
    assert not _meta_select(q.call_args_list[1])


def test_help_doc_304_never_selects_the_blob(client):
    """The whole point of the fix: a matching ETag must cost one cheap query."""
    with patch("main.query", side_effect=[[_META]]) as q:
        r = client.get("/api/help-doc", headers={"If-None-Match": ETAG})

    assert r.status_code == 304
    assert not r.content
    assert r.headers["ETag"] == ETAG
    # One query, and it must be the one that does NOT mention data.
    assert q.call_count == 1
    assert _meta_select(q.call_args_list[0])


def test_help_doc_stale_etag_still_sends_the_body(client):
    with patch("main.query", side_effect=[[_META], [{"data": _BODY}]]) as q:
        r = client.get("/api/help-doc", headers={"If-None-Match": '"user-manual-1"'})

    assert r.status_code == 200
    assert r.content == _BODY
    assert q.call_count == 2


def test_help_doc_404_before_touching_the_blob(client):
    with patch("main.query", side_effect=[[]]) as q:
        r = client.get("/api/help-doc?slug=nope")

    assert r.status_code == 404
    assert q.call_count == 1


def test_help_doc_404_when_deleted_between_the_two_queries(client):
    """Metadata found, blob gone — must 404 rather than serve an empty body."""
    with patch("main.query", side_effect=[[_META], []]) as q:
        r = client.get("/api/help-doc")

    assert r.status_code == 404
    assert q.call_count == 2


def test_help_doc_non_pdf_downloads_as_attachment(client):
    meta = {**_META, "content_type": "text/csv", "filename": "export.csv"}
    with patch("main.query", side_effect=[[meta], [{"data": b"a,b\n1,2\n"}]]):
        r = client.get("/api/help-doc?slug=export")

    assert r.status_code == 200
    assert "attachment" in r.headers["Content-Disposition"]


def test_help_doc_accepts_memoryview_from_psycopg2(client):
    """psycopg2 hands BYTEA back as a memoryview, not bytes."""
    with patch("main.query", side_effect=[[_META], [{"data": memoryview(_BODY)}]]):
        r = client.get("/api/help-doc")

    assert r.status_code == 200
    assert r.content == _BODY
