"""Research — an analysis blog for the site.

Two audiences, one router:
  • Public (no auth): read published posts and their approved comments, and
    submit a comment (which lands 'pending' — see moderation below).
  • Admin (X-Admin-Token, via admin_auth.require_admin_token): the in-browser
    editor — create / edit / publish / delete posts, and work the comment
    moderation queue.

Comments are moderated: every submission is stored as status='pending' and is
invisible until an admin approves it. A honeypot field ('website') catches the
bots that fill every input — we accept-and-drop those so they don't retry.

DB access goes through main.query (imported lazily to dodge the import cycle:
main.py registers this router before query() is defined). query() runs with
autocommit and always fetchall()s, so every write must end in RETURNING.

Migration: migrations/010_research.sql
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from admin_auth import require_admin_token

router = APIRouter(prefix="/api/research", tags=["research"])

_MAX_TITLE = 200
_MAX_SUMMARY = 500
_MAX_BODY = 100_000
_MAX_COMMENT = 4000
_MAX_AUTHOR = 80
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _q(sql, params=None):
    from main import query
    return query(sql, params)


def _slugify(text: str) -> str:
    """Lowercase, hyphenated, ASCII-ish slug. Empty input -> 'post'."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:80] or "post"


def _unique_slug(base: str, exclude_id: Optional[int] = None) -> str:
    """Append -2, -3, … until the slug is free (ignoring the row being edited)."""
    slug = base
    n = 1
    while True:
        rows = _q(
            "SELECT id FROM research_posts WHERE slug = %s AND (%s::bigint IS NULL OR id <> %s)",
            (slug, exclude_id, exclude_id),
        )
        if not rows:
            return slug
        n += 1
        slug = f"{base}-{n}"


