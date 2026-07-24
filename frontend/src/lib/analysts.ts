import { backendUrl } from "./seo";

// Shapes mirror backend/analysts.py's serialisers. Loose typing — the client
// component (AnalystMonitorTab.js) already handles this data untyped.
export type AnalystRow = Record<string, unknown>;

// Analyst snapshots land once daily and the backend edge-caches for 6h, so an
// hourly revalidate keeps the SSR HTML fresh without hammering the API.
const REVALIDATE = 3600;

// Must match MOVER_WINDOW_DAYS in components/AnalystMonitorTab.js so the SSR
// payload is identical to what a client refetch would return.
const MOVER_WINDOW_DAYS = 30;

async function getList(path: string): Promise<AnalystRow[] | null> {
  try {
    const res = await fetch(backendUrl(path), { next: { revalidate: REVALIDATE } });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}

// Server-side fetch of the /analysts page data. Either field is null on
// failure so the client falls back to fetching in the browser instead of
// rendering an empty page.
export async function getAnalystsData(): Promise<{
  latest: AnalystRow[] | null;
  movers: AnalystRow[] | null;
}> {
  const [latest, movers] = await Promise.all([
    getList("/api/analysts/latest"),
    getList(`/api/analysts/movers?window_days=${MOVER_WINDOW_DAYS}`),
  ]);
  return { latest, movers };
}
