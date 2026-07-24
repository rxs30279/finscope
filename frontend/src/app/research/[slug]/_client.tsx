"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { colors } from "@/lib/theme";
import ArticleView from "../_article";
import DonateOutro from "@/components/DonateOutro";
import {
  fmtCommentDate,
  fmtPostDate,
  type ResearchComment,
  type ResearchPost,
  type ResearchPostSummary,
} from "@/lib/research";
import { coverFor } from "@/lib/researchCovers";

export default function ResearchPostClient({
  initialPost,
  allPosts = [],
}: {
  initialPost: ResearchPost;
  allPosts?: ResearchPostSummary[];
}) {
  const post = initialPost;
  const [comments, setComments] = useState<ResearchComment[] | null>(null);

  useEffect(() => {
    fetch(`${API}/research/posts/${post.slug}/comments`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => setComments(d.comments || []))
      .catch(() => setComments([]));
  }, [post.slug]);

  // Same list position the index page uses, so this post's hero cover matches
  // its card there. -1 (post not in the list / list unavailable) falls back to
  // a slug hash inside coverFor.
  const postIndex = useMemo(
    () => allPosts.findIndex((p) => p.slug === post.slug),
    [allPosts, post.slug],
  );
  const cover = coverFor(post, postIndex);
  const readMins = useMemo(() => {
    const words = post.body.trim().split(/\s+/).filter(Boolean).length;
    return Math.max(1, Math.round(words / 220));
  }, [post.body]);

  // Prefer posts sharing a tag; fall back to the newest other posts.
  const related = useMemo(() => {
    const others = allPosts.filter((p) => p.slug !== post.slug);
    const tagged = others.filter((p) => p.tags?.some((t) => post.tags?.includes(t)));
    return (tagged.length ? tagged : others).slice(0, 3);
  }, [allPosts, post.slug, post.tags]);

  return (
    <div className="amr amr-bleed">
      {/* ── Hero ─────────────────────────────────────────────── */}
      <div className="amra-hero">
        <div
          className="amra-himg"
          style={{ backgroundImage: `url("${cover.src}")`, backgroundPosition: cover.position }}
        />
        <div className="amra-hscrim" />
        <Link href="/research" className="amra-back">
          ← All research
        </Link>
        <div className="amra-hinner">
          <div className="amra-tagrow">
            {post.tags?.map((t) => (
              <span key={t} className="amra-tag">
                {t}
              </span>
            ))}
          </div>
          <h1>{post.title}</h1>
          <div className="amra-meta">
            <span className="amra-avatar">A</span>
            <span>Alpha Move AI</span>
            <span className="amra-sep">·</span>
            <span>{fmtPostDate(post.published_at)}</span>
            <span className="amra-sep">·</span>
            <span>{readMins} min read</span>
          </div>
        </div>
      </div>

      {/* ── Body ─────────────────────────────────────────────── */}
      <div className="amra-col">
        <ArticleView
          title={post.title}
          dateLabel={fmtPostDate(post.published_at)}
          tags={post.tags}
          body={post.body}
          showHeader={false}
        />
      </div>

      {/* ── Related ──────────────────────────────────────────── */}
      {related.length > 0 && (
        <div className="amra-related">
          <div className="amra-related-inner">
            <h4>Related notes</h4>
            <div className="amra-rgrid">
              {related.map((p) => {
                const c = coverFor(p, allPosts.findIndex((x) => x.slug === p.slug));
                return (
                  <Link key={p.id} href={`/research/${p.slug}`} className="amra-rcard">
                    <div className="amra-rthumb">
                      <i style={{ backgroundImage: `url("${c.src}")`, backgroundPosition: c.position }} />
                    </div>
                    <div className="amra-rcbody">
                      {p.tags?.[0] && <span className="amra-tag">{p.tags[0]}</span>}
                      <h3>{p.title}</h3>
                      <span className="amra-rdate">{fmtPostDate(p.published_at)}</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── Support + comments ───────────────────────────────── */}
      <div className="amra-col">
        <DonateOutro source="research_post" />
        <CommentsSection slug={post.slug} comments={comments} />
      </div>

      <ArticlePageStyles />
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

// Layout styles for the article hero + related strip. Scoped by `.amr`/`.amra`
// prefixes; the body prose keeps ArticleView's own `.research-prose` styles.
function ArticlePageStyles() {
  return (
    <style jsx global>{`
      .amr {
        --white: #f1f5f9;
        --text: #e5e5e5;
        --muted: #a0a0b8;
        --faint: #6b6b85;
        --dim: #55556b;
        --border: #342a52;
        --border-subtle: #271d40;
        --card: #1b1330;
        --alt: #140c26;
        --indigo: #a5aefc;
        --purple: #a855f7;
        --indigo-ghost: rgba(129, 140, 248, 0.12);
        --orange: #f97316;
        color: var(--text);
        position: relative;
        background:
          radial-gradient(1100px 620px at 80% -8%, rgba(147, 51, 234, 0.12), transparent 60%),
          radial-gradient(900px 700px at 4% 8%, rgba(109, 40, 217, 0.18), transparent 55%),
          radial-gradient(1200px 900px at 50% 118%, rgba(124, 58, 237, 0.20), transparent 60%),
          linear-gradient(180deg, #1b1136 0%, #150c29 48%, #100820 100%);
      }
      .amr-bleed { margin: -16px -24px 0; }
      @media (max-width: 943px) { .amr-bleed { margin: -12px -12px 0; } }
      .amr a { text-decoration: none; color: inherit; }
      .amr h1, .amr h2, .amr h3, .amr h4 {
        font-family: var(--font-mulish), var(--font-inter), sans-serif; text-wrap: balance;
      }

      .amra-col { max-width: 760px; margin: 0 auto; padding: 0 22px; }

      /* Hero */
      .amra-hero { position: relative; height: 420px; overflow: hidden; }
      .amra-himg { position: absolute; inset: 0; background-size: cover; transform: scale(1.03); }
      .amra-hscrim {
        position: absolute; inset: 0;
        background: linear-gradient(180deg, rgba(27, 17, 54, 0.4) 0%, rgba(21, 12, 41, 0.35) 30%, #1b1136 100%);
      }
      .amra-back {
        position: absolute; top: 18px; left: 50%; transform: translateX(-50%);
        width: 100%; max-width: 760px; padding: 0 22px; box-sizing: border-box; z-index: 2;
        font-family: var(--font-inter), sans-serif; font-size: 12px; font-weight: 600; color: var(--indigo);
      }
      .amra-hinner {
        position: relative; max-width: 760px; margin: 0 auto; height: 100%;
        display: flex; flex-direction: column; justify-content: flex-end; padding: 0 22px 36px;
      }
      .amra-tagrow { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
      .amra-tag {
        font-family: var(--font-inter), sans-serif; font-size: 10px; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.09em; color: var(--indigo);
        background: var(--indigo-ghost); border: 1px solid rgba(129, 140, 248, 0.22);
        padding: 3px 9px; border-radius: 3px;
      }
      .amra-hero h1 {
        font-size: clamp(28px, 4.4vw, 46px); font-weight: 800; letter-spacing: -0.03em;
        line-height: 1.05; color: var(--white); margin: 12px 0 0;
      }
      .amra-meta {
        display: flex; align-items: center; gap: 12px; margin-top: 16px;
        font-size: 12px; color: var(--muted); flex-wrap: wrap;
        font-family: var(--font-inter), sans-serif;
      }
      .amra-avatar {
        width: 26px; height: 26px; border-radius: 50%; display: inline-flex;
        align-items: center; justify-content: center; font-size: 11px; font-weight: 800; color: #0a0a0a;
        background: linear-gradient(135deg, var(--purple), var(--indigo));
      }
      .amra-sep { color: #52525b; }

      .amra-col { padding-top: 40px; }

      /* Related */
      .amra-related { border-top: 1px solid var(--border-subtle); margin-top: 40px; background: var(--alt); }
      .amra-related-inner { max-width: 1000px; margin: 0 auto; padding: 40px 22px 8px; }
      .amra-related h4 { margin: 0 0 18px; font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--indigo); }
      .amra-rgrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
      .amra-rcard {
        border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--card);
        display: flex; flex-direction: column; transition: box-shadow 0.18s ease, border-color 0.18s ease;
      }
      .amra-rcard:hover { border-color: #3a3550; box-shadow: 0 10px 28px rgba(0, 0, 0, 0.38); }
      .amra-rthumb { position: relative; aspect-ratio: 16 / 10; overflow: hidden; }
      .amra-rthumb i { position: absolute; inset: 0; background-size: cover; transition: transform 0.5s ease; }
      .amra-rcard:hover .amra-rthumb i { transform: scale(1.07); }
      .amra-rcbody { padding: 15px 16px 18px; display: flex; flex-direction: column; gap: 9px; }
      .amra-rcard h3 { font-size: 15.5px; font-weight: 800; letter-spacing: -0.015em; line-height: 1.25; color: var(--white); margin: 0; }
      .amra-rdate { font-size: 10.5px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.06em; font-variant-numeric: tabular-nums; }

      @media (max-width: 720px) {
        .amra-hero { height: 340px; }
        .amra-rgrid { grid-template-columns: 1fr; }
      }
      @media (prefers-reduced-motion: reduce) {
        .amr *, .amr *::before, .amr *::after { transition: none !important; animation: none !important; }
        .amra-rcard:hover { transform: none; }
      }
    `}</style>
  );
}
