import type { MetadataRoute } from "next";
import { SITE_URL, apiUrl } from "@/lib/seo";

// Regenerate daily so newly added / dropped index constituents flow into the sitemap.
export const revalidate = 86400;

const STATIC_ROUTES: { path: string; priority: number; freq: MetadataRoute.Sitemap[number]["changeFrequency"] }[] = [
  { path: "/", priority: 1, freq: "daily" },
  { path: "/screener", priority: 0.9, freq: "daily" },
  { path: "/markets", priority: 0.8, freq: "daily" },
  { path: "/trending", priority: 0.8, freq: "daily" },
  { path: "/analysts", priority: 0.7, freq: "daily" },
  { path: "/rns", priority: 0.7, freq: "daily" },
  { path: "/heatmap", priority: 0.6, freq: "daily" },
  { path: "/benchmarks", priority: 0.5, freq: "weekly" },
  { path: "/subscribe", priority: 0.5, freq: "monthly" },
  { path: "/donate", priority: 0.3, freq: "yearly" },
  { path: "/feedback", priority: 0.3, freq: "yearly" },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const staticEntries: MetadataRoute.Sitemap = STATIC_ROUTES.map((r) => ({
    url: `${SITE_URL}${r.path}`,
    lastModified: now,
    changeFrequency: r.freq,
    priority: r.priority,
  }));

  // One entry per active company. The screener endpoint returns the full universe;
  // if it's unreachable at build/revalidate, fall back to the static routes only so
  // the build never breaks on a transient API failure.
  let companyEntries: MetadataRoute.Sitemap = [];
  try {
    const rows = await fetch(apiUrl("/api/screener?limit=2000"), {
      next: { revalidate: 86400 },
    }).then((r) => (r.ok ? r.json() : []));
    if (Array.isArray(rows)) {
      const seen = new Set<string>();
      companyEntries = rows
        .map((r: { symbol?: string }) => r?.symbol)
        .filter((s): s is string => Boolean(s) && !seen.has(s) && (seen.add(s), true))
        .map((s) => ({
          url: `${SITE_URL}/company?symbol=${encodeURIComponent(s)}`,
          lastModified: now,
          changeFrequency: "daily" as const,
          priority: 0.6,
        }));
    }
  } catch {
    // API unreachable — ship the static routes only.
  }

  return [...staticEntries, ...companyEntries];
}
