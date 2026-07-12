"""Shared request helpers: client-IP resolution and in-process rate limiting.

Both existed as per-module copies (news.py, research.py) that keyed rate
limits on the FIRST hop of X-Forwarded-For. That hop is client-supplied — a
scripted caller could send a random XFF header per request and mint a fresh
rate-limit bucket every time, bypassing the caps that guard DeepSeek spend
and the comment queue. client_ip() below keys on headers our own proxies
actually wrote instead.
"""
import threading
import time

from fastapi import Request


def client_ip(request: Request) -> str:
    """Best-available client IP for rate-limit keying.

    Deployment: browser → Vercel (the frontend's /api rewrite) → Traefik
    (Dokploy) → uvicorn. Resolution order:

    1. x-vercel-forwarded-for — Vercel sets this to the real browser IP on
       every request it proxies and overwrites any client-supplied value, so
       it's authoritative for all legitimate site traffic.
    2. The RIGHTMOST X-Forwarded-For hop — the one entry recorded by our own
       Traefik from the actual TCP peer. The leftmost hop is client-supplied
       and trivially forged, which is why it must never be the key.
    3. The socket peer, when no proxy headers exist (local dev).

    A caller hitting the API origin directly (bypassing Vercel) can forge
    header 1 — but forging only *diversifies* their buckets; it can't impersonate
    another user's quota, and the endpoints that spend money pair this with a
    global in-window cap that bounds total damage regardless of key spoofing.
    """
    vercel = request.headers.get("x-vercel-forwarded-for", "")
    if vercel:
        return vercel.split(",")[0].strip()
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    """Thread-safe per-key sliding-window counter (per worker process).

    allow(key) records a hit and returns True while the key has made fewer
    than `limit` hits in the trailing `window` seconds; False (nothing
    recorded) once it's at the cap. The key map is bounded: past `max_keys`
    entries, expired keys are pruned so a slow scan across many IPs can't
    grow it forever (the process is long-lived on Dokploy).

    In-process, so with N workers the effective ceiling is limit × N — fine
    for abuse damping; use a DB-backed window (news.summary_rate_hits) when
    the cap must be exact across workers.
    """

    def __init__(self, limit: int, window_seconds: float, max_keys: int = 1000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            if len(self._hits) > self.max_keys:
                for k in [
                    k for k, v in self._hits.items()
                    if not v or v[-1] < now - self.window
                ]:
                    del self._hits[k]
            hits = [t for t in self._hits.get(key, []) if t > now - self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True
