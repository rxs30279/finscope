import { ImageResponse } from "next/og";

// Default social-share card for every route that doesn't supply its own.
// Rendered to a static 1200x630 PNG at build time (fixed path, so it serves
// fine under the legacy vercel.json catch-all routing).
export const alt = "Alpha Move AI — UK Stock Screener";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 90px",
          background: "linear-gradient(135deg, #0a0a0a 0%, #1a1200 100%)",
          fontFamily: "sans-serif",
        }}
      >
        <div
          style={{
            color: "#f97316",
            fontSize: 30,
            fontWeight: 600,
            letterSpacing: 4,
            textTransform: "uppercase",
          }}
        >
          Alpha Move AI
        </div>
        <div
          style={{
            color: "#f1f5f9",
            fontSize: 76,
            fontWeight: 700,
            lineHeight: 1.1,
            marginTop: 28,
          }}
        >
          UK Stock Screener
        </div>
        <div style={{ color: "#94a3b8", fontSize: 34, marginTop: 28, maxWidth: 920 }}>
          FTSE 100 · 250 · SmallCap · AIM — fundamentals, scores, analyst
          consensus, RNS news &amp; market signals.
        </div>
      </div>
    ),
    { ...size },
  );
}
