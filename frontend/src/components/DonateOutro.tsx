"use client";

import Link from "next/link";
import { usePostHog } from "posthog-js/react";
import { colors } from "@/lib/theme";

/**
 * Quiet end-of-content donations ask — sits at the foot of long-form pages
 * (research posts) where a reader has just extracted value. Deliberately
 * calmer than the rotating EmailDigestCTA banner: a card, two lines and an
 * outlined button routing to /donate, where the full Ko-fi pitch lives.
 * Clicks share the `donate_cta_clicked` event, tagged with `source`.
 */
export default function DonateOutro({ source }: { source: string }) {
  const ph = usePostHog();

  return (
    <div
      style={{
        background: colors.bgCard,
        border: `1px solid ${colors.border}`,
        borderLeft: `3px solid ${colors.accent}`,
        borderRadius: 4,
        padding: "20px 24px",
        margin: "36px 0 0",
      }}
    >
      <div
        style={{
          color: colors.accent,
          fontSize: 10,
          fontFamily: "monospace",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: 2,
          marginBottom: 8,
        }}
      >
        Reader-supported · No ads · No paywall
      </div>
      <div style={{ color: colors.textMuted, fontSize: 13.5, lineHeight: 1.7, marginBottom: 16 }}>
        Alpha Move AI — the screener, the AI-ranked RNS digest and research like this — is a free,
        one-person project. If it has saved you time or sharpened a decision, chipping in the price
        of a coffee keeps it running and independent. Entirely optional.
      </div>
      <Link
        href="/donate"
        onClick={() => ph?.capture("donate_cta_clicked", { source })}
        style={{
          display: "inline-block",
          background: "linear-gradient(135deg, #2a1a00 0%, #1a1200 100%)",
          border: `1px solid ${colors.accent}`,
          color: colors.accent,
          padding: "10px 22px",
          fontSize: 12,
          fontFamily: "monospace",
          fontWeight: 700,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          borderRadius: 3,
          textDecoration: "none",
          boxShadow: "0 0 12px rgba(249, 115, 22, 0.15)",
        }}
      >
        ♥ Support the site
      </Link>
    </div>
  );
}
