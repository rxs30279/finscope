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
