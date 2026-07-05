import type { Metadata } from "next";
import HighImpactRnsPageClient from "./_client";

// Preproduction: launched hidden while we monitor a month of showcase picks
// before public release. Kept out of the nav and out of search indexes.
export const metadata: Metadata = {
  title: "High Impact RNS",
  description: "A curated showcase of high-impact, positive RNS stories, tracked for a month.",
  robots: { index: false, follow: false },
  alternates: { canonical: "/high-impact-rns" },
};

export default function HighImpactRnsPage() {
  return <HighImpactRnsPageClient />;
}
