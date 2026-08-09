"""Throttle handling on the investegate fetch path.

The point of these tests: before _RateLimited existed, a 429 was an HTTPError,
HTTPError subclasses URLError, and the generic handlers in _run_ingest /
_backfill_summaries swallowed it and broke the loop. A block and a quiet news
day produced identical data and identical logs. Every test here is about
keeping those two cases distinguishable.
"""
import urllib.error

import pytest

import rns


def _http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError(
        url="https://www.investegate.co.uk/", code=code, msg="throttled",
        hdrs=headers, fp=None,
    )


# ── Retry-After parsing ───────────────────────────────────────────────────────

def test_parse_retry_after_seconds():
    assert rns._parse_retry_after("30") == 30.0


def test_parse_retry_after_http_date():
    # A date in the past clamps to 0 rather than going negative.
    assert rns._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


@pytest.mark.parametrize("value", [None, "", "not-a-date"])
def test_parse_retry_after_junk(value):
    assert rns._parse_retry_after(value) is None


# ── _urlopen_polite ───────────────────────────────────────────────────────────

def test_retries_then_succeeds(monkeypatch):
    """A single 429 is retried, not surfaced — transient throttles self-heal."""
    calls = []
    monkeypatch.setattr(rns.time, "sleep", lambda s: calls.append(s))

    attempts = {"n": 0}

    class _Resp:
        def read(self): return b"<html>ok</html>"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429)
        return _Resp()

    monkeypatch.setattr(rns.urllib.request, "urlopen", fake_urlopen)

    assert rns._urlopen_polite("https://x/", 10) == "<html>ok</html>"
    assert attempts["n"] == 2
    assert calls == [rns._THROTTLE_BACKOFF_S[0]]


def test_exhausted_retries_raise_rate_limited(monkeypatch):
    monkeypatch.setattr(rns.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        rns.urllib.request, "urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(_http_error(429)),
    )
    with pytest.raises(rns._RateLimited) as exc:
        rns._urlopen_polite("https://x/", 10)
    assert exc.value.code == 429


def test_rate_limited_is_not_a_urlerror():
    """The whole point — the old generic handlers must not catch this."""
    assert not issubclass(rns._RateLimited, urllib.error.URLError)


def test_honours_retry_after_header(monkeypatch):
    # Pin the cap: _backoff_cap_s() reads the wall clock, and a 7s wait is
    # allowed outside the digest window but not inside it. Without this the
    # test passes or fails depending on the time of day it runs.
    monkeypatch.setattr(rns, "_backoff_cap_s", lambda now=None: rns._RETRY_AFTER_CAP_S)
    waits = []
    monkeypatch.setattr(rns.time, "sleep", lambda s: waits.append(s))
    attempts = {"n": 0}

    class _Resp:
        def read(self): return b"ok"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429, retry_after="7")
        return _Resp()

    monkeypatch.setattr(rns.urllib.request, "urlopen", fake_urlopen)
    rns._urlopen_polite("https://x/", 10)
    assert waits == [7.0]


def test_long_retry_after_gives_up_immediately(monkeypatch):
    """Waiting longer than the cap just collides with the next */15 run."""
    monkeypatch.setattr(rns, "_backoff_cap_s", lambda now=None: rns._RETRY_AFTER_CAP_S)
    waits = []
    monkeypatch.setattr(rns.time, "sleep", lambda s: waits.append(s))
    monkeypatch.setattr(
        rns.urllib.request, "urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(
            _http_error(429, retry_after=str(int(rns._RETRY_AFTER_CAP_S) + 60))
        ),
    )
    with pytest.raises(rns._RateLimited):
        rns._urlopen_polite("https://x/", 10)
    assert waits == []  # never slept


def test_non_throttle_http_error_propagates(monkeypatch):
    """A 500 is a real failure, not a throttle — must not become _RateLimited."""
    monkeypatch.setattr(rns.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        rns.urllib.request, "urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(_http_error(500)),
    )
    with pytest.raises(urllib.error.HTTPError):
        rns._urlopen_polite("https://x/", 10)


# ── Digest-deadline guard ─────────────────────────────────────────────────────

def _at(h, m):
    from datetime import datetime
    return datetime(2026, 8, 10, h, m, tzinfo=rns._UK_TZ)


