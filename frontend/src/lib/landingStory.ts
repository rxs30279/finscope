import { backendUrl } from "./seo";
import { fetchRetry } from "./fetchRetry";

// Shape mirrors backend/landing_story.py current_story().
//
// Prices are PENCE (matching price_history), gap_pct is a percentage already
// multiplied out, and `ohlc` is [label, open, high, low, close] oldest-first
// with `event_idx` pointing at the announcement day's bar.
export type StoryBar = [string, number, number, number, number];

// [time, ticker, headline] straight off that morning's wire, unfiltered — the
// routine noise is the point the funnel then makes.
export type WireLine = [string, string, string];

export interface StoryWire {
  total: number;
  survived: number;
  top: number;
  sample: WireLine[];
}

export interface LandingStory {
  symbol: string;
  company_name: string | null;
  headline: string | null;
  url: string | null;
  published_at: string;
  llm_score: number | null;
  sentiment: "positive" | "negative" | "neutral" | null;
  thesis: string | null;
  sector: string | null;
  ftse_index: string | null;
  prev_close: number;
  event_open: number;
  event_close: number | null;
  gap_pct: number;
  ohlc: StoryBar[];
  event_idx: number;
  // Null for rows snapshotted before the funnel existed — the block then skips
  // its opening scenes and shows the card straight away.
  wire: StoryWire | null;
  picked_at: string;
}

// The row is rewritten once a week by a Monday cron, so an hour of staleness
// costs nothing and keeps the most-hit route off the backend.
const REVALIDATE = 3600;

// Returns null on ANY failure — including "no story picked yet" — so the
// landing page simply omits the section rather than breaking. Same degradation
// getResearchPosts() already relies on in page.tsx.
export async function getLandingStory(): Promise<LandingStory | null> {
  try {
    const res = await fetchRetry(backendUrl("/api/landing/story"), {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as LandingStory | null;
    // Guard the two fields the chart cannot render without.
    if (!data || !Array.isArray(data.ohlc) || data.ohlc.length === 0) return null;
    return data;
  } catch {
    return null;
  }
}

// Pence, at the precision the LSE quotes them.
export function fmtPence(v: number): string {
  return `${v.toFixed(v >= 1000 ? 0 : 1)}p`;
}

// Signed, with a real minus sign rather than a hyphen.
export function fmtGap(pct: number): string {
  return `${pct < 0 ? "−" : "+"}${Math.abs(pct).toFixed(1)}%`;
}
