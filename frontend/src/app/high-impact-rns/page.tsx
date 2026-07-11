import type { Metadata } from "next";
import HighImpactRnsPageClient from "./_client";
import { getShowcase } from "@/lib/showcase";

export const metadata: Metadata = {
  title: "High Impact RNS",
  description: "A curated showcase of high-impact, positive RNS stories, tracked from the day they broke.",
  alternates: { canonical: "/high-impact-rns" },
};

export default async function HighImpactRnsPage() {
  // Server-rendered so the list (and its LCP row) is in the initial HTML
  // instead of appearing after a client-side fetch — null (API unreachable)
  // makes the client fall back to fetching in the browser.
  const initialRows = await getShowcase();
  return <HighImpactRnsPageClient initialRows={initialRows} />;
}
