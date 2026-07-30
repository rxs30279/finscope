import type { Metadata } from "next";
import AudienceClient from "./_client";

// Admin-only subscriber list — never index, never follow, not in the public
// nav. See docs/email-monitor-page-plan.md step 5.
export const metadata: Metadata = {
  title: "Audience",
  robots: { index: false, follow: false },
};

export default function AudiencePage() {
  return <AudienceClient />;
}
