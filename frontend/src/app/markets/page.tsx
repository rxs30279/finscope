import type { Metadata } from "next";
import MarketsPageClient from "./_client";

export const metadata: Metadata = {
  title: "UK Market Signals — Fear & Greed, Breadth & Sector Rotation",
  description:
    "Gauge the UK market mood: the Alpha Move Fear & Greed index, market breadth, " +
    "sector rotation and cross-asset signals for the London Stock Exchange.",
  alternates: { canonical: "/markets" },
};

export default function MarketsPage() {
  return <MarketsPageClient />;
}
