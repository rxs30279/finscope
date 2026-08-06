import type { Metadata } from "next";
import HighImpactRnsArchiveClient from "./_client";

// Admin-only — the stories the public page's display floor hides. Never index.
export const metadata: Metadata = {
  title: "High Impact RNS — Archive",
  robots: { index: false, follow: false },
};

export default function HighImpactRnsArchivePage() {
  return <HighImpactRnsArchiveClient />;
}