def _clock_offset(t, minutes):
    """`t` (a datetime.time) shifted by `minutes`, same day as _at()."""
    total = t.hour * 60 + t.minute + minutes
    return _at((total // 60) % 24, total % 60)


# The window is rns._URGENT_WINDOW = (lo, DIGEST_SEND_UK) — DIGEST_SEND_UK is
# env-configurable (see rns.py), so these must be derived from the live bounds
# rather than fixed clock times or a fixed window width. A test written
# against "45 minutes before send" silently assumed the window is exactly 45
# min wide, which only held while the send was hardcoded at 07:30 (lo=06:30).

@pytest.mark.parametrize("offset_from", ["lo", "lo_plus_1", "hi_minus_1"])
def test_cap_is_tight_inside_digest_window(offset_from):
    """The morning drop must reach the send — don't sleep through it."""
    lo, hi = rns._URGENT_WINDOW
    now = {
        "lo": _at(lo.hour, lo.minute),
        "lo_plus_1": _clock_offset(lo, 1),
        "hi_minus_1": _clock_offset(hi, -1),
    }[offset_from]
    assert rns._backoff_cap_s(now) == rns._URGENT_BACKOFF_CAP_S


@pytest.mark.parametrize("offset_from", ["lo_minus_1", "hi", "far_after_hi"])
def test_cap_is_relaxed_outside_digest_window(offset_from):
    """Boundaries included: the send itself is when the risk has passed."""
    lo, hi = rns._URGENT_WINDOW
    now = {
        "lo_minus_1": _clock_offset(lo, -1),
        "hi": _at(hi.hour, hi.minute),
        "far_after_hi": _clock_offset(hi, 600),  # 10h later — well clear of any morning send
    }[offset_from]
    assert rns._backoff_cap_s(now) == rns._RETRY_AFTER_CAP_S


def test_morning_throttle_fails_fast_rather_than_sleeping(monkeypatch):
    """The regression this guard exists for: a hostile Retry-After during the
    07:00 drop must not burn the digest's slack."""
    monkeypatch.setattr(rns, "_backoff_cap_s", lambda now=None: rns._URGENT_BACKOFF_CAP_S)
    waits = []
    monkeypatch.setattr(rns.time, "sleep", lambda s: waits.append(s))
    monkeypatch.setattr(
        rns.urllib.request, "urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(_http_error(429, retry_after="45")),
    )
    with pytest.raises(rns._RateLimited):
        rns._urlopen_polite("https://x/", 10)
    assert waits == []  # would have been 45s + 45s before the cap


def test_default_backoff_truncated_in_morning_window(monkeypatch):
    """The 20s second backoff also exceeds the morning cap — one retry, then out."""
    monkeypatch.setattr(rns, "_backoff_cap_s", lambda now=None: rns._URGENT_BACKOFF_CAP_S)
    waits = []
    monkeypatch.setattr(rns.time, "sleep", lambda s: waits.append(s))
    monkeypatch.setattr(
        rns.urllib.request, "urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(_http_error(429)),
    )
    with pytest.raises(rns._RateLimited):
        rns._urlopen_polite("https://x/", 10)
    assert waits == [5.0]  # 5s allowed, 20s exceeds the cap
    assert sum(waits) <= rns._URGENT_BACKOFF_CAP_S


# ── Callers surface it ────────────────────────────────────────────────────────

def test_ingest_reports_rate_limited(monkeypatch):
    monkeypatch.setattr(
        rns, "_fetch_page",
        lambda page: (_ for _ in ()).throw(rns._RateLimited(429, "https://x/")),
    )
    result = rns._run_ingest(max_pages=5, stop_on_known=True, sleep_s=0)
    assert result["rate_limited"] is True
    assert result["processed"] == 0


def test_ingest_not_rate_limited_on_quiet_day(monkeypatch):
    """The contrast case: no new rows must NOT look like a throttle."""
    monkeypatch.setattr(rns, "_fetch_page", lambda page: "<html></html>")
    monkeypatch.setattr(rns, "_parse_rows", lambda html: [])
    result = rns._run_ingest(max_pages=5, stop_on_known=True, sleep_s=0)
    assert result["rate_limited"] is False


def test_backfill_stops_on_throttle(monkeypatch):
    """Must abort the batch, not burn the remaining `limit` on a blocked host."""
    rows = [{"id": i, "url": f"https://x/{i}"} for i in range(10)]
    monkeypatch.setattr(rns, "_query", lambda sql, params=None: rows)
    monkeypatch.setattr(rns.time, "sleep", lambda s: None)

    seen = []

    def fake_fetch(url, timeout=15):
        seen.append(url)
        raise rns._RateLimited(429, url)

    monkeypatch.setattr(rns, "_fetch_summary_and_body", fake_fetch)

    result = rns._backfill_summaries(limit=10, sleep_s=0, tiers=("A", "B"))
    assert result["rate_limited"] is True
    assert len(seen) == 1  # stopped after the first, did not try all 10
