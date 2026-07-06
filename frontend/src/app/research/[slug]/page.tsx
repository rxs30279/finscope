import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ResearchPostClient from "./_client";
import { getResearchPost } from "@/lib/research";

interface PageProps {
  params: Promise<{ slug: string }>;
}

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
    },
    twitter: { card: "summary_large_image", title: post.title, description },
  };
}

export default async function ResearchPostPage({ params }: PageProps) {
  const { slug } = await params;
  const post = await getResearchPost(slug);
  if (!post) notFound();

  // JSON-LD so the article is eligible for rich results.
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    headline: post.title,
    description: post.summary || undefined,
    datePublished: post.published_at || undefined,
    dateModified: post.updated_at || undefined,
    author: { "@type": "Organization", name: "Alpha Move AI" },
    publisher: { "@type": "Organization", name: "Alpha Move AI" },
    keywords: post.tags?.join(", ") || undefined,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <ResearchPostClient initialPost={post} />
    </>
  );
}
