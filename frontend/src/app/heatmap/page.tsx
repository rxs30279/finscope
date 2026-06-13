import type { Metadata } from "next";
import HeatmapPageClient from "./_client";

export const metadata: Metadata = {
  title: "UK Market Heatmap by Sector",
  description:
    "A visual heatmap of the UK market — see at a glance which sectors and shares are " +
    "up or down across the FTSE 100, 250, SmallCap and AIM.",
  alternates: { canonical: "/heatmap" },
};

export default function HeatmapPage() {
  return <HeatmapPageClient />;
}
