"use client";

import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { colors } from "@/lib/theme";
import ArticleView from "../_article";
import { fmtCommentDate, fmtPostDate, type ResearchComment, type ResearchPost } from "@/lib/research";

export default function ResearchPostClient({ initialPost }: { initialPost: ResearchPost }) {
  const post = initialPost;
  const [comments, setComments] = useState<ResearchComment[] | null>(null);

  useEffect(() => {
    fetch(`${API}/research/posts/${post.slug}/comments`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setComments(d.comments || []))
      .catch(() => setComments([]));
  }, [post.slug]);

  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <Link
        href="/research"
        style={{
          fontFamily: "monospace",
          fontSize: 12,
          color: colors.accent,
          textDecoration: "none",
          display: "inline-block",
          marginBottom: 20,
        }}
      >
        ← All research
      </Link>

      <ArticleView
        title={post.title}
        dateLabel={fmtPostDate(post.published_at)}
        tags={post.tags}
        body={post.body}
      />

      <CommentsSection slug={post.slug} comments={comments} />
    </div>
  );
}

// ── Comments ────────────────────────────────────────────────────────────────
function CommentsSection({
  slug,
  comments,
}: {
  slug: string;
  comments: ResearchComment[] | null;
}) {
  const [author, setAuthor] = useState("");
  const [email, setEmail] = useState("");
  const [body, setBody] = useState("");
  const [website, setWebsite] = useState(""); // honeypot
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">("idle");
  const [errMsg, setErrMsg] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!author.trim() || !body.trim()) return;
    setState("sending");
    setErrMsg("");
    try {
      const res = await fetch(`${API}/research/posts/${slug}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author, email, body, website }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      setState("done");
      setAuthor("");
      setEmail("");
      setBody("");
    } catch (err) {
      setState("error");
      setErrMsg(err instanceof Error ? err.message : "Something went wrong");
    }
  };

  return (
    <section
      style={{
        marginTop: 48,
        paddingTop: 28,
        borderTop: `1px solid ${colors.border}`,
      }}
    >
      <h3 style={sectionTitle}>
        Comments{comments && comments.length > 0 ? ` (${comments.length})` : ""}
      </h3>

      {comments === null && <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 13 }}>Loading…</div>}
      {comments !== null && comments.length === 0 && (
        <div style={{ color: colors.textDim, fontFamily: "monospace", fontSize: 13, marginBottom: 24 }}>
          No comments yet. Be the first.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 32 }}>
        {comments?.map((c) => (
          <div
            key={c.id}
            style={{
              background: colors.bgCard,
              border: `1px solid ${colors.borderSubtle}`,
              borderRadius: 4,
              padding: "12px 16px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
              <span style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 700, color: colors.indigo }}>
                {c.author}
              </span>
              <span style={{ fontFamily: "monospace", fontSize: 11, color: colors.textFaint }}>
                {fmtCommentDate(c.created_at)}
              </span>
            </div>
            <div style={{ color: colors.text, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap", fontFamily: "var(--font-inter), sans-serif" }}>
              {c.body}
            </div>
          </div>
        ))}
      </div>

      <h3 style={sectionTitle}>Leave a comment</h3>
      {state === "done" ? (
        <div
          style={{
            background: colors.bgCardAlt,
            border: `1px solid ${colors.green}`,
            borderRadius: 4,
            padding: 16,
            color: colors.green,
            fontFamily: "monospace",
            fontSize: 13,
          }}
        >
          Thanks — your comment was submitted and will appear once it&apos;s reviewed.
        </div>
      ) : (
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <input
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="Name *"
              maxLength={80}
              required
              style={{ ...inputStyle, flex: 1, minWidth: 160 }}
            />
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email (optional, not shown)"
              type="email"
              style={{ ...inputStyle, flex: 1, minWidth: 160 }}
            />
          </div>
          {/* Honeypot — visually hidden, real users never touch it. */}
          <input
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            tabIndex={-1}
            autoComplete="off"
            aria-hidden="true"
            style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Your comment *"
            rows={4}
            maxLength={4000}
            required
            style={{ ...inputStyle, resize: "vertical", fontFamily: "var(--font-inter), sans-serif" }}
          />
          {state === "error" && (
            <div style={{ color: colors.red, fontFamily: "monospace", fontSize: 12 }}>{errMsg}</div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button
              type="submit"
              disabled={state === "sending"}
              style={{
                background: colors.accentBg,
                color: colors.accent,
                border: `1px solid ${colors.accent}`,
                borderRadius: 2,
                padding: "8px 20px",
                fontFamily: "monospace",
                fontSize: 12,
                cursor: state === "sending" ? "not-allowed" : "pointer",
                opacity: state === "sending" ? 0.6 : 1,
              }}
            >
              {state === "sending" ? "Submitting…" : "Submit comment"}
            </button>
            <span style={{ color: colors.textFaint, fontFamily: "monospace", fontSize: 11 }}>
              Comments are reviewed before they appear.
            </span>
          </div>
        </form>
      )}
    </section>
  );
}

const sectionTitle: CSSProperties = {
  fontFamily: "monospace",
  fontSize: 13,
  fontWeight: 700,
  color: colors.accent,
  textTransform: "uppercase",
  letterSpacing: 1,
  margin: "0 0 16px",
};

const inputStyle: CSSProperties = {
  background: colors.bg,
  border: `1px solid ${colors.border}`,
  borderRadius: 2,
  padding: "9px 12px",
  color: colors.text,
  fontSize: 14,
  outline: "none",
  fontFamily: "monospace",
};
