import type { Metadata } from "next";
import ScreenerPageClient from "./_client";

export const metadata: Metadata = {
  title: "UK Stock Screener — FTSE 100, 250, SmallCap & AIM",
  description:
    "Screen 500+ UK-listed shares across the FTSE 100, 250, SmallCap and AIM by " +
    "valuation, quality, growth, momentum and risk. Free fundamentals and composite scores.",
  alternates: { canonical: "/screener" },
};

export default function ScreenerPage() {
  return <ScreenerPageClient />;
}
