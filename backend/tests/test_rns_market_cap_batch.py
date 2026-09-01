"""The market-cap batch must not silently evict real companies from the digest.

Two failure modes, both of which used to end the same way — a row quietly
absent from the morning email:

1. **Unbounded hang.** yfinance's `.info` takes no timeout, so the only ceiling
   was the kernel's TCP retransmit budget (tcp_retries2=15 ≈ 15m24s). On
   2026-09-01 one hung Yahoo socket stalled the digest for 16 minutes: the call
   sits under the send's advisory lock and *before* its first log line, so it
   presented as total silence — no email, no error, no pipeline_runs stamp, and
   cron-job.org showing a green 202.

2. **Over-eager blacklisting.** `_MC_FAIL_CACHE` has a 30-day TTL and exists for
   tickers Yahoo says don't exist. A bare `except Exception` also fed it every
   transient failure, so one YFRateLimitError would drop a real company out of
   the digest for a month — its rows fall below _MIN_MARKET_CAP for having no
   cap, and nothing is logged.
"""
import sys, os, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rns


def _clear_caches():
    rns._MC_CACHE.clear()
    rns._MC_FAIL_CACHE.clear()


def _install(monkeypatch, info_fn):
    """Swap yfinance out at the import site inside _fetch_market_caps_batch.

    The function does `import yfinance as yf` locally, so patching sys.modules
    is what reaches it. `info_fn` may return a market cap or raise.
    """
    class _Ticker:
        def __init__(self, sym):
            self._sym = sym

        @property
        def info(self):
            return {"marketCap": info_fn(self._sym)}

    class _FakeYF:
        Ticker = _Ticker

    monkeypatch.setitem(sys.modules, "yfinance", _FakeYF)


# ── 1. the hang ───────────────────────────────────────────────────────────────

def test_returns_promptly_when_one_symbol_hangs(monkeypatch):
    """A single wedged symbol must not hold the whole batch."""
    _clear_caches()
    release = threading.Event()

    def _info(sym):
        if sym == "HUNG.L":
            release.wait(30)          # simulates the un-timeout-able socket
            return 1
        return 5_000_000_000

    monkeypatch.setattr(rns, "_MC_BATCH_TIMEOUT_S", 0.5)
    _install(monkeypatch, _info)

    t0 = time.time()
    try:
        out = rns._fetch_market_caps_batch(["AAA.L", "HUNG.L", "BBB.L"])
        elapsed = time.time() - t0
    finally:
        release.set()

    assert elapsed < 5, f"batch took {elapsed:.1f}s — the timeout did not fire"
    assert out["AAA.L"] == 5_000_000_000
    assert out["BBB.L"] == 5_000_000_000
    assert "HUNG.L" not in out


def test_timed_out_symbol_is_not_blacklisted(monkeypatch):
    """A stall is not evidence the ticker is invalid."""
    _clear_caches()
    release = threading.Event()

    def _info(sym):
        if sym == "HUNG.L":
            release.wait(30)
            return 1
        return None                   # answered: genuinely has no marketCap

    monkeypatch.setattr(rns, "_MC_BATCH_TIMEOUT_S", 0.5)
    _install(monkeypatch, _info)

    try:
        rns._fetch_market_caps_batch(["HUNG.L", "GONE.L"])
    finally:
        release.set()

    assert "HUNG.L" not in rns._MC_FAIL_CACHE, "a stalled symbol was blacklisted"
    assert "GONE.L" in rns._MC_FAIL_CACHE, "a real miss should still be cached"


def test_happy_path_unchanged(monkeypatch):
    _clear_caches()
    monkeypatch.setattr(rns, "_MC_BATCH_TIMEOUT_S", 10)
    _install(monkeypatch, lambda sym: 123)

    out = rns._fetch_market_caps_batch(["AAA.L", "BBB.L"])

    assert out == {"AAA.L": 123, "BBB.L": 123}
    assert set(rns._MC_CACHE) == {"AAA.L", "BBB.L"}
    assert rns._MC_FAIL_CACHE == {}


# ── 2. permanent vs transient ─────────────────────────────────────────────────

def test_rate_limit_does_not_blacklist(monkeypatch):
    """The 2026-09-01 regression: a transient 429 must stay retryable."""
    from yfinance.exceptions import YFRateLimitError
    _clear_caches()
    monkeypatch.setattr(rns, "_MC_BATCH_TIMEOUT_S", 10)

    def _info(sym):
        raise YFRateLimitError()

    _install(monkeypatch, _info)
    out = rns._fetch_market_caps_batch(["REAL.L"])

    assert out == {}
    assert "REAL.L" not in rns._MC_FAIL_CACHE, \
        "a rate-limited real company was blacklisted for 30 days"


def test_invalid_ticker_is_still_blacklisted(monkeypatch):
    """The case the negative cache exists for — a guessed .L that 404s."""
    import urllib.error
    _clear_caches()
    monkeypatch.setattr(rns, "_MC_BATCH_TIMEOUT_S", 10)

    def _info(sym):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    _install(monkeypatch, _info)
    rns._fetch_market_caps_batch(["ZZQQXX.L"])

    assert "ZZQQXX.L" in rns._MC_FAIL_CACHE


def test_generic_network_error_does_not_blacklist(monkeypatch):
    _clear_caches()
    monkeypatch.setattr(rns, "_MC_BATCH_TIMEOUT_S", 10)

    def _info(sym):
        raise ConnectionResetError("connection reset by peer")

    _install(monkeypatch, _info)
    rns._fetch_market_caps_batch(["REAL.L"])

    assert "REAL.L" not in rns._MC_FAIL_CACHE


# ── _is_missing_ticker, directly ──────────────────────────────────────────────

def test_is_missing_ticker_reads_status_from_each_client_shape():
    """urllib exposes .code, requests/curl_cffi expose .response.status_code."""
    import urllib.error
    assert rns._is_missing_ticker(
        urllib.error.HTTPError("u", 404, "Not Found", {}, None)) is True
    assert rns._is_missing_ticker(
        urllib.error.HTTPError("u", 500, "Server Error", {}, None)) is False

    class _Resp:
        status_code = 404

    class _ReqErr(Exception):
        response = _Resp()

    assert rns._is_missing_ticker(_ReqErr()) is True

    class _Flat(Exception):
        status_code = 503

    assert rns._is_missing_ticker(_Flat()) is False


def test_curl_cffi_zero_code_does_not_shadow_the_real_status():
    """The shape prod actually raises. curl_cffi.HTTPError inherits `.code`
    from CurlError, where it is the curl error code and reads 0 on an HTTP
    error — while the real status sits on `.response`. Probing `.code` first
    classified every 404 as transient, which an urllib-shaped fake did not
    catch. Verified against prod: ZZQQXX.L raises exactly this."""
    class _Resp:
        status_code = 404

    class _CurlHTTPError(OSError):
        code = 0                      # curl error code, NOT the HTTP status
        response = _Resp()

    exc = _CurlHTTPError("HTTP Error 404: ")
    assert rns._is_missing_ticker(exc) is True

    class _CurlServerError(OSError):
        code = 0

        class response:
            status_code = 503

    assert rns._is_missing_ticker(_CurlServerError()) is False


def test_rate_limit_is_transient_even_though_it_is_a_yf_exception():
    from yfinance.exceptions import YFRateLimitError
    assert rns._is_missing_ticker(YFRateLimitError()) is False


def test_unknown_exception_defaults_to_transient():
    """Fail safe: an unrecognised error retries rather than blacklisting."""
    assert rns._is_missing_ticker(RuntimeError("something odd")) is False
