import { ImageResponse } from "next/og";
import { getResearchPost } from "@/lib/research";
import { fmtPostDate } from "@/lib/research";

// Per-article social-share card. Only used as a fallback when the post has no
// custom `image` set — generateMetadata's explicit openGraph.images (when
// present) takes priority over this file convention.
export const alt = "Alpha Move AI — Research";
export const size = { width: 1200, height: 630 };
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
            color: "#f1f5f9",
            fontSize: 60,
            fontWeight: 700,
            lineHeight: 1.15,
            marginTop: 28,
            maxWidth: 1020,
          }}
        >
          {title}
        </div>
        {dateLabel && (
          <div style={{ color: "#94a3b8", fontSize: 28, marginTop: 32 }}>
            {dateLabel}
          </div>
        )}
      </div>
    ),
    { ...size },
  );
}
