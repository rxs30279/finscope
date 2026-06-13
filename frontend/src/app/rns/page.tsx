import type { Metadata } from "next";
import RnsPageClient from "./_client";

export const metadata: Metadata = {
  title: "UK RNS Regulatory News — AI-Scored",
  description:
    "The latest London Stock Exchange RNS regulatory announcements, filtered and " +
    "scored by significance so you see the news that actually moves UK shares.",
  alternates: { canonical: "/rns" },
};

export default function RnsPage() {
  return <RnsPageClient />;
}
