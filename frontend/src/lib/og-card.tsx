import { readFile } from "node:fs/promises";
import { join } from "node:path";

// Shared pieces for the social-share cards (root + research posts) so both
// carry the same landing-page look: dark ground, rising candle trace, green-α
// brand mark. Rendered through next/og's satori, which supports only a subset
// of CSS — keep styles simple (flex, absolute positioning, gradients).

export const OG_SIZE = { width: 1200, height: 630 };

// Landing-page brand tokens (landing.css) so the cards match the front page.
export const BG = "#0d1117";
export const ACCENT = "#f97316";
export const GREEN = "#42e58a";
export const RED = "#e5524b";
export const INK = "#e8edf2";
export const MUTED = "#9aa6b5";

// Deterministic PRNG so a card's trace is unique to its seed but stable
// across regenerations (crawlers re-fetch; the card must not change under
// them).
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
  // Wick split into the segments above and below the body — drawing one
  // full-height line behind a translucent body leaves the line visible
  // through the block, so nothing may overlap the body.
  wickTopY: number;
  wickTopH: number;
  wickBotY: number;
  wickBotH: number;
  up: boolean;
}

// Static rendition of the landing page's animated candle walk
// (LandingEffects.tsx), but mean-reverting toward a rising trendline instead
// of flat 100 so every card's trace climbs left-to-right. The trace
// accelerates in its final third — steeper climb, bigger bodies, longer
// wicks — which reads more like a real breakout than a uniform drift and
// fills the text-free space on the right of the card.
function buildCandles(seed: string): Candle[] {
  const rng = mulberry32(hashSeed(seed));
  const rand = (a: number, b: number) => a + rng() * (b - a);

  const cw = 16;
  const gap = 12;
  const total = cw + gap;
  const count = Math.ceil(OG_SIZE.width / total) + 1;
  const baseY = 540;
  const scaleY = 9;
  const y = (v: number) => baseY - (v - 100) * scaleY;

  const lateStart = Math.floor(count * 0.66);

  const out: Candle[] = [];
  let price = 100;
  let trend = 100;
  for (let i = 0; i < count; i++) {
    const late = i >= lateStart;
    trend += late ? 1.1 : 0.22;
    const vol = late ? 4.2 : 2.6;
    const wickMax = late ? 4.6 : 2.6;
    const o = price;
    const c = o + rand(-vol, vol) + (trend - o) * 0.12;
    price = c;
    const h = Math.max(o, c) + rand(0.4, wickMax);
    const l = Math.min(o, c) - rand(0.4, wickMax);
    const yO = y(o);
    const yC = y(c);
    const bodyTop = Math.min(yO, yC);
    const bodyH = Math.max(2, Math.abs(yC - yO));
    out.push({
      x: i * total,
      bodyTop,
      bodyH,
      wickTopY: y(h),
      wickTopH: Math.max(0, bodyTop - y(h)),
      wickBotY: bodyTop + bodyH,
      wickBotH: Math.max(0, y(l) - (bodyTop + bodyH)),
      up: c >= o,
    });
  }
  return out;
}

// The official green-α mark, inlined as a data URI. Satori's bundled font is
// Latin-only so it can't typeset the Greek glyph itself — the raster keeps
// the official serif form exactly. alpha-mark-54.png is pre-sized to exactly
// how it's displayed because satori's own downscaling is visibly pixelated.
// Returns null (card renders without the mark) rather than 500ing the whole
// image if the asset ever goes missing.
export async function loadAlphaMark(): Promise<string | null> {
  try {
    const buf = await readFile(join(process.cwd(), "public", "alpha-mark-54.png"));
    return `data:image/png;base64,${buf.toString("base64")}`;
  } catch {
    return null;
  }
}

// Candle trace pinned behind the card content, faded into the ground toward
// the top so the headline stays legible (same idea as .am-bg-fade on the
// landing page).
export function CandleBackdrop({ seed }: { seed: string }) {
  const candles = buildCandles(seed);
  return (
    // Single absolutely-positioned wrapper, not a fragment: satori re-parents
    // fragment children into an anonymous box placed after the root's
    // padding, which shifts the whole trace down by the padding offset.
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: OG_SIZE.width,
        height: OG_SIZE.height,
        display: "flex",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: OG_SIZE.width,
          height: OG_SIZE.height,
          display: "flex",
          opacity: 0.6,
        }}
      >
        {candles.map((k) => {
          const col = k.up ? GREEN : RED;
          return [
            k.wickTopH > 0 && (
              <div
                key={`wt${k.x}`}
                style={{
                  position: "absolute",
                  left: k.x + 7,
                  top: k.wickTopY,
                  width: 2,
                  height: k.wickTopH,
                  background: col,
                }}
              />
            ),
            k.wickBotH > 0 && (
              <div
                key={`wb${k.x}`}
                style={{
                  position: "absolute",
                  left: k.x + 7,
                  top: k.wickBotY,
                  width: 2,
                  height: k.wickBotH,
                  background: col,
                }}
              />
            ),
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
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: OG_SIZE.width,
          height: OG_SIZE.height,
          display: "flex",
          background:
            "linear-gradient(180deg, rgba(13,17,23,0.97) 0%, rgba(13,17,23,0.9) 40%, rgba(13,17,23,0.4) 72%, rgba(13,17,23,0.05) 100%)",
        }}
      />
    </div>
  );
}

// Official green-α brand mark (favicon artwork) in a thin green box, kept
// top-right away from the orange eyebrow so the two accent colours don't sit
// side by side.
export function AlphaMarkBadge({ src }: { src: string | null }) {
  if (!src) return null;
  return (
    <div
      style={{
        position: "absolute",
        top: 48,
        right: 90,
        display: "flex",
        padding: 4,
        border: `2px solid rgba(66,229,138,0.6)`,
        borderRadius: 16,
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="" width={54} height={54} style={{ borderRadius: 12 }} />
    </div>
  );
}
