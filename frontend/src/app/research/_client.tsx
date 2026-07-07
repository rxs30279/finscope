"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";
import { fmtPostDate, type ResearchPostSummary } from "@/lib/research";

export default function ResearchListClient({
  initialPosts,
}: {
  initialPosts: ResearchPostSummary[] | null;
}) {
  const isAdmin = useIsAdmin();
  // Server-rendered when the page's server fetch succeeded; the client fetch
  // below is only the fallback for when it didn't.
  const [posts, setPosts] = useState<ResearchPostSummary[] | null>(initialPosts);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (initialPosts !== null) return;
    fetch(`${API}/research/posts`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setPosts(d.posts || []))
      .catch(() => setError(true));
  }, [initialPosts]);

  return (
    <div style={{ maxWidth: 820, margin: "0 auto" }}>
      <PageHeader
        title="Research"
        subtitle="Analysis, market notes and data-driven commentary on UK equities."
        right={
          isAdmin ? (
            <Link
              href="/research/admin"
              style={{
                fontFamily: "monospace",
                fontSize: 11,
                color: colors.accent,
                border: `1px solid ${colors.border}`,
                background: colors.accentBg,
                padding: "6px 12px",
                borderRadius: 2,
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              ✎ Manage posts
            </Link>
          ) : undefined
        }
      />

      {error && (
        <div style={{ ...loadingStyle, color: colors.red }}>Couldn&apos;t load posts.</div>
      )}
      {!error && posts === null && <div style={loadingStyle}>Loading…</div>}
      {!error && posts !== null && posts.length === 0 && (
        <div style={loadingStyle}>No articles published yet — check back soon.</div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {posts?.map((p) => (
          <Link
            key={p.id}
            href={`/research/${p.slug}`}
            style={{ textDecoration: "none", display: "block" }}
          >
            <article
              style={{
                background: colors.bgCard,
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                padding: 20,
                transition: "border-color 0.15s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.borderColor = colors.accent)}
              onMouseLeave={(e) => (e.currentTarget.style.borderColor = colors.border)}
            >
              <div
                style={{
                  fontFamily: "monospace",
                  fontSize: 10,
                  color: colors.textFaint,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  marginBottom: 8,
                  display: "flex",
                  gap: 10,
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <span>{fmtPostDate(p.published_at)}</span>
                {p.comment_count > 0 && (
                  <span style={{ color: colors.textDim }}>
                    · {p.comment_count} comment{p.comment_count === 1 ? "" : "s"}
                  </span>
                )}
                {p.tags?.map((t) => (
                  <span
                    key={t}
                    style={{
                      color: colors.indigo,
                      background: "#0d0d0d",
                      border: `1px solid ${colors.borderSubtle}`,
                      padding: "1px 6px",
                      borderRadius: 2,
                    }}
                  >
                    {t}
                  </span>
                ))}
              </div>
              <h2
                style={{
                  fontFamily: "var(--font-mulish), var(--font-inter), sans-serif",
                  fontSize: 20,
                  fontWeight: 700,
                  color: colors.white,
                  margin: "0 0 8px",
                  lineHeight: 1.3,
                }}
              >
                {p.title}
              </h2>
              {p.summary && (
                <p
                  style={{
                    margin: 0,
                    color: colors.textMuted,
                    fontSize: 14,
                    lineHeight: 1.6,
                    fontFamily: "var(--font-inter), sans-serif",
                  }}
                >
                  {p.summary}
                </p>
              )}
            </article>
          </Link>
        ))}
      </div>
    </div>
  );
}

const loadingStyle: React.CSSProperties = {
  textAlign: "center",
  padding: 48,
  color: colors.textDim,
  fontFamily: "monospace",
  fontSize: 14,
};
