import type { Metadata } from "next";
import ReactDOM from "react-dom";
import ResearchListClient from "./_client";
import { getResearchPosts } from "@/lib/research";
import { HERO_COVER } from "@/lib/researchCovers";

export const metadata: Metadata = {
  title: "Research — Analysis & Market Notes",
  description:
    "Analysis, market notes and data-driven commentary on UK equities from Alpha Move AI.",
  alternates: {
    canonical: "/research",
    types: { "application/rss+xml": "/research/feed.xml" },
  },
  openGraph: {
    type: "website",
    title: "Research — Alpha Move AI",
    description:
      "Analysis, market notes and data-driven commentary on UK equities from Alpha Move AI.",
    url: "/research",
  },
};

export default async function ResearchPage() {
  // Server-rendered so crawlers see the article list, not "Loading…" — this
  // page is the blog's main SEO entry point. null (API unreachable) makes the
  // client fall back to fetching in the browser instead of failing the page.
  const posts = await getResearchPosts();
  // The hero art is a CSS background, which the browser can't discover until it
  // has parsed the page's CSS — preloading it protects LCP.
  ReactDOM.preload(HERO_COVER.src, { as: "image" });
  return <ResearchListClient initialPosts={posts} />;
}
