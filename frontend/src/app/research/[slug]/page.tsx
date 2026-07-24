import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ReactDOM from "react-dom";
import ResearchPostClient from "./_client";
import { getResearchPost, getResearchPosts } from "@/lib/research";
import { coverFor } from "@/lib/researchCovers";
import { SITE_URL } from "@/lib/seo";

interface PageProps {
  params: Promise<{ slug: string }>;
}

// getResearchPost returns null only on a real 404 and THROWS on any other
// failure — so a backend blip 500s this route (crawlers retry) instead of
// serving a 404 that could get a live article de-indexed.
export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const post = await getResearchPost(slug);
  if (!post) {
    return { title: "Research", robots: { index: false, follow: true } };
  }
  const canonical = `/research/${post.slug}`;
  const description =
    post.summary ||
    post.body.replace(/[#*_`>\-\[\]()!]/g, "").replace(/\s+/g, " ").trim().slice(0, 160);
  return {
    title: `${post.title} — Research`,
    description,
    alternates: { canonical },
    openGraph: {
      type: "article",
      title: post.title,
      description,
      url: canonical,
      publishedTime: post.published_at || undefined,
      modifiedTime: post.updated_at || undefined,
      tags: post.tags,
      // Relative paths resolve against metadataBase (layout.tsx).
      images: post.image ? [post.image] : undefined,
    },
    twitter: {
      // Only claim the big-image card when there is an image to fill it.
      card: post.image ? "summary_large_image" : "summary",
      title: post.title,
      description,
      images: post.image ? [post.image] : undefined,
    },
  };
}

export default async function ResearchPostPage({ params }: PageProps) {
  const { slug } = await params;
  const post = await getResearchPost(slug);
  if (!post) notFound();

  // Post list drives the "Related notes" strip and the cover assignment. null
  // (API blip) degrades to no related section rather than failing the article.
  const allPosts = (await getResearchPosts()) ?? [];

  // The hero cover is a CSS background — preload it so it doesn't wait on CSS
  // parse, protecting LCP. Use the same list position the client renders from.
  ReactDOM.preload(coverFor(post, allPosts.findIndex((p) => p.slug === post.slug)).src, {
    as: "image",
  });

  const url = `${SITE_URL}/research/${post.slug}`;
  // JSON-LD so the article is eligible for rich results.
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: post.title,
    description: post.summary || undefined,
    url,
    mainEntityOfPage: { "@type": "WebPage", "@id": url },
    // Posts without a custom image fall back to the generated share card
    // (opengraph-image.tsx) so `image` is always present for rich results.
    image: [
      post.image
        ? post.image.startsWith("http")
          ? post.image
          : `${SITE_URL}${post.image}`
        : `${url}/opengraph-image`,
    ],
    datePublished: post.published_at || undefined,
    dateModified: post.updated_at || undefined,
    author: { "@type": "Organization", name: "Alpha Move AI", url: SITE_URL },
    publisher: {
      "@type": "Organization",
      name: "Alpha Move AI",
      logo: { "@type": "ImageObject", url: `${SITE_URL}/android-chrome-512.png` },
    },
    keywords: post.tags?.join(", ") || undefined,
  };

  return (
    <>
      <script
        type="application/ld+json"
        // JSON.stringify doesn't escape '<', so a title containing "</script>"
        // could close the tag early — escape it into the JS string form.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, "\\u003c") }}
      />
      <ResearchPostClient initialPost={post} allPosts={allPosts} />
    </>
  );
}
