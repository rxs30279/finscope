"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";
import { fmtPostDate, type ResearchPostSummary } from "@/lib/research";

interface AdminComment {
  id: number;
  post_id: number;
  post_slug: string;
  post_title: string;
  author: string;
  email: string | null;
  body: string;
  status: string;
  created_at: string | null;
}

interface EditState {
  id: number | null;
  title: string;
  slug: string;
  summary: string;
  tags: string;
  body: string;
  status: "draft" | "published";
}

const BLANK: EditState = {
  id: null,
  title: "",
  slug: "",
  summary: "",
  tags: "",
  body: "",
  status: "draft",
};

export default function ResearchAdminClient() {
  const isAdmin = useIsAdmin();
  const [tab, setTab] = useState<"posts" | "comments">("posts");
  const [posts, setPosts] = useState<ResearchPostSummary[]>([]);
  const [comments, setComments] = useState<AdminComment[]>([]);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const loadPosts = useCallback(() => {
    fetch(`${API}/research/admin/posts`, { headers: adminHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setPosts(d.posts || []))
      .catch(() => setMsg("Failed to load posts (is your admin token set?)"));
  }, []);

  const loadComments = useCallback(() => {
    fetch(`${API}/research/admin/comments?status=pending`, { headers: adminHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setComments(d.comments || []))
      .catch(() => setMsg("Failed to load comments."));
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    loadPosts();
    loadComments();
  }, [isAdmin, loadPosts, loadComments]);

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: colors.textDim, fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  const openNew = () => { setEdit({ ...BLANK }); setMsg(null); };

  const openEdit = async (id: number) => {
    setMsg(null);
    const res = await fetch(`${API}/research/admin/posts/${id}`, { headers: adminHeaders() });
    if (!res.ok) { setMsg("Couldn't open post."); return; }
    const p = await res.json();
    setEdit({
      id: p.id,
      title: p.title,
      slug: p.slug,
      summary: p.summary || "",
      tags: (p.tags || []).join(", "),
      body: p.body || "",
      status: p.status,
    });
  };

  const savePost = async (publish?: boolean) => {
    if (!edit) return;
    if (!edit.title.trim()) { setMsg("Title is required."); return; }
    setBusy(true);
    setMsg(null);
    const status = publish === undefined ? edit.status : publish ? "published" : "draft";
    const payload = {
      title: edit.title,
      slug: edit.slug || undefined,
      summary: edit.summary,
      tags: edit.tags.split(",").map((t) => t.trim()).filter(Boolean),
      body: edit.body,
      status,
    };
    const url = edit.id ? `${API}/research/admin/posts/${edit.id}` : `${API}/research/admin/posts`;
    const method = edit.id ? "PUT" : "POST";
    try {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json", ...adminHeaders() },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      setEdit(null);
      loadPosts();
      setMsg("Saved.");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  };

  const togglePublish = async (p: ResearchPostSummary) => {
    // Status-only endpoint — never sends (and so never clobbers) the body/title.
    setBusy(true);
    const res = await fetch(`${API}/research/admin/posts/${p.id}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ status: p.status === "published" ? "draft" : "published" }),
    });
    setBusy(false);
    if (res.ok) loadPosts();
    else setMsg("Couldn't change status.");
  };

  const deletePost = async (id: number) => {
    if (!confirm("Delete this post and all its comments? This can't be undone.")) return;
    setBusy(true);
    const res = await fetch(`${API}/research/admin/posts/${id}`, {
      method: "DELETE",
      headers: adminHeaders(),
    });
    setBusy(false);
    if (res.ok) loadPosts();
    else setMsg("Delete failed.");
  };

  const moderate = async (id: number, action: "approve" | "reject") => {
    setBusy(true);
    const res = await fetch(`${API}/research/admin/comments/${id}/moderate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ action }),
    });
    setBusy(false);
    if (res.ok) loadComments();
    else setMsg("Moderation failed.");
  };

  // ── Editor view ────────────────────────────────────────────────────────────
  if (edit) {
    return (
      <div style={{ maxWidth: 820, margin: "0 auto" }}>
        <PageHeader title={edit.id ? "Edit post" : "New post"} />
        {msg && <div style={msgStyle}>{msg}</div>}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <Field label="Title">
            <input value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} style={inputStyle} maxLength={200} />
          </Field>
          <Field label="Slug (optional — auto from title)">
            <input value={edit.slug} onChange={(e) => setEdit({ ...edit, slug: e.target.value })} style={inputStyle} placeholder="my-post-url" />
          </Field>
          <Field label="Summary (shown on the list + as the meta description)">
            <textarea value={edit.summary} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} style={{ ...inputStyle, resize: "vertical" }} rows={2} maxLength={500} />
          </Field>
          <Field label="Tags (comma-separated)">
            <input value={edit.tags} onChange={(e) => setEdit({ ...edit, tags: e.target.value })} style={inputStyle} placeholder="valuation, small-caps" />
          </Field>
          <Field label="Body (Markdown)">
            <textarea
              value={edit.body}
              onChange={(e) => setEdit({ ...edit, body: e.target.value })}
              style={{ ...inputStyle, resize: "vertical", minHeight: 320, lineHeight: 1.6 }}
              placeholder={"## A heading\n\nWrite in **Markdown**. Lists, links, tables and code all work."}
            />
          </Field>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 6 }}>
            <button onClick={() => savePost(undefined)} disabled={busy} style={btn(colors.textMuted)}>
              Save {edit.status === "published" ? "(keep published)" : "draft"}
            </button>
            {edit.status !== "published" && (
              <button onClick={() => savePost(true)} disabled={busy} style={btn(colors.accent)}>Save &amp; publish</button>
            )}
            {edit.status === "published" && (
              <button onClick={() => savePost(false)} disabled={busy} style={btn(colors.amber)}>Unpublish</button>
            )}
            <button onClick={() => { setEdit(null); setMsg(null); }} disabled={busy} style={btn(colors.textDim)}>Cancel</button>
          </div>
        </div>
      </div>
    );
  }

  // ── List view ──────────────────────────────────────────────────────────────
  const pendingCount = comments.length;
  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <PageHeader
        title="Research admin"
        right={
          <Link href="/research" style={{ fontFamily: "monospace", fontSize: 11, color: colors.textMuted, textDecoration: "none" }}>
            View site →
          </Link>
        }
      />

      <div style={{ display: "flex", gap: 4, borderBottom: `1px solid ${colors.border}`, marginBottom: 20 }}>
        <button onClick={() => setTab("posts")} style={{ ...tabStyle, ...(tab === "posts" ? tabActive : {}) }}>Posts ({posts.length})</button>
        <button onClick={() => setTab("comments")} style={{ ...tabStyle, ...(tab === "comments" ? tabActive : {}) }}>
          Pending comments{pendingCount ? ` (${pendingCount})` : ""}
        </button>
      </div>

      {msg && <div style={msgStyle}>{msg}</div>}

      {tab === "posts" && (
        <>
          <button onClick={openNew} style={{ ...btn(colors.accent), marginBottom: 16 }}>+ New post</button>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {posts.length === 0 && <div style={emptyStyle}>No posts yet.</div>}
            {posts.map((p) => (
              <div key={p.id} style={rowStyle}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 3 }}>
                    <span style={{
                      fontSize: 9, fontFamily: "monospace", textTransform: "uppercase", letterSpacing: 0.5,
                      padding: "1px 6px", borderRadius: 2,
                      color: p.status === "published" ? colors.green : colors.amber,
                      border: `1px solid ${p.status === "published" ? "#14432f" : "#4a3a1a"}`,
                      background: p.status === "published" ? "#0c1f16" : "#1a1400",
                    }}>
                      {p.status}
                    </span>
                    <span style={{ color: colors.text, fontSize: 14, fontWeight: 600, fontFamily: "var(--font-inter), sans-serif", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.title}
                    </span>
                  </div>
                  <div style={{ fontFamily: "monospace", fontSize: 10, color: colors.textFaint }}>
                    /research/{p.slug}
                    {p.published_at ? ` · ${fmtPostDate(p.published_at)}` : ""}
                    {p.comment_count ? ` · ${p.comment_count} comment${p.comment_count === 1 ? "" : "s"}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <button onClick={() => openEdit(p.id)} style={miniBtn(colors.textMuted)}>Edit</button>
                  <button onClick={() => togglePublish(p)} disabled={busy} style={miniBtn(p.status === "published" ? colors.amber : colors.green)}>
                    {p.status === "published" ? "Unpublish" : "Publish"}
                  </button>
                  <button onClick={() => deletePost(p.id)} disabled={busy} style={miniBtn(colors.red)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {tab === "comments" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {comments.length === 0 && <div style={emptyStyle}>No comments awaiting review. 🎉</div>}
          {comments.map((c) => (
            <div key={c.id} style={{ ...rowStyle, flexDirection: "column", alignItems: "stretch", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "monospace", fontSize: 12, color: colors.indigo, fontWeight: 700 }}>
                  {c.author}
                  {c.email && <span style={{ color: colors.textFaint, fontWeight: 400 }}> · {c.email}</span>}
                </span>
                <span style={{ fontFamily: "monospace", fontSize: 10, color: colors.textFaint }}>
                  on “{c.post_title}” · {fmtPostDate(c.created_at)}
                </span>
              </div>
              <div style={{ color: colors.text, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap", fontFamily: "var(--font-inter), sans-serif" }}>
                {c.body}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button onClick={() => moderate(c.id, "approve")} disabled={busy} style={miniBtn(colors.green)}>Approve</button>
                <button onClick={() => moderate(c.id, "reject")} disabled={busy} style={miniBtn(colors.red)}>Reject</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      <span style={{ fontFamily: "monospace", fontSize: 10, color: colors.textFaint, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</span>
      {children}
    </label>
  );
}

const inputStyle: CSSProperties = {
  background: colors.bg,
  border: `1px solid ${colors.border}`,
  borderRadius: 2,
  padding: "9px 12px",
  color: colors.text,
  fontSize: 14,
  outline: "none",
  fontFamily: "monospace",
  width: "100%",
  boxSizing: "border-box",
};

const rowStyle: CSSProperties = {
  display: "flex",
  gap: 12,
  alignItems: "center",
  background: colors.bgCard,
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  padding: "12px 16px",
};

const tabStyle: CSSProperties = {
  background: "none",
  border: "none",
  padding: "10px 16px",
  color: colors.textDim,
  cursor: "pointer",
  borderBottom: "2px solid transparent",
  fontSize: 12,
  fontFamily: "monospace",
  textTransform: "uppercase",
  letterSpacing: 0.5,
};

const tabActive: CSSProperties = { color: colors.accent, borderBottom: `2px solid ${colors.accent}`, fontWeight: 700 };

const msgStyle: CSSProperties = {
  background: colors.bgCardAlt,
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  padding: "10px 14px",
  color: colors.amber,
  fontFamily: "monospace",
  fontSize: 12,
  marginBottom: 16,
};

const emptyStyle: CSSProperties = {
  textAlign: "center",
  padding: 40,
  color: colors.textDim,
  fontFamily: "monospace",
  fontSize: 13,
};

const btn = (c: string): CSSProperties => ({
  background: "none",
  color: c,
  border: `1px solid ${c}`,
  borderRadius: 2,
  padding: "8px 16px",
  fontFamily: "monospace",
  fontSize: 12,
  cursor: "pointer",
});

const miniBtn = (c: string): CSSProperties => ({
  background: "none",
  color: c,
  border: `1px solid ${colors.border}`,
  borderRadius: 2,
  padding: "4px 10px",
  fontFamily: "monospace",
  fontSize: 11,
  cursor: "pointer",
});
