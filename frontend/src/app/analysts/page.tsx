import type { Metadata } from "next";
import AnalystsPageClient from "./_client";
import { getAnalystsData } from "@/lib/analysts";

export const metadata: Metadata = {
  title: "UK Analyst Ratings & Consensus Changes",
  description:
    "Track broker analyst ratings for UK shares — consensus, buy/hold/sell breakdowns, " +
    "price-target upside and the latest upgrades and downgrades.",
  alternates: { canonical: "/analysts" },
};

export default async function AnalystsPage() {
  // Server-fetched (ISR) so the cards + table are in the initial HTML — the
  // client component only refetches on manual refresh or if this returned null.
  const { latest, movers } = await getAnalystsData();
  return <AnalystsPageClient initialLatest={latest} initialMovers={movers} />;
}
