import { backendUrl } from "./seo";
import { fetchRetry } from "./fetchRetry";

// Shapes mirror backend/research.py serialisers.
export interface ResearchPostSummary {
  id: number;
  slug: string;
  title: string;
  summary: string | null;
  image: string | null;
  tags: string[];
  status: "draft" | "published";
  published_at: string | null;
  updated_at: string | null;
  comment_count: number;
}

export interface ResearchPost extends ResearchPostSummary {
  body: string;
  created_at: string | null;
}

export interface ResearchComment {
  id: number;
  author: string;
  body: string;
  created_at: string | null;
}

// 60s max-staleness on the server-side fetches below: served
// stale-while-revalidate, so readers always get a cached render; this only
// bounds how long a fresh edit takes to appear.
const REVALIDATE = 60;

// Server-side fetch of a single published post — used by the [slug] route's
// generateMetadata and its server component (Next dedupes the two identical
// fetches within one request).
//
// Returns null ONLY on a genuine 404 (the page should notFound() and stay out
// of the index). Any other failure — backend down, 5xx, timeout — THROWS so the
// route 500s instead: serving a 404 for a live article during an API blip would
// invite search engines to de-index it.
export async function getResearchPost(slug: string): Promise<ResearchPost | null> {
  if (!slug) return null;
  const res = await fetchRetry(backendUrl(`/api/research/posts/${encodeURIComponent(slug)}`), {
    next: { revalidate: REVALIDATE },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Research API ${res.status} for ${slug}`);
  return (await res.json()) as ResearchPost;
}

// Server-side fetch of the published-post list — the /research index and the
// RSS feed. Returns null on any failure so callers can degrade (the list page
// falls back to a client-side fetch) rather than 500 the whole page.
export async function getResearchPosts(): Promise<ResearchPostSummary[] | null> {
  try {
    const res = await fetchRetry(backendUrl("/api/research/posts"), {
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { posts?: ResearchPostSummary[] };
    return data.posts || [];
  } catch {
    return null;
  }
}

// British long-form date for post bylines.
export function fmtPostDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

// Date + time for comments — several comments can land the same day, and the
// time is what shows their order.
export function fmtCommentDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return (
    d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) +
    ", " +
    d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
  );
}
