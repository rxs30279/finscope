import type { Metadata } from "next";
import HighImpactRnsPageClient from "./_client";

export const metadata: Metadata = {
  title: "High Impact RNS",
  description: "A curated showcase of high-impact, positive RNS stories, tracked from the day they broke.",
  alternates: { canonical: "/high-impact-rns" },
};

export default function HighImpactRnsPage() {
  return <HighImpactRnsPageClient />;
}
