// Canonical site origin, used for metadataBase, OG/canonical URLs, the sitemap,
// and server-side API fetches. Override per-environment with NEXT_PUBLIC_SITE_URL.
export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") || "https://app.alphamoveai.co.uk";

export const SITE_NAME = "Alpha Move AI";

// The browser uses a relative `/api` (see lib/api.ts), but server components and
// metadata routes run on the server where relative URLs don't resolve — they need
// an absolute origin. In production Vercel routes `${SITE_URL}/api/*` to the Python
// backend (vercel.json), so this loops back to the same deployment.
export function apiUrl(path: string): string {
  return `${SITE_URL}${path.startsWith("/") ? "" : "/"}${path}`;
}

// Server-side data fetches should hit the FastAPI backend directly rather than
// looping out through the public domain + Vercel edge rewrite (the edge never
// caches /api — rewrite responses are always MISS — so the extra hop is pure
// latency). BACKEND_ORIGIN is the same var next.config.ts proxies to; when it's
// unset (e.g. some preview/local setups) we fall back to apiUrl()'s public loop
// so nothing breaks.
// JSON-LD payloads are injected with dangerouslySetInnerHTML; escape "<" so a
// DB-sourced value containing "</script>" can't break out of the script tag.
export function jsonLdString(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

export function backendUrl(path: string): string {
  const origin =
    process.env.BACKEND_ORIGIN?.replace(/\/$/, "") ||
    (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");
  const p = `${path.startsWith("/") ? "" : "/"}${path}`;
  return origin ? `${origin}${p}` : apiUrl(path);
}
