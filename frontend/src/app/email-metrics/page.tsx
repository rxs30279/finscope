import type { Metadata } from "next";
import EmailMetricsClient from "./_client";

// Admin-only daily email chart — never index, never follow, not in the public
// nav. Sibling of /emails (per-message) and /audience (subscriber list).
export const metadata: Metadata = {
  title: "Email metrics",
  robots: { index: false, follow: false },
};

export default function EmailMetricsPage() {
  return <EmailMetricsClient />;
}
