import type { Metadata } from "next";
import ResearchAdminClient from "./_client";

// Admin-only tooling — never index, never follow.
export const metadata: Metadata = {
  title: "Research Admin",
  robots: { index: false, follow: false },
};

export default function ResearchAdminPage() {
  return <ResearchAdminClient />;
}
