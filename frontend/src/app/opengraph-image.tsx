import { ImageResponse } from "next/og";
import {
  OG_SIZE,
  BG,
  ACCENT,
  INK,
  MUTED,
  loadAlphaMark,
  CandleBackdrop,
  AlphaMarkBadge,
} from "@/lib/og-card";

// Default social-share card for every route that doesn't supply its own.
// Same treatment as the research-post cards: landing-page ground, rising
// candle trace, green-α mark. The seed is a fixed string so the site-wide
// card is one stable composition.
export const alt = "Alpha Move AI — UK Stock Screener";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function OgImage() {
  const alphaMark = await loadAlphaMark();

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-start",
          padding: "110px 90px 0",
          background: BG,
          fontFamily: "sans-serif",
        }}
      >
        <CandleBackdrop seed="alpha-move-ai" />
        <AlphaMarkBadge src={alphaMark} />

        <div
          style={{
            color: ACCENT,
            fontSize: 26,
            fontWeight: 600,
            letterSpacing: 4,
            textTransform: "uppercase",
          }}
        >
          Alpha Move AI
        </div>

        <div
          style={{
            color: INK,
            fontSize: 76,
            fontWeight: 700,
            lineHeight: 1.1,
            marginTop: 30,
          }}
        >
          UK Stock Screener
        </div>

        <div
          style={{
            color: MUTED,
            fontSize: 32,
            lineHeight: 1.4,
            marginTop: 26,
            maxWidth: 900,
          }}
        >
          FTSE 100 · 250 · SmallCap · AIM — fundamentals, scores, analyst
          consensus, RNS news &amp; market signals.
        </div>
      </div>
    ),
    { ...size },
  );
}
