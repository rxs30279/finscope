import type { Metadata } from "next";
import GatesClient from "./_client";

// Admin-only calibration page for the RNS gate registry — never index, never
// follow, not in the public nav. See docs/rns-gate-block-plan.md.
export const metadata: Metadata = {
  title: "Gate Calibration",
  robots: { index: false, follow: false },
};

export default function GatesPage() {
  return <GatesClient />;
}
