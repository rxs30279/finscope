"use client";

import type { ReactNode } from "react";
import { useIsMobile } from "@/hooks/useMediaQuery";

interface PageHeaderProps {
  /** Page title — rendered in the DM Serif Display (Mulish) display face. */
  title: ReactNode;
  /** Optional muted one-line description sitting under the title. */
  subtitle?: ReactNode;
  /** Render the subtitle on the same baseline as the title rather than below it. */
  inlineSubtitle?: boolean;
  /** Optional controls/stats shown on the right (counts, toggles, refresh…). */
  right?: ReactNode;
  /** Bottom spacing below the header. Set to 0 when the parent already spaces
   *  the header from the first section (e.g. a gap-based flex column). */
  marginBottom?: number;
}

/**
 * The single source of truth for a page's top header, so every route leads
 * with the same display title + muted subtitle (and an optional controls slot
 * on the right). Swap the styling here to restyle every page at once.
 */
export default function PageHeader({
  title,
  subtitle,
  inlineSubtitle = false,
  right,
  marginBottom = 16,
}: PageHeaderProps) {
  const isMobile = useIsMobile();
  return (
    <div
      style={{
        display: "flex",
        flexDirection: isMobile ? "column" : "row",
        alignItems: isMobile ? "stretch" : "baseline",
        justifyContent: "space-between",
        gap: isMobile ? 8 : 16,
        flexWrap: "wrap",
        marginBottom,
      }}
    >
      <div
        style={{
          minWidth: 0,
          display: inlineSubtitle ? "flex" : undefined,
          alignItems: inlineSubtitle ? "baseline" : undefined,
          flexWrap: inlineSubtitle ? "wrap" : undefined,
          gap: inlineSubtitle ? 12 : undefined,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontFamily: "DM Serif Display,serif",
            fontSize: isMobile ? 22 : 24,
            color: "#f1f5f9",
            letterSpacing: "-0.01em",
            lineHeight: 1.15,
          }}
        >
          {title}
        </h1>
        {subtitle != null && (
          <div
            style={{
              color: "#64748b",
              fontSize: inlineSubtitle ? 13 : 12,
              marginTop: inlineSubtitle ? 0 : 4,
              lineHeight: 1.5,
            }}
          >
            {subtitle}
          </div>
        )}
      </div>
      {right != null && (
        <div
          style={{
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          {right}
        </div>
      )}
    </div>
  );
}
