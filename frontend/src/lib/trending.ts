import { backendUrl } from "./seo";
import { fetchRetry } from "./fetchRetry";

// Shape mirrors the rows backend/prices.py's trending() builds. Only `symbol`
// is guaranteed non-null — `pct` is null when the streak's starting close was
// zero, and name/sector/market_cap come from a LEFT JOIN that can miss.
export type TrendingRow = {
  symbol: string;
  name: string;
  streak: number;
  price: number | null;
  pct: number | null;
  sector: string | null;
  currency: string;
  market_cap: number | null;
};

export type Trending = {
  risers: TrendingRow[];
  fallers: TrendingRow[];
};

// Prices land once a day from the prices cron (16:35 UK), and the backend keys
// its own cache on the latest price date, so hourly revalidation is plenty.
const REVALIDATE = 3600;

// Server-side fetch of the risers/fallers lists. Returns null on any failure so
// the client falls back to fetching in the browser rather than rendering an
// empty page — the backend response is cheap now that the window scan is
// date-bounded, so the fallback costs little when it fires.
export async function getTrending(): Promise<Trending | null> {
  try {
    const res = await fetchRetry(backendUrl("/api/trending"), {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data?.risers) && Array.isArray(data?.fallers)
      ? (data as Trending)
      : null;
  } catch {
    return null;
  }
}
