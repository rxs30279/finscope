import type { Metadata } from "next";
import DonateTab from "@/components/DonateTab";

export const metadata: Metadata = {
  title: "Support Alpha Move AI",
  description:
    "Alpha Move AI is a free UK stock screener. If it helps your research, you can " +
    "support its hosting and data costs here.",
  alternates: { canonical: "/donate" },
};

export default function DonatePage() {
  return <DonateTab />;
}