# ── Serialisation ─────────────────────────────────────────────────────────────
def _post_summary(r: dict) -> dict:
    """List-card shape: no body, plus the approved-comment tally."""
    return {
        "id": r["id"],
        "slug": r["slug"],
        "title": r["title"],
        "summary": r["summary"],
        "tags": r["tags"] or [],
        "status": r["status"],
        "published_at": r["published_at"].isoformat() if r["published_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        "comment_count": int(r.get("comment_count") or 0),
    }


def _post_full(r: dict) -> dict:
    out = _post_summary(r)
    out["body"] = r["body"]
    out["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
    return out


def _comment_public(r: dict) -> dict:
    # Email is intentionally omitted — it's owner-only reference data.
    return {
        "id": r["id"],
        "author": r["author"],
        "body": r["body"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


# ── Public: posts ─────────────────────────────────────────────────────────────
@router.get("/posts")
def list_posts():
    """Published posts, newest first, with approved-comment counts."""
    rows = _q(
        """
        SELECT p.*, (
            SELECT COUNT(*) FROM research_comments c
            WHERE c.post_id = p.id AND c.status = 'approved'
        ) AS comment_count
        FROM research_posts p
        WHERE p.status = 'published'
        ORDER BY p.published_at DESC NULLS LAST, p.id DESC
        """
    )
    return {"posts": [_post_summary(r) for r in rows]}


@router.get("/posts/{slug}")
def get_post(slug: str):
    rows = _q(
        """
        SELECT p.*, (
            SELECT COUNT(*) FROM research_comments c
            WHERE c.post_id = p.id AND c.status = 'approved'
        ) AS comment_count
        FROM research_posts p
        WHERE p.slug = %s AND p.status = 'published'
        """,
        (slug,),
    )
    if not rows:
        raise HTTPException(404, "Post not found")
    return _post_full(rows[0])


@router.get("/posts/{slug}/comments")
def list_comments(slug: str):
    rows = _q(
        """
        SELECT c.id, c.author, c.body, c.created_at
        FROM research_comments c
        JOIN research_posts p ON p.id = c.post_id
        WHERE p.slug = %s AND p.status = 'published' AND c.status = 'approved'
        ORDER BY c.created_at ASC
        """,
        (slug,),
    )
    return {"comments": [_comment_public(r) for r in rows]}


class CommentBody(BaseModel):
    author: str
    body: str
    email: Optional[str] = None
    # Honeypot: a hidden field real users leave blank; bots fill it. Any value
    # here => accept-and-drop so the bot thinks it succeeded and moves on.
    website: Optional[str] = None


@router.post("/posts/{slug}/comments")
def submit_comment(slug: str, payload: CommentBody):
    if (payload.website or "").strip():
        return {"ok": True, "pending": True}  # honeypot — silently discard

    author = (payload.author or "").strip()
    body = (payload.body or "").strip()
    if not author:
        raise HTTPException(400, "Name is required")
    if len(author) > _MAX_AUTHOR:
        raise HTTPException(400, f"Name too long (max {_MAX_AUTHOR})")
    if not body:
        raise HTTPException(400, "Comment is required")
    if len(body) > _MAX_COMMENT:
        raise HTTPException(400, f"Comment too long (max {_MAX_COMMENT})")

    email = (payload.email or "").strip().lower()
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(400, "Invalid email address")

    rows = _q(
        "SELECT id FROM research_posts WHERE slug = %s AND status = 'published'",
        (slug,),
    )
    if not rows:
        raise HTTPException(404, "Post not found")
    post_id = rows[0]["id"]

    _q(
        """
        INSERT INTO research_comments (post_id, author, email, body)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (post_id, author, email or None, body),
    )
    # Moderated: the comment won't show until approved. Tell the reader so.
    return {"ok": True, "pending": True}


# ── Admin: posts ──────────────────────────────────────────────────────────────
class PostBody(BaseModel):
    title: str
    summary: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[list[str]] = None
    slug: Optional[str] = None            # optional override; auto from title otherwise
    status: Optional[str] = None          # 'draft' | 'published'


def _clean_tags(tags) -> list[str]:
    if not tags:
        return []
    seen, out = set(), []
    for t in tags:
        t = (t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t[:40])
    return out[:12]


@router.get("/admin/posts", dependencies=[Depends(require_admin_token)])
def admin_list_posts():
    """Every post incl. drafts, newest activity first — the editor's index."""
    rows = _q(
        """
        SELECT p.*, (
            SELECT COUNT(*) FROM research_comments c
            WHERE c.post_id = p.id AND c.status = 'approved'
        ) AS comment_count
        FROM research_posts p
        ORDER BY COALESCE(p.published_at, p.updated_at) DESC, p.id DESC
        """
    )
    return {"posts": [_post_summary(r) for r in rows]}


@router.get("/admin/posts/{post_id}", dependencies=[Depends(require_admin_token)])
def admin_get_post(post_id: int):
    rows = _q("SELECT p.*, 0 AS comment_count FROM research_posts p WHERE id = %s", (post_id,))
    if not rows:
        raise HTTPException(404, "Post not found")
    return _post_full(rows[0])


@router.post("/admin/posts", dependencies=[Depends(require_admin_token)])
def admin_create_post(payload: PostBody):
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    if len(title) > _MAX_TITLE:
        raise HTTPException(400, f"Title too long (max {_MAX_TITLE})")
    body = (payload.body or "")[:_MAX_BODY]
    summary = (payload.summary or "").strip()[:_MAX_SUMMARY] or None
    status = payload.status if payload.status in ("draft", "published") else "draft"
    slug = _unique_slug(_slugify(payload.slug or title))
    published_at = "NOW()" if status == "published" else "NULL"

    rows = _q(
        f"""
        INSERT INTO research_posts (slug, title, summary, body, tags, status, published_at)
        VALUES (%s, %s, %s, %s, %s, %s, {published_at})
        RETURNING id, slug
        """,
        (slug, title, summary, body, _clean_tags(payload.tags), status),
    )
    return {"ok": True, "id": rows[0]["id"], "slug": rows[0]["slug"]}


@router.put("/admin/posts/{post_id}", dependencies=[Depends(require_admin_token)])
def admin_update_post(post_id: int, payload: PostBody):
    existing = _q("SELECT * FROM research_posts WHERE id = %s", (post_id,))
    if not existing:
        raise HTTPException(404, "Post not found")
    cur = existing[0]

    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    if len(title) > _MAX_TITLE:
        raise HTTPException(400, f"Title too long (max {_MAX_TITLE})")
    body = (payload.body or "")[:_MAX_BODY]
    summary = (payload.summary or "").strip()[:_MAX_SUMMARY] or None
    status = payload.status if payload.status in ("draft", "published") else cur["status"]

    # Slug: honour an explicit override, else leave it stable (editing the title
    # of a live post must not break its URL / inbound links).
    if payload.slug:
        slug = _unique_slug(_slugify(payload.slug), exclude_id=post_id)
    else:
        slug = cur["slug"]

    # Stamp published_at on the first publish only; unpublishing clears it so the
    # next publish re-dates the post to the top of the feed.
    if status == "published" and cur["published_at"] is None:
        pub_clause = "published_at = NOW(),"
    elif status == "draft":
        pub_clause = "published_at = NULL,"
    else:
        pub_clause = ""

    rows = _q(
        f"""
        UPDATE research_posts
        SET title = %s, summary = %s, body = %s, tags = %s, status = %s, slug = %s,
            {pub_clause} updated_at = NOW()
        WHERE id = %s
        RETURNING id, slug
        """,
        (title, summary, body, _clean_tags(payload.tags), status, slug, post_id),
    )
    return {"ok": True, "id": rows[0]["id"], "slug": rows[0]["slug"]}


class StatusBody(BaseModel):
    status: str  # 'draft' | 'published'


@router.post("/admin/posts/{post_id}/status", dependencies=[Depends(require_admin_token)])
def admin_set_status(post_id: int, payload: StatusBody):
    """Flip publish state WITHOUT touching title/body/tags — so the quick
    publish/unpublish toggle can never clobber content (a full PUT must send
    every field; this endpoint sends none of them)."""
    if payload.status not in ("draft", "published"):
        raise HTTPException(400, "status must be 'draft' or 'published'")
    existing = _q("SELECT published_at FROM research_posts WHERE id = %s", (post_id,))
    if not existing:
        raise HTTPException(404, "Post not found")
    # Stamp published_at on the first publish only; unpublishing clears it so a
    # later re-publish re-dates the post to the top of the feed.
    if payload.status == "published":
        pub_clause = "published_at = NOW()," if existing[0]["published_at"] is None else ""
    else:
        pub_clause = "published_at = NULL,"
    rows = _q(
        f"UPDATE research_posts SET status = %s, {pub_clause} updated_at = NOW() "
        "WHERE id = %s RETURNING id, slug, status",
        (payload.status, post_id),
    )
    return {"ok": True, "id": rows[0]["id"], "slug": rows[0]["slug"], "status": rows[0]["status"]}


@router.delete("/admin/posts/{post_id}", dependencies=[Depends(require_admin_token)])
def admin_delete_post(post_id: int):
    rows = _q("DELETE FROM research_posts WHERE id = %s RETURNING id", (post_id,))
    if not rows:
        raise HTTPException(404, "Post not found")
    return {"ok": True}


# ── Admin: comment moderation ─────────────────────────────────────────────────
@router.get("/admin/comments", dependencies=[Depends(require_admin_token)])
def admin_list_comments(status: str = "pending"):
    if status not in ("pending", "approved", "rejected", "all"):
        raise HTTPException(400, "Invalid status filter")
    where = "" if status == "all" else "WHERE c.status = %s"
    params = () if status == "all" else (status,)
    rows = _q(
        f"""
        SELECT c.id, c.post_id, c.author, c.email, c.body, c.status, c.created_at,
               p.slug AS post_slug, p.title AS post_title
        FROM research_comments c
        JOIN research_posts p ON p.id = c.post_id
        {where}
        ORDER BY c.created_at DESC
        """,
        params,
    )
    return {
        "comments": [
            {
                "id": r["id"],
                "post_id": r["post_id"],
                "post_slug": r["post_slug"],
                "post_title": r["post_title"],
                "author": r["author"],
                "email": r["email"],
                "body": r["body"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    }


class ModerateBody(BaseModel):
    action: str  # 'approve' | 'reject'


@router.post("/admin/comments/{comment_id}/moderate", dependencies=[Depends(require_admin_token)])
def admin_moderate_comment(comment_id: int, payload: ModerateBody):
    if payload.action == "approve":
        rows = _q(
            "UPDATE research_comments SET status = 'approved', approved_at = NOW() "
            "WHERE id = %s RETURNING id",
            (comment_id,),
        )
    elif payload.action == "reject":
        rows = _q(
            "UPDATE research_comments SET status = 'rejected', approved_at = NULL "
            "WHERE id = %s RETURNING id",
            (comment_id,),
        )
    else:
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    if not rows:
        raise HTTPException(404, "Comment not found")
    return {"ok": True}


@router.delete("/admin/comments/{comment_id}", dependencies=[Depends(require_admin_token)])
def admin_delete_comment(comment_id: int):
    rows = _q("DELETE FROM research_comments WHERE id = %s RETURNING id", (comment_id,))
    if not rows:
        raise HTTPException(404, "Comment not found")
    return {"ok": True}


# ── Sitemap helper (imported by main.sitemap_xml) ─────────────────────────────
def published_slugs() -> list[dict]:
    """(slug, updated_at) for published posts — feeds the sitemap."""
    return _q(
        "SELECT slug, updated_at FROM research_posts WHERE status = 'published' "
        "ORDER BY published_at DESC NULLS LAST"
    )
