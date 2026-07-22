"""Subscriber list against Postgres (subscribers.py, migration 019).

Covers the behaviour that used to be Resend's problem and is now ours: the
capacity gate, idempotent re-signup, the unsubscribe flag, and the display-only
scarcity counter. The counter maths is included because it is the one piece
where "the number shown" and "the number enforced" deliberately differ, and
conflating them would either block real sign-ups or advertise spots that
don't exist.
"""
import pytest
from fastapi.testclient import TestClient

import subscribers
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_count_cache():
    """The scarcity counter is memoised for 60s in a module-level dict; without
    clearing it one test serves another's number."""
    subscribers._count_cache["ts"] = 0.0
    subscribers._count_cache["data"] = None
    yield
    subscribers._count_cache["ts"] = 0.0
    subscribers._count_cache["data"] = None


class _FakeCursor:
    """Just enough cursor to run the two statements subscribers.py issues.

    Dispatches on the SQL rather than accepting anything, so a future rewrite
    of either statement fails loudly here instead of silently no-opping.
    """

    def __init__(self, state):
        self.state = state
        self._result = None

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.state.setdefault("executed_sql", []).append(text)
        email = params[0]
        if text.startswith("INSERT INTO subscribers"):
            if email in self.state["active"]:
                inserted = False           # conflict on an already-active row
            elif email in self.state["unsubscribed"]:
                self.state["unsubscribed"].remove(email)
                self.state["active"].append(email)
                inserted = False           # conflict → DO UPDATE (reactivated)
            else:
                self.state["active"].append(email)
                inserted = True            # xmax = 0
            self.state["signups"].append(email)
            self._result = (inserted,)
        elif text.startswith("UPDATE subscribers"):
            if email in self.state["active"]:
                self.state["active"].remove(email)
                self.state["unsubscribed"].append(email)
            self._result = None
        else:
            raise AssertionError(f"unexpected SQL: {text}")

    def fetchone(self):
        return self._result


@pytest.fixture
def fake_db(monkeypatch):
    """In-memory stand-in for the subscribers table.

    Patches `connection` and `query` — the two db.py entry points the module
    uses — rather than the functions under test, so signup(), _do_unsubscribe()
    and list_active_contacts() all run their real logic.
    """
    import contextlib

    state = {"active": [], "unsubscribed": [], "signups": []}

    class _Conn:
        def cursor(self):
            return _FakeCursor(state)

        def commit(self):
            state["committed"] = True

    @contextlib.contextmanager
    def _connection():
        yield _Conn()

    def _query(sql, params=None):
        text = " ".join(sql.split())
        if text.startswith("SELECT email FROM subscribers"):
            assert "NOT unsubscribed" in text, text
            return [{"email": e} for e in state["active"]]
        if text.startswith("SELECT COUNT(*)"):
            assert "NOT unsubscribed" in text, text
            return [{"n": len(state["active"])}]
        if text.startswith("SELECT unsubscribed FROM subscribers WHERE email"):
            email = params[0]
            if email in state["active"]:
                return [{"unsubscribed": False}]
            if email in state["unsubscribed"]:
                return [{"unsubscribed": True}]
            return []
        raise AssertionError(f"unexpected SQL: {text}")

    monkeypatch.setattr(subscribers, "connection", _connection)
    monkeypatch.setattr(subscribers, "query", _query)
    return state


@pytest.fixture
def wired(fake_db):
    """Alias kept for readability: the write paths are already real."""
    return fake_db


# ── Signup ────────────────────────────────────────────────────────────────────

def test_signup_adds_new_address(wired):
    result = subscribers.signup(subscribers.SignupBody(email="New@Example.com"))
    assert result == {"ok": True, "status": "subscribed"}
    # Stored lowercased — the HMAC token signs the lowercased form, so a
    # mixed-case row would produce unsubscribe links that fail verification.
    assert wired["active"] == ["new@example.com"]


def test_signup_is_idempotent_for_active_address(wired):
    wired["active"].append("a@b.com")
    result = subscribers.signup(subscribers.SignupBody(email="a@b.com"))
    assert result["status"] == "subscribed"
    assert wired["active"] == ["a@b.com"]      # no duplicate row
    assert wired["signups"] == []              # and no write at all


def test_signup_reactivates_unsubscribed_address(wired):
    """Returning subscribers report 'reactivated', not 'subscribed' — the
    distinction is what tells a complaint investigation that this was an
    opt-in, not a resurrection of a deleted row."""
    wired["unsubscribed"].append("back@example.com")
    result = subscribers.signup(subscribers.SignupBody(email="back@example.com"))
    assert result["status"] == "reactivated"
    assert wired["active"] == ["back@example.com"]


def test_reactivation_keeps_unsubscribed_at_and_stamps_resubscribed_at(wired):
    """migration 019's rationale: re-signup after unsubscribe must not look
    like a fresh opt-in when a complaint is investigated. unsubscribed_at is
    the record of the LAST opt-out and must survive reactivation; the new
    resubscribed_at column is what stamps the opt-in, conditionally on the
    row having actually been unsubscribed."""
    wired["unsubscribed"].append("back@example.com")
    subscribers.signup(subscribers.SignupBody(email="back@example.com"))

    insert_sql = next(s for s in wired["executed_sql"] if s.startswith("INSERT INTO subscribers"))
    assert "unsubscribed_at = NULL" not in insert_sql
    assert "resubscribed_at" in insert_sql
    assert "CASE WHEN subscribers.unsubscribed" in insert_sql


