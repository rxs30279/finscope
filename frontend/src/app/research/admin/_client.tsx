"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import "@uiw/react-md-editor/markdown-editor.css";
import "@uiw/react-markdown-preview/markdown.css";
import { API, adminHeaders } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useIsAdmin } from "@/hooks/useAdmin";
import PageHeader from "@/components/layout/PageHeader";
import ArticleView from "../_article";
import { fmtCommentDate, fmtPostDate, type ResearchPostSummary } from "@/lib/research";

// The Markdown editor manipulates the DOM (toolbar, split preview) and can't be
// server-rendered — load it client-only. While it loads, a plain disabled
// textarea holds the space so the form doesn't jump.
const MDEditor = dynamic(() => import("@uiw/react-md-editor"), {
  ssr: false,
  loading: () => (
    <textarea disabled style={{ width: "100%", minHeight: 420, background: "#0a0a0a", border: "1px solid #2a2a2a", borderRadius: 2, color: "#666", fontFamily: "monospace", padding: 12 }} value="Loading editor…" readOnly />
  ),
});

type CommentFilter = "pending" | "approved" | "rejected" | "all";

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
  image: string;
  body: string;
  status: "draft" | "published";
}

const BLANK: EditState = {
  id: null,
  title: "",
  slug: "",
  summary: "",
  tags: "",
  image: "",
  body: "",
  status: "draft",
};

// ── Local draft stash ─────────────────────────────────────────────────────────
// The whole article lives in React state while writing — a closed tab, crash or
// stray navigation would lose it all. Every edit is debounce-stashed here and
// offered back the next time the same post (or "new") is opened.
const stashKey = (id: number | null) => `ama_research_draft_${id ?? "new"}`;

