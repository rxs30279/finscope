import { ImageResponse } from "next/og";
import { getResearchPost } from "@/lib/research";
import { fmtPostDate } from "@/lib/research";
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

// Per-article social-share card. Only used as a fallback when the post has no
// custom `image` set — generateMetadata's explicit openGraph.images (when
// present) takes priority over this file convention.
export const alt = "Alpha Move AI — Research";
export const size = OG_SIZE;
export const contentType = "image/png";

export default async function OgImage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = await getResearchPost(slug).catch(() => null);
  const title = post?.title || "Research";
  const dateLabel = post ? fmtPostDate(post.published_at) : "";
  const alphaMark = await loadAlphaMark();

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          // Anchor the text to the top so it clears the candle trace along
          // the bottom of the card.
          justifyContent: "flex-start",
          padding: "110px 90px 0",
          background: BG,
          fontFamily: "sans-serif",
        }}
      >
        <CandleBackdrop seed={slug} />
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
          Alpha Move AI · Research
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
