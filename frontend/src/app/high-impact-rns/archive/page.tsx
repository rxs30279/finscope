import type { Metadata } from "next";
import HighImpactRnsArchiveClient from "./_client";

// Admin-only — the full vet-withheld history, with no rolling-window cutoff
// (shadow rows also show on the public page within the window). Never index.
export const metadata: Metadata = {
  title: "High Impact RNS — Archive",
  robots: { index: false, follow: false },
};

export default function HighImpactRnsArchivePage() {
  return <HighImpactRnsArchiveClient />;
}