function readStash(id: number | null): { ts: number; state: EditState } | null {
  try {
    const raw = window.localStorage.getItem(stashKey(id));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || !parsed.state) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeStash(state: EditState) {
  try {
    window.localStorage.setItem(stashKey(state.id), JSON.stringify({ ts: Date.now(), state }));
  } catch {
    /* storage full/unavailable — autosave is best-effort */
  }
}

function clearStash(id: number | null) {
  try {
    window.localStorage.removeItem(stashKey(id));
  } catch {
    /* ignore */
  }
}

export default function ResearchAdminClient() {
  const isAdmin = useIsAdmin();
  const [tab, setTab] = useState<"posts" | "comments">("posts");
  const [posts, setPosts] = useState<ResearchPostSummary[]>([]);
  const [comments, setComments] = useState<AdminComment[]>([]);
  const [commentFilter, setCommentFilter] = useState<CommentFilter>("pending");
  const [pendingCount, setPendingCount] = useState(0);
  const [edit, setEdit] = useState<EditState | null>(null);
  // What the DB currently holds for the open post — dirty = edit differs.
  const [saved, setSaved] = useState<EditState | null>(null);
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const dirty = edit !== null && saved !== null && JSON.stringify(edit) !== JSON.stringify(saved);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const editorWrapRef = useRef<HTMLDivElement | null>(null);
  const uploadSeq = useRef(0); // uniquifies upload placeholders (must be declared before the !isAdmin early return)

  const loadPosts = useCallback(() => {
    fetch(`${API}/research/admin/posts`, { headers: adminHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setPosts(d.posts || []))
      .catch(() => setMsg("Failed to load posts (is your admin token set?)"));
  }, []);

  const loadComments = useCallback((filter: CommentFilter) => {
    fetch(`${API}/research/admin/comments?status=${filter}`, { headers: adminHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        const list: AdminComment[] = d.comments || [];
        setComments(list);
        if (filter === "pending") setPendingCount(list.length);
        else if (filter === "all") setPendingCount(list.filter((c) => c.status === "pending").length);
      })
      .catch(() => setMsg("Failed to load comments."));
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    loadPosts();
    loadComments(commentFilter);
  }, [isAdmin, loadPosts, loadComments, commentFilter]);

  // Warn before the tab closes / navigates away with unsaved edits. (The
  // autosave stash would recover them, but the prompt avoids the scare.)
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      e.preventDefault();
      e.returnValue = ""; // Chrome requires returnValue to show the prompt
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // Debounced autosave of the open editor state to localStorage.
  useEffect(() => {
    if (!edit || !dirty) return;
    const t = setTimeout(() => writeStash(edit), 1000);
    return () => clearTimeout(t);
  }, [edit, dirty]);

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: colors.textDim, fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  // Open the editor on `loaded` (the DB truth), offering any newer stashed
  // draft for the same post first.
  const openWithStashCheck = (loaded: EditState) => {
    setMsg(null);
    setPreview(false);
    setSaved(loaded);
    const stash = readStash(loaded.id);
    if (stash && JSON.stringify(stash.state) !== JSON.stringify(loaded)) {
      const when = fmtCommentDate(new Date(stash.ts).toISOString());
      if (confirm(`Restore unsaved draft from ${when}? (Cancel discards it.)`)) {
        // Keep the DB identity fields — the stash may predate a slug change.
        setEdit({ ...stash.state, id: loaded.id });
        return;
      }
      clearStash(loaded.id);
    }
    setEdit(loaded);
  };

  const openNew = () => openWithStashCheck({ ...BLANK });

  const openEdit = async (id: number) => {
    setMsg(null);
    const res = await fetch(`${API}/research/admin/posts/${id}`, { headers: adminHeaders() });
    if (!res.ok) { setMsg("Couldn't open post."); return; }
    const p = await res.json();
    openWithStashCheck({
      id: p.id,
      title: p.title,
      slug: p.slug,
      summary: p.summary || "",
      tags: (p.tags || []).join(", "),
      image: p.image || "",
      body: p.body || "",
      status: p.status,
    });
  };

  // Save the current editor state. Stays in the editor (long-form writing needs
  // frequent saves); `close` exits afterwards. `publish` flips status.
  const savePost = async (opts: { publish?: boolean; close?: boolean } = {}) => {
    if (!edit) return;
    if (!edit.title.trim()) { setMsg("Title is required."); return; }
    setBusy(true);
    setMsg(null);
    const status = opts.publish === undefined ? edit.status : opts.publish ? "published" : "draft";
    const payload = {
      title: edit.title,
      slug: edit.slug || undefined,
      summary: edit.summary,
      tags: edit.tags.split(",").map((t) => t.trim()).filter(Boolean),
      image: edit.image.trim() || null,
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
      const d = await res.json();
      clearStash(edit.id); // covers the "new" stash too — the draft is now in the DB
      loadPosts();
      if (opts.close) {
        setEdit(null);
        setSaved(null);
        setMsg("Saved.");
      } else {
        // Adopt the server's identity (id on create, slug either way) so the
        // next save is a PUT to the right row, and reset the dirty baseline.
        const nowSaved: EditState = { ...edit, id: d.id, slug: d.slug || edit.slug, status };
        setEdit(nowSaved);
        setSaved(nowSaved);
        setMsg(`Saved at ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}.`);
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  };

  // ── Image upload ───────────────────────────────────────────────────────────
  // POSTs raw file bytes (no multipart) to the admin-gated upload endpoint;
  // the backend sniffs the type, content-hashes the name and returns the URL.
  const uploadImage = async (file: File): Promise<string> => {
    const res = await fetch(
      `${API}/research/images?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream", ...adminHeaders() },
        body: file,
      },
    );
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Upload failed (HTTP ${res.status})`);
    }
    return (await res.json()).url as string;
  };

  // Insert text into the body at the editor caret (or append when the editor
  // isn't focused, e.g. a file dropped from the desktop).
  const insertIntoBody = (snippet: string) => {
    const ta = editorWrapRef.current?.querySelector("textarea");
    setEdit((prev) => {
      if (!prev) return prev;
      const pos =
        ta && document.activeElement === ta ? ta.selectionStart ?? prev.body.length : prev.body.length;
      const pad = pos > 0 && prev.body[pos - 1] !== "\n" ? "\n" : "";
      return { ...prev, body: prev.body.slice(0, pos) + pad + snippet + "\n" + prev.body.slice(pos) };
    });
  };

  // Paste/drag images into the body: drop a placeholder at the caret right
  // away, then swap it for the real markdown when the upload lands. The empty
  // ![…]() placeholder renders nothing in the preview (the img guard).
  const addImagesToBody = (files: File[]) => {
    files.forEach(async (file) => {
      const placeholder = `![Uploading ${++uploadSeq.current} ${file.name}…]()`;
      insertIntoBody(placeholder);
      try {
        const url = await uploadImage(file);
        const alt = file.name.replace(/\.[^.]+$/, "").replace(/[\[\]()]/g, "");
        setEdit((prev) =>
          prev ? { ...prev, body: prev.body.replace(placeholder, `![${alt}](${url})`) } : prev,
        );
      } catch (err) {
        setEdit((prev) =>
          prev ? { ...prev, body: prev.body.replace(placeholder + "\n", "").replace(placeholder, "") } : prev,
        );
        setMsg(err instanceof Error ? err.message : "Image upload failed.");
      }
    });
  };

  const imageFilesFrom = (list: FileList | null | undefined): File[] =>
    Array.from(list || []).filter((f) => f.type.startsWith("image/"));

  const cancelEdit = () => {
    if (!edit) return;
    if (dirty && !confirm("Discard unsaved changes?")) return;
    clearStash(edit.id);
    setEdit(null);
    setSaved(null);
    setPreview(false);
    setMsg(null);
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
    if (res.ok) loadComments(commentFilter);
    else setMsg("Moderation failed.");
  };

  const deleteComment = async (id: number) => {
    if (!confirm("Delete this comment permanently?")) return;
    setBusy(true);
    const res = await fetch(`${API}/research/admin/comments/${id}`, {
      method: "DELETE",
      headers: adminHeaders(),
    });
    setBusy(false);
    if (res.ok) loadComments(commentFilter);
    else setMsg("Delete failed.");
  };

  // ── Editor view ────────────────────────────────────────────────────────────
  if (edit) {
    const actionRow = (
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 6, alignItems: "center" }}>
        <button onClick={() => savePost()} disabled={busy || !dirty} style={btn(dirty ? colors.accent : colors.textDim)}>
          Save{edit.status === "published" ? " (stays live)" : " draft"}
        </button>
        <button onClick={() => savePost({ close: true })} disabled={busy} style={btn(colors.textMuted)}>
          Save &amp; close
        </button>
        {edit.status !== "published" && (
          <button onClick={() => savePost({ publish: true })} disabled={busy} style={btn(colors.green)}>Save &amp; publish</button>
        )}
        {edit.status === "published" && (
          <button onClick={() => savePost({ publish: false })} disabled={busy} style={btn(colors.amber)}>Unpublish</button>
        )}
        <button onClick={() => setPreview(!preview)} disabled={busy} style={btn(colors.indigo)}>
          {preview ? "← Back to editor" : "Preview"}
        </button>
        <button onClick={cancelEdit} disabled={busy} style={btn(colors.textDim)}>
          {dirty ? "Discard & close" : "Close"}
        </button>
        {dirty && (
          <span style={{ fontFamily: "monospace", fontSize: 11, color: colors.amber }}>● unsaved changes</span>
        )}
      </div>
    );

    if (preview) {
      // Exactly the public article renderer, fed the unsaved state — what you
      // see here is what publishes.
      return (
        <div style={{ maxWidth: 760, margin: "0 auto" }}>
          <PageHeader title="Preview" subtitle="Rendered with the live article styling." />
          {msg && <div style={msgStyle}>{msg}</div>}
          {actionRow}
          <div style={{ marginTop: 28, borderTop: `1px solid ${colors.border}`, paddingTop: 28 }}>
            <ArticleView
              title={edit.title || "(untitled)"}
              dateLabel={edit.status === "published" ? fmtPostDate(new Date().toISOString()) : "draft preview"}
              tags={edit.tags.split(",").map((t) => t.trim()).filter(Boolean)}
              body={edit.body}
            />
          </div>
        </div>
      );
    }

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
          {/* Not a Field <label>: the Upload button is its own <label> for the
              hidden file input, and labels can't nest. */}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={{ fontFamily: "monospace", fontSize: 10, color: colors.textFaint, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Share image (optional — OG/Twitter card)
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <input value={edit.image} onChange={(e) => setEdit({ ...edit, image: e.target.value })} style={{ ...inputStyle, flex: 1 }} placeholder="/api/research/images/hero-….png — or use Upload" maxLength={500} />
              <label style={{ ...btn(colors.textMuted), display: "inline-flex", alignItems: "center", cursor: "pointer" }}>
                Upload…
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  style={{ display: "none" }}
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    e.target.value = ""; // allow re-picking the same file
                    if (!file) return;
                    try {
                      const url = await uploadImage(file);
                      setEdit((prev) => (prev ? { ...prev, image: url } : prev));
                    } catch (err) {
                      setMsg(err instanceof Error ? err.message : "Image upload failed.");
                    }
                  }}
                />
              </label>
            </div>
          </div>
          {/* Not wrapped in Field's <label>: the editor's toolbar buttons would
              trigger the label's click-to-focus and steal the caret. */}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span style={{ fontFamily: "monospace", fontSize: 10, color: colors.textFaint, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Body (Markdown — paste or drag images straight in to upload them)
            </span>
            <div
              data-color-mode="dark"
              ref={editorWrapRef}
              onPaste={(e) => {
                const files = imageFilesFrom(e.clipboardData?.files);
                if (files.length) {
                  e.preventDefault(); // image paste, not text — we handle it
                  addImagesToBody(files);
                }
              }}
              onDragOver={(e) => {
                if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
              }}
              onDrop={(e) => {
                const files = imageFilesFrom(e.dataTransfer?.files);
                if (files.length) {
                  e.preventDefault(); // stop the browser opening the file
                  addImagesToBody(files);
                }
              }}
            >
              <MDEditor
                value={edit.body}
                onChange={(v) => setEdit({ ...edit, body: v || "" })}
                height={480}
                preview="live"
                previewOptions={{
                  components: {
                    // While typing an image link the body transiently holds
                    // ![](), and <img src=""> makes React warn (and the browser
                    // re-request the page). Skip rendering until a URL exists.
                    // `node` (the markdown AST handle) must not reach the DOM.
                    img: ({ node: _node, ...props }: { node?: unknown } & React.ImgHTMLAttributes<HTMLImageElement>) =>
                      props.src ? <img {...props} style={{ maxWidth: "100%" }} /> : null,
                  },
                }}
                textareaProps={{
                  placeholder: "## A heading\n\nWrite in Markdown — the toolbar inserts it for you. Lists, links, tables, images and code all work.",
                }}
              />
            </div>
          </div>
          {actionRow}
        </div>
      </div>
    );
  }

  // ── List view ──────────────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <PageHeader
        title="Research admin"
        right={
          <Link
            href="/research"
            style={{
              fontFamily: "monospace",
              fontSize: 13,
              color: colors.accent,
              border: `1px solid ${colors.border}`,
              background: colors.accentBg,
              padding: "8px 14px",
              borderRadius: 2,
              textDecoration: "none",
              whiteSpace: "nowrap",
            }}
          >
            View site →
          </Link>
        }
      />

      <div style={{ display: "flex", gap: 4, borderBottom: `1px solid ${colors.border}`, marginBottom: 20 }}>
        <button onClick={() => setTab("posts")} style={{ ...tabStyle, ...(tab === "posts" ? tabActive : {}) }}>Posts ({posts.length})</button>
        <button onClick={() => setTab("comments")} style={{ ...tabStyle, ...(tab === "comments" ? tabActive : {}) }}>
          Comments{pendingCount ? ` (${pendingCount} pending)` : ""}
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
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {(["pending", "approved", "rejected", "all"] as CommentFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setCommentFilter(f)}
                style={{
                  ...miniBtn(commentFilter === f ? colors.accent : colors.textDim),
                  borderColor: commentFilter === f ? colors.accent : colors.border,
                  textTransform: "capitalize",
                }}
              >
                {f}
              </button>
            ))}
          </div>
          {comments.length === 0 && (
            <div style={emptyStyle}>
              {commentFilter === "pending" ? "No comments awaiting review. 🎉" : `No ${commentFilter === "all" ? "" : commentFilter + " "}comments.`}
            </div>
          )}
          {comments.map((c) => (
            <div key={c.id} style={{ ...rowStyle, flexDirection: "column", alignItems: "stretch", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "monospace", fontSize: 12, color: colors.indigo, fontWeight: 700 }}>
                  {c.author}
                  {c.email && <span style={{ color: colors.textFaint, fontWeight: 400 }}> · {c.email}</span>}
                  {commentFilter !== "pending" && (
                    <span style={{ color: c.status === "approved" ? colors.green : c.status === "rejected" ? colors.red : colors.amber, fontWeight: 400 }}>
                      {" "}· {c.status}
                    </span>
                  )}
                </span>
                <span style={{ fontFamily: "monospace", fontSize: 10, color: colors.textFaint }}>
                  on “{c.post_title}” · {fmtCommentDate(c.created_at)}
                </span>
              </div>
              <div style={{ color: colors.text, fontSize: 14, lineHeight: 1.6, whiteSpace: "pre-wrap", fontFamily: "var(--font-inter), sans-serif" }}>
                {c.body}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {c.status !== "approved" && (
                  <button onClick={() => moderate(c.id, "approve")} disabled={busy} style={miniBtn(colors.green)}>Approve</button>
                )}
                {c.status !== "rejected" && (
                  <button onClick={() => moderate(c.id, "reject")} disabled={busy} style={miniBtn(colors.red)}>Reject</button>
                )}
                <button onClick={() => deleteComment(c.id)} disabled={busy} style={miniBtn(colors.textDim)}>Delete</button>
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
