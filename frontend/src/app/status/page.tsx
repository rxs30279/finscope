import type { Metadata } from "next";
import StatusClient from "./_client";

// Admin-only operations page — never index, never follow, not in the public nav.
export const metadata: Metadata = {
  title: "System Status",
  robots: { index: false, follow: false },
};

export default function StatusPage() {
  return <StatusClient />;
}
