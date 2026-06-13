import type { Metadata } from "next";
import TrendingPageClient from "./_client";

export const metadata: Metadata = {
  title: "Trending UK Stocks — Today's Risers & Fallers",
  description:
    "Today's biggest movers on the London market — top-rising and top-falling UK shares " +
    "plus momentum streaks across the FTSE 100, 250, SmallCap and AIM.",
  alternates: { canonical: "/trending" },
};

export default function TrendingPage() {
  return <TrendingPageClient />;
}
