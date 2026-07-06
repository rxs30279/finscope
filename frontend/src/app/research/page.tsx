import type { Metadata } from "next";
import ResearchListClient from "./_client";

export const metadata: Metadata = {
  title: "Research — Analysis & Market Notes",
  description:
    "Analysis, market notes and data-driven commentary on UK equities from Alpha Move AI.",
  alternates: { canonical: "/research" },
  openGraph: {
    type: "website",
    title: "Research — Alpha Move AI",
    description:
      "Analysis, market notes and data-driven commentary on UK equities from Alpha Move AI.",
    url: "/research",
  },
};

export default function ResearchPage() {
  return <ResearchListClient />;
}
