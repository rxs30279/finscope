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
};

export type CalendarDay = {
  date: string;
  weekday: string;
  companies: CalendarCompany[];
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