def test_signup_rejects_malformed_address(wired):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        subscribers.signup(subscribers.SignupBody(email="not-an-email"))
    assert exc.value.status_code == 400


# ── Capacity gate ─────────────────────────────────────────────────────────────

def test_signup_blocked_when_list_is_full(wired, monkeypatch):
    monkeypatch.setenv("MAX_SUBSCRIBERS", "3")
    wired["active"].extend(["a@b.com", "c@d.com", "e@f.com"])

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        subscribers.signup(subscribers.SignupBody(email="new@example.com"))
    assert exc.value.status_code == 403
    assert "full" in exc.value.detail


def test_existing_subscriber_is_never_blocked_by_the_cap(wired, monkeypatch):
    """A full list must not start rejecting the people already on it."""
    monkeypatch.setenv("MAX_SUBSCRIBERS", "2")
    wired["active"].extend(["a@b.com", "c@d.com"])
    assert subscribers.signup(subscribers.SignupBody(email="a@b.com"))["status"] == "subscribed"


# ── Scarcity counter (display-only maths) ─────────────────────────────────────

def test_count_is_floored_for_social_proof(fake_db, monkeypatch):
    monkeypatch.setenv("MAX_SUBSCRIBERS", "100")
    monkeypatch.setenv("SUBSCRIBER_COUNT_FLOOR", "22")
    fake_db["active"].extend(f"u{i}@x.com" for i in range(5))

    data = subscribers.subscriber_count()
    assert data == {"count": 22, "cap": 100, "remaining": 78}


def test_count_uses_real_number_once_it_passes_the_floor(fake_db, monkeypatch):
    monkeypatch.setenv("MAX_SUBSCRIBERS", "100")
    monkeypatch.setenv("SUBSCRIBER_COUNT_FLOOR", "22")
    fake_db["active"].extend(f"u{i}@x.com" for i in range(40))

    assert subscribers.subscriber_count()["count"] == 40


def test_floor_alone_never_shows_the_list_as_full(fake_db, monkeypatch):
    """The seeded number must never close the form — only genuine subscribers
    can do that, or the floor silently disables sign-ups."""
    monkeypatch.setenv("MAX_SUBSCRIBERS", "20")
    monkeypatch.setenv("SUBSCRIBER_COUNT_FLOOR", "50")
    fake_db["active"].extend(f"u{i}@x.com" for i in range(3))

    data = subscribers.subscriber_count()
    assert data["count"] == 19          # capped at cap-1
    assert data["remaining"] == 1


def test_count_reports_full_when_genuinely_full(fake_db, monkeypatch):
    monkeypatch.setenv("MAX_SUBSCRIBERS", "5")
    monkeypatch.setenv("SUBSCRIBER_COUNT_FLOOR", "0")
    fake_db["active"].extend(f"u{i}@x.com" for i in range(5))

    data = subscribers.subscriber_count()
    assert data["count"] == 5 and data["remaining"] == 0


def test_count_serves_stale_rather_than_failing_the_landing_page(fake_db, monkeypatch):
    monkeypatch.setenv("SUBSCRIBER_COUNT_FLOOR", "0")
    monkeypatch.setenv("MAX_SUBSCRIBERS", "100")
    fake_db["active"].extend(f"u{i}@x.com" for i in range(7))
    first = subscribers.subscriber_count()

    def _boom(sql, params=None):
        raise RuntimeError("connection lost")

    monkeypatch.setattr(subscribers, "query", _boom)
    subscribers._count_cache["ts"] = 0.0        # force a refresh attempt
    assert subscribers.subscriber_count() == first


# ── Unsubscribe ───────────────────────────────────────────────────────────────

def test_unsubscribe_link_round_trips(client, wired, monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "test-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.alphamoveai.co.uk")
    wired["active"].append("a@b.com")

    url = subscribers.build_unsubscribe_url("a@b.com")
    token = url.split("t=")[1]

    resp = client.get(f"/api/unsubscribe?email=a@b.com&t={token}")
    assert resp.status_code == 200
    assert "unsubscribed" in resp.text.lower()
    assert wired["unsubscribed"] == ["a@b.com"]


def test_unsubscribe_rejects_forged_token(client, wired, monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "test-secret")
    wired["active"].append("a@b.com")

    resp = client.get("/api/unsubscribe?email=a@b.com&t=deadbeef")
    assert resp.status_code == 400
    assert wired["unsubscribed"] == []          # nothing changed


def test_one_click_post_unsubscribes(client, wired, monkeypatch):
    """RFC 8058: Gmail/Outlook POST this endpoint from the native button."""
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "test-secret")
    wired["active"].append("a@b.com")
    token = subscribers._unsubscribe_token("a@b.com")

    resp = client.post(f"/api/unsubscribe?email=a@b.com&t={token}")
    assert resp.status_code == 200
    assert wired["unsubscribed"] == ["a@b.com"]


def test_token_is_case_insensitive_on_the_address(monkeypatch):
    """Signing lowercases, so a link built for A@B.com must verify for a@b.com
    — otherwise anyone who typed a capital at signup gets a dead link."""
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "test-secret")
    assert subscribers._verify_token("a@b.com", subscribers._unsubscribe_token("A@B.com"))


def test_token_changes_with_the_secret(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "secret-one")
    first = subscribers._unsubscribe_token("a@b.com")
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "secret-two")
    assert subscribers._unsubscribe_token("a@b.com") != first
