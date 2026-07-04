import type { Metadata } from "next";
import ScreenerColumnSettings from "@/components/settings/ScreenerColumnSettings";

export const metadata: Metadata = {
  title: "Screener Settings — Alpha Move AI",
  description: "Choose which fundamental columns appear in the UK stock screener's table.",
  alternates: { canonical: "/settings/screener" },
};

export default function ScreenerSettingsPage() {
  return <ScreenerColumnSettings />;
}
