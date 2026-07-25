import { backendUrl } from "./seo";
import { fetchRetry } from "./fetchRetry";

// Shape mirrors backend/showcase.py's approved-list serialiser. Loose typing —
// the client component (HighImpactRnsTab.js) already handles this data untyped.
export type ShowcaseRow = Record<string, unknown>;

// 5-minute max-staleness: bounds how long a fresh approval/archive takes to
// appear on the public page, served stale-while-revalidate in the meantime.
const REVALIDATE = 300;

// Server-side fetch of the approved showcase — the /high-impact-rns index.
// Returns null on any failure so the client falls back to fetching in the
// browser instead of rendering an empty list.
export async function getShowcase(): Promise<ShowcaseRow[] | null> {
  try {
    const res = await fetchRetry(backendUrl("/api/showcase"), {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}
