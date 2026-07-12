"""request_utils (shared client-IP resolution + rate limiter) and the symbol-
list guards on /api/quotes and /api/watchlist.

The client-IP tests encode the anti-spoofing contract: the rate-limit key must
never come from a client-controlled value (the leftmost X-Forwarded-For hop),
only from headers our own proxies wrote.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException

import main
from request_utils import client_ip, SlidingWindowLimiter


class _Client:
    def __init__(self, host):
        self.host = host


class _Req:
    """Duck-typed stand-in for fastapi.Request (headers.get + client.host)."""
    def __init__(self, headers=None, peer="10.0.0.1"):
        self.headers = headers or {}
        self.client = _Client(peer)


# ── client_ip ────────────────────────────────────────────────────────────────
def test_prefers_vercel_header():
    req = _Req({
        "x-vercel-forwarded-for": "203.0.113.7",
        "x-forwarded-for": "6.6.6.6, 198.51.100.1",
    })
    assert client_ip(req) == "203.0.113.7"


def test_xff_uses_rightmost_hop_not_client_supplied_first():
    # The leftmost entry is attacker-supplied; the rightmost was appended by
    # our own proxy from the real TCP peer.
    req = _Req({"x-forwarded-for": "6.6.6.6, 7.7.7.7, 198.51.100.1"})
    assert client_ip(req) == "198.51.100.1"


def test_falls_back_to_socket_peer():
    assert client_ip(_Req(peer="192.0.2.9")) == "192.0.2.9"


def test_spoofed_xff_cannot_mint_fresh_buckets():
    # Rotating the client-controlled first hop must not change the key when
    # the proxy-appended rightmost hop stays the same.
    a = client_ip(_Req({"x-forwarded-for": "1.1.1.1, 198.51.100.1"}))
    b = client_ip(_Req({"x-forwarded-for": "2.2.2.2, 198.51.100.1"}))
    assert a == b == "198.51.100.1"


# ── SlidingWindowLimiter ─────────────────────────────────────────────────────
def test_limiter_allows_up_to_limit_then_blocks():
    lim = SlidingWindowLimiter(limit=3, window_seconds=60)
    assert [lim.allow("ip1") for _ in range(4)] == [True, True, True, False]
    # Other keys are unaffected.
    assert lim.allow("ip2") is True


def test_limiter_window_expires(monkeypatch):
    lim = SlidingWindowLimiter(limit=1, window_seconds=60)
    t = [1000.0]
    monkeypatch.setattr("request_utils.time.time", lambda: t[0])
    assert lim.allow("ip") is True
    assert lim.allow("ip") is False
    t[0] += 61  # past the window → the old hit no longer counts
    assert lim.allow("ip") is True


def test_limiter_prunes_expired_keys(monkeypatch):
    lim = SlidingWindowLimiter(limit=1, window_seconds=60, max_keys=5)
    t = [1000.0]
    monkeypatch.setattr("request_utils.time.time", lambda: t[0])
    for i in range(6):
        lim.allow(f"ip{i}")
    t[0] += 61
    lim.allow("fresh")  # triggers the prune of the six expired keys
    assert set(lim._hits) == {"fresh"}


# ── symbol-list guards ───────────────────────────────────────────────────────
def test_parse_symbol_list_caps_count():
    too_many = ",".join(f"S{i}.L" for i in range(main._MAX_LIST_SYMBOLS + 1))
    with pytest.raises(HTTPException) as e:
        main._parse_symbol_list(too_many)
    assert e.value.status_code == 400


def test_parse_symbol_list_drops_garbage_keeps_real():
    parsed = main._parse_symbol_list(
        "VOD.L, ../etc/passwd, ^FTSE, <script>, GBPUSD=X, VOD.L"
    )
    # Valid shapes kept in order, dupes and junk dropped.
    assert parsed == ["VOD.L", "^FTSE", "GBPUSD=X"]


def test_quotes_endpoint_rejects_oversized_request(client):
    too_many = ",".join(f"S{i}.L" for i in range(main._MAX_LIST_SYMBOLS + 1))
    r = client.get("/api/quotes", params={"symbols": too_many})
    assert r.status_code == 400


def test_quotes_endpoint_ignores_garbage_symbols(client):
    # All-garbage input short-circuits to {} without touching yfinance.
    r = client.get("/api/quotes", params={"symbols": "../x,<script>,a b"})
    assert r.status_code == 200
    assert r.json() == {}
