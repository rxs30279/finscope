import { apiUrl } from "./seo";

// Shapes mirror backend/research.py serialisers.
export interface ResearchPostSummary {
  id: number;
  slug: string;
  title: string;
  summary: string | null;
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

// Server-side fetch of a single published post — used by the [slug] route's
// generateMetadata and its server component. Returns null on 404/failure so the
// page can render a graceful not-found and stay out of the index. Next dedupes
// the two identical fetches within one request.
export async function getResearchPost(slug: string): Promise<ResearchPost | null> {
  if (!slug) return null;
  try {
    // 60s max-staleness: served stale-while-revalidate, so readers always get a
    // cached render; this only bounds how long a fresh edit takes to appear.
    const res = await fetch(apiUrl(`/api/research/posts/${encodeURIComponent(slug)}`), {
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return (await res.json()) as ResearchPost;
  } catch {
    return null;
  }
}

// British long-form date for post bylines / comment timestamps.
export function fmtPostDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}
