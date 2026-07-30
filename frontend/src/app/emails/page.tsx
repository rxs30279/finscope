import type { Metadata } from "next";
import EmailsClient from "./_client";

// Admin-only email delivery monitor — never index, never follow, not in the
// public nav. See docs/email-monitor-page-plan.md.
export const metadata: Metadata = {
  title: "Emails",
  robots: { index: false, follow: false },
};

export default function EmailsPage() {
  return <EmailsClient />;
}
