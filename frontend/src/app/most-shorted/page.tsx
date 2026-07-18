import type { Metadata } from "next";
import MostShortedPageClient from "./_client";
import { getMostShorted } from "@/lib/shorts";

export const metadata: Metadata = {
  title: "Most Shorted UK Stocks — Live FCA Short Interest",
  description:
    "The most shorted stocks on the London Stock Exchange, ranked by FCA-disclosed " +
    "aggregate net short positions. Updated daily with short-interest trend charts.",
  alternates: { canonical: "/most-shorted" },
};

export default async function MostShortedPage() {
  // Server-rendered so the full leaderboard is in the initial HTML (SEO — this
  // page targets "most shorted UK stocks" searches) — null (API unreachable)
  // makes the client fall back to fetching in the browser.
  const initialData = await getMostShorted();
  return <MostShortedPageClient initialData={initialData} />;
}
