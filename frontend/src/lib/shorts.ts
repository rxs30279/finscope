import { backendUrl } from "./seo";
import { fetchRetry } from "./fetchRetry";

// Shapes mirror backend/shorts.py's _build_leaderboard serialiser.
export type ShortLeaderRow = {
  isin: string;
  name: string;
  symbol: string | null;
  pct: number;
  change_1m: number | null;
  change_window: number;
  window_start: string;
  history: { date: string; pct: number }[];
  // ~3-month daily close series (pence) for the price sparkline; empty for
  // out-of-universe issuers with no resolved symbol.
  price_history: { date: string; close: number }[];
  // The four screener composites + index label (all null for out-of-universe issuers).
  momentum_score: number | null;
  quality_score: number | null;
  value_score: number | null;
  risk_score: number | null;
  ftse_index: string | null;
};

export type ShortLeaderboard = {
  as_of: string | null;
  rows: ShortLeaderRow[];
};

// ANSP files land once per working day (~12pm UK) and the backend edge-caches
// for 6h, so an hourly revalidate keeps the SSR HTML fresh without hammering it.
const REVALIDATE = 3600;

// Server-side fetch of the /most-shorted leaderboard. Returns null on any
// failure so the client falls back to fetching in the browser instead of
// rendering an empty page.
export async function getMostShorted(): Promise<ShortLeaderboard | null> {
  try {
    const res = await fetchRetry(backendUrl("/api/shorts/top"), {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data?.rows) ? (data as ShortLeaderboard) : null;
  } catch {
    return null;
  }
}
