import { getResearchPosts } from "@/lib/research";
import { SITE_URL, SITE_NAME } from "@/lib/seo";

// RSS 2.0 feed of published Research posts — a decent slice of the investing
// audience still subscribes by feed reader. Linked from the /research page via
// its metadata alternates. Re-generated at most every 5 minutes.
export const revalidate = 300;

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function GET() {
  const posts = (await getResearchPosts()) || [];

  const items = posts
    .map((p) => {
      const url = `${SITE_URL}/research/${p.slug}`;
      const pubDate = p.published_at ? new Date(p.published_at).toUTCString() : "";
      return [
        "    <item>",
        `      <title>${esc(p.title)}</title>`,
        `      <link>${esc(url)}</link>`,
        `      <guid isPermaLink="true">${esc(url)}</guid>`,
        p.summary ? `      <description>${esc(p.summary)}</description>` : "",
        pubDate ? `      <pubDate>${pubDate}</pubDate>` : "",
        ...(p.tags || []).map((t) => `      <category>${esc(t)}</category>`),
        "    </item>",
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${esc(`${SITE_NAME} — Research`)}</title>
    <link>${esc(`${SITE_URL}/research`)}</link>
    <description>Analysis, market notes and data-driven commentary on UK equities.</description>
    <language>en-gb</language>
    <atom:link href="${esc(`${SITE_URL}/research/feed.xml`)}" rel="self" type="application/rss+xml"/>
${items}
  </channel>
</rss>
`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
    },
  });
}
