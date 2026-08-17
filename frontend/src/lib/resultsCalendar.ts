import { backendUrl } from "./seo";
import { fetchRetry } from "./fetchRetry";

// Shapes mirror backend/results_calendar.py's get_week serialiser.
export type CalendarCompany = {
  symbol: string;
  name: string;
  event_type: string;
  event_label: string;
  sector: string | null;
  ftse_index: string | null;
  // "diary" (the Sharecast company diary, our primary source) or "yfinance"
  // (FTSE 100 cross-check, which fills the diary's outright omissions). Not
  // rendered — carried so a wrong date can be traced to its source from the
  // response alone. Optional because rows written before the cross-check
  // shipped lack it. Rows predating 2026-08-17 came from Digital Look, which
  // shares the value "diary"; the distinction stopped mattering when that
  // source went dark.
  source?: string;
};

export type CalendarDay = {
  date: string;
  weekday: string;
  companies: CalendarCompany[];
};

// Health of the primary source (the Sharecast company diary) for the week being
// shown. Distinct from `updated_at`, which is a max over the week's rows and so
// stays fresh on the yfinance cross-check alone while the diary is down.
export type CalendarSourceStatus = {
  // Last time the diary wrote a row for ANY week — i.e. its last good scrape.
  diary_last_success: string | null;
  // True when this week is one the cron maintains AND the diary has been silent
  // longer than stale_after_hours. Past weeks are never stale: nothing refreshes
  // them by design.
  stale: boolean;
  stale_after_hours: number;
  age_hours: number | null;
};

export type ResultsCalendar = {
  week_start: string;
  week_end: string;
  prev_week: string;
  next_week: string;
  is_current_week: boolean;
  total: number;
  // Diary rows we could not map to a ticker (bonds, GDRs, micro-cap AIM). Not
  // rendered — kept on the response as a health signal, since a sudden jump here
  // means the name resolver has regressed rather than the week being quiet.
  unmatched: number;
  updated_at: string | null;
  // Optional: responses served by a backend older than the staleness banner
  // lack it, and the page must render normally rather than blank in that case.
  source_status?: CalendarSourceStatus;
  days: CalendarDay[];
};

// The underlying diary is re-scraped once a day by the cron, and the displayed
// week only turns over on a Saturday, so hourly revalidation is plenty.
const REVALIDATE = 3600;

// Server-side fetch of one week. Returns null on any failure so the client falls
// back to fetching in the browser rather than rendering an empty grid.
export async function getResultsCalendar(week?: string): Promise<ResultsCalendar | null> {
  try {
    const qs = week ? `?week=${encodeURIComponent(week)}` : "";
    const res = await fetchRetry(backendUrl(`/api/results-calendar${qs}`), {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data?.days) ? (data as ResultsCalendar) : null;
  } catch {
    return null;
  }
}
