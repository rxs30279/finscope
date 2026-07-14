import { ImageResponse } from "next/og";
import { getResearchPost } from "@/lib/research";
import { fmtPostDate } from "@/lib/research";

// Per-article social-share card. Only used as a fallback when the post has no
// custom `image` set — generateMetadata's explicit openGraph.images (when
// present) takes priority over this file convention.
export const alt = "Alpha Move AI — Research";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Landing-page brand tokens (landing.css) so the card matches the front page.
const BG = "#0d1117";
const ACCENT = "#f97316";
const GREEN = "#42e58a";
const RED = "#e5524b";
const INK = "#e8edf2";
const MUTED = "#9aa6b5";

// Deterministic PRNG so a post's trace is unique to it but stable across
// regenerations (crawlers re-fetch; the card must not change under them).
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashSeed(s: string): number {
  let h = 0x811c9dc5; // FNV-1a
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

interface Candle {
  x: number;
  bodyTop: number;
  bodyH: number;
  wickTop: number;
  wickH: number;
  up: boolean;
}

// Static rendition of the landing page's animated candle walk
// (LandingEffects.tsx): mean-reverting drift around 100 with random wicks.
function buildCandles(seed: string): Candle[] {
  const rng = mulberry32(hashSeed(seed));
  const rand = (a: number, b: number) => a + rng() * (b - a);

  const cw = 16;
  const gap = 12;
  const total = cw + gap;
  const count = Math.ceil(size.width / total) + 1;
  const baseY = 500;
  const scaleY = 10;
  const y = (v: number) => baseY - (v - 100) * scaleY;

  const out: Candle[] = [];
  let price = 100;
  for (let i = 0; i < count; i++) {
    const o = price;
    const c = o + rand(-3, 3) + (100 - o) * 0.04;
    price = c;
    const h = Math.max(o, c) + rand(0.4, 2.6);
    const l = Math.min(o, c) - rand(0.4, 2.6);
    const yO = y(o);
    const yC = y(c);
    out.push({
      x: i * total,
      bodyTop: Math.min(yO, yC),
      bodyH: Math.max(2, Math.abs(yC - yO)),
      wickTop: y(h),
      wickH: Math.max(2, y(l) - y(h)),
      up: c >= o,
    });
  }
  return out;
}

export default async function OgImage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = await getResearchPost(slug).catch(() => null);
  const title = post?.title || "Research";
  const dateLabel = post ? fmtPostDate(post.published_at) : "";
  const candles = buildCandles(slug);

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
          background: BG,
          fontFamily: "sans-serif",
        }}
      >
        {/* Candle trace behind everything, strongest at the bottom */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: size.width,
            height: size.height,
            display: "flex",
            opacity: 0.6,
          }}
        >
          {candles.map((k) => {
            const col = k.up ? GREEN : RED;
            return [
              <div
                key={`w${k.x}`}
                style={{
                  position: "absolute",
                  left: k.x + 7,
                  top: k.wickTop,
                  width: 2,
                  height: k.wickH,
                  background: col,
                }}
              />,
              <div
                key={`b${k.x}`}
                style={{
                  position: "absolute",
                  left: k.x,
                  top: k.bodyTop,
                  width: 16,
                  height: k.bodyH,
                  background: col,
                }}
              />,
            ];
          })}
        </div>
        {/* Fade the trace into the background so the headline stays legible
            (same idea as .am-bg-fade on the landing page). */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: size.width,
            height: size.height,
            display: "flex",
            background:
              "linear-gradient(180deg, rgba(13,17,23,0.97) 0%, rgba(13,17,23,0.9) 40%, rgba(13,17,23,0.4) 72%, rgba(13,17,23,0.05) 100%)",
          }}
        />

        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          {/* Brand mark (nav arrow logo) */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 52,
              height: 52,
              borderRadius: 12,
              border: `2px solid ${ACCENT}`,
              background: "rgba(249,115,22,0.12)",
            }}
          >
            <svg
              width="30"
              height="30"
              viewBox="0 0 24 24"
              fill="none"
              stroke={ACCENT}
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 17 L9 9 L13 13 L20 5" />
              <path d="M20 5 L20 10 M20 5 L15 5" />
            </svg>
          </div>
          <div
            style={{
              color: ACCENT,
              fontSize: 26,
              fontWeight: 600,
              letterSpacing: 4,
              textTransform: "uppercase",
            }}
          >
            Alpha Move AI · Research
          </div>
        </div>

        <div
          style={{
            color: INK,
            fontSize: title.length > 70 ? 52 : 60,
            fontWeight: 700,
            lineHeight: 1.15,
            marginTop: 30,
            maxWidth: 1020,
          }}
        >
          {title}
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            marginTop: 34,
            color: MUTED,
            fontSize: 26,
          }}
        >
          {dateLabel && <div style={{ display: "flex" }}>{dateLabel}</div>}
          {dateLabel && (
            <div
              style={{
                display: "flex",
                width: 6,
                height: 6,
                borderRadius: 3,
                background: MUTED,
              }}
            />
          )}
          <div style={{ display: "flex" }}>app.alphamoveai.co.uk</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
