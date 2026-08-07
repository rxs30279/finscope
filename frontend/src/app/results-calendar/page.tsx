import type { Metadata } from "next";
import ResultsCalendarClient from "./_client";
import { getResultsCalendar } from "@/lib/resultsCalendar";

export const metadata: Metadata = {
  title: "UK Results Calendar — Who Reports This Week",
  description:
    "Which London-listed companies report results this week. Full-year and interim " +
    "results, quarterlies and trading updates for FTSE 100, FTSE 250, SmallCap and " +
    "AIM companies, laid out day by day.",
  alternates: { canonical: "/results-calendar" },
};

// The grid is the whole point of the page, so it is server-rendered into the
// initial HTML rather than fetched in the browser — same reasoning as
// /most-shorted. A null (API unreachable) makes the client fetch instead.
export default async function ResultsCalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ week?: string }>;
}) {
  const { week } = await searchParams;
  const initialData = await getResultsCalendar(week);
  return <ResultsCalendarClient initialData={initialData} initialWeek={week} />;
}
