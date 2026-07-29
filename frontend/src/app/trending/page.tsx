import type { Metadata } from "next";
import TrendingPageClient from "./_client";
import { getTrending } from "@/lib/trending";

export const metadata: Metadata = {
  title: "Trending UK Stocks — Today's Risers & Fallers",
  description:
    "Today's biggest movers on the London market — top-rising and top-falling UK shares " +
    "plus momentum streaks across the FTSE 100, 250, SmallCap and AIM.",
  alternates: { canonical: "/trending" },
};

export default async function TrendingPage() {
  // Server-rendered so both lists are in the initial HTML — otherwise the
  // visitor waits for hydration before the fetch even starts. null (API
  // unreachable) makes the client fall back to fetching in the browser.
  const initialData = await getTrending();
  return <TrendingPageClient initialData={initialData} />;
}
