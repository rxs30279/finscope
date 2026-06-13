import type { Metadata } from "next";
import AnalystsPageClient from "./_client";

export const metadata: Metadata = {
  title: "UK Analyst Ratings & Consensus Changes",
  description:
    "Track broker analyst ratings for UK shares — consensus, buy/hold/sell breakdowns, " +
    "price-target upside and the latest upgrades and downgrades.",
  alternates: { canonical: "/analysts" },
};

export default function AnalystsPage() {
  return <AnalystsPageClient />;
}
