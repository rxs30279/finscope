// Server-side fetches cross the public internet to the FastAPI backend on
// Hetzner, and that hop intermittently drops a connection before TLS completes:
// undici reports `TypeError: fetch failed` wrapping `UND_ERR_SOCKET` ("other
// side closed") or `ECONNRESET`, with `bytesWritten: ~330, bytesRead: 0` — the
// ClientHello went out and nothing came back.
//
// Investigated 2026-07-25 and the origin shows NO trace of these: CPU idle
// (~96%), no container restarts at the failure times, Traefik never logs them,
// conntrack near-empty, and a 40-connection parallel TLS burst from a UK client
// got 40/40 clean. So it is a transient failure somewhere in the path we cannot
// fix at the source — one immediate retry is the pragmatic answer.
//
// Two deliberate constraints:
//
//   1. Retries ONLY on network-level failures, never on an HTTP status. A 500
//      from the backend is a real answer; re-asking just doubles the load on a
//      box that is already unhappy. Callers keep their own `res.ok` handling.
//
//   2. No AbortSignal/timeout. undici's own connect timeout (10s) already bounds
//      a hung handshake, which is precisely the failure mode here, and passing a
//      signal risks opting the request out of Next's data cache — which would
//      quietly turn every ISR hit into a live backend call.
const RETRY_DELAY_MS = 150;

// undici surfaces socket failures as `TypeError: fetch failed` with the real
// error hanging off `cause`. Anything else (a bad URL, an aborted request, a
// JSON parse failure downstream) is a genuine bug and must propagate unchanged.
function isTransientNetworkError(err: unknown): boolean {
  const cause = (err as { cause?: unknown } | undefined)?.cause;
  const code = (cause as { code?: string } | undefined)?.code;
  return (
    code === "UND_ERR_SOCKET" || // "other side closed" — the one we actually see
    code === "UND_ERR_CONNECT_TIMEOUT" ||
    code === "ECONNRESET" ||
    code === "ECONNREFUSED" ||
    code === "ETIMEDOUT" ||
    code === "EPIPE"
  );
}

// Drop-in replacement for `fetch` in server components / metadata routes.
// Same signature, same return value — including `next: { revalidate }`, which is
// passed straight through so caching behaviour is unchanged.
export async function fetchRetry(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (err) {
    if (!isTransientNetworkError(err)) throw err;
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    // A second failure propagates to the caller, which already degrades to a
    // client-side fetch (or, for research posts, throws so ISR keeps serving the
    // last good render rather than caching a 404).
    return fetch(url, init);
  }
}
