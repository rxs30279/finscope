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
Beyond the honeypot: a per-IP rate limit and a per-post pending cap stop a
script flooding the queue, and each accepted comment emails the owner (via the
same Resend relay feedback.py uses) so the queue actually gets worked.

DB access goes through main.query (imported lazily to dodge the import cycle:
main.py registers this router before query() is defined). query() runs with
autocommit and always fetchall()s, so every write must end in RETURNING.

Migration: migrations/010_research.sql
"""
import re
import sys
import os
import html
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from admin_auth import require_admin_token
from request_utils import client_ip as _client_ip, SlidingWindowLimiter

router = APIRouter(prefix="/api/research", tags=["research"])

_MAX_TITLE = 200
_MAX_SUMMARY = 500
_MAX_BODY = 100_000
_MAX_IMAGE = 500
_MAX_COMMENT = 4000
_MAX_AUTHOR = 80
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

# Comment flood control (the honeypot only stops dumb bots): a per-IP sliding
# window on submissions (keyed on the proxy-verified IP — see
# request_utils.client_ip), plus a cap on how many pending comments one post
# can accumulate before we stop accepting more.
_RATE_LIMIT = 3           # accepted submissions …
_RATE_WINDOW = 60         # … per IP per this many seconds
_MAX_PENDING_PER_POST = 50
_comment_limiter = SlidingWindowLimiter(_RATE_LIMIT, _RATE_WINDOW)


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


def _notify_new_comment(post_title: str, post_slug: str, author: str,
                        email: str, body: str) -> None:
    """Email the owner that a comment is waiting in the moderation queue.

    Runs as a BackgroundTask after the response is sent, and swallows every
    failure — an email-provider outage must never affect (or reveal anything
    to) the commenter. Reuses feedback.py's recipient resolution.
    """
    try:
        from emailer import send_email
        from feedback import _feedback_to  # same recipient as the contact form
        base = (os.environ.get("PUBLIC_BASE_URL") or "https://app.alphamoveai.co.uk").rstrip("/")
        admin_url = f"{base}/research/admin"
        text = (
            f"New comment awaiting review on “{post_title}”\n"
            f"({base}/research/{post_slug})\n\n"
            f"From: {author}{f' <{email}>' if email else ''}\n\n"
            f"{body}\n\n"
            f"Review: {admin_url}"
        )
        html_body = (
            '<div style="font-family:monospace;font-size:14px;color:#111;">'
            f'<p>New comment awaiting review on '
            f'<a href="{html.escape(base)}/research/{html.escape(post_slug)}">'
            f'{html.escape(post_title)}</a></p>'
            f'<p style="color:#666;">From: {html.escape(author)}'
            f'{" &lt;" + html.escape(email) + "&gt;" if email else ""}</p>'
            f'<p style="white-space:pre-wrap;line-height:1.6;border-left:3px solid #ccc;'
            f'padding-left:12px;">{html.escape(body)}</p>'
            f'<p><a href="{html.escape(admin_url)}">Open the moderation queue</a></p>'
            '</div>'
        )
        send_email(
            to=_feedback_to(),
            subject=f"New research comment — {post_title}",
            text=text,
            html=html_body,
            from_addr=os.environ.get("DIGEST_FROM",
                                     "Alpha Move AI <digest@alphamoveai.co.uk>"),
        )
    except Exception:
        pass  # never let notification failures surface anywhere


# ── Serialisation ─────────────────────────────────────────────────────────────
def _post_summary(r: dict) -> dict:
    """List-card shape: no body, plus the approved-comment tally."""
    return {
        "id": r["id"],
        "slug": r["slug"],
        "title": r["title"],
        "summary": r["summary"],
        "image": r.get("image"),
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
def submit_comment(slug: str, payload: CommentBody, request: Request,
                   background: BackgroundTasks):
    if (payload.website or "").strip():
        return {"ok": True, "pending": True}  # honeypot — silently discard

    if not _comment_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Too many comments — please wait a minute and try again")

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
        """
        SELECT p.id, p.title, (
            SELECT COUNT(*) FROM research_comments c
            WHERE c.post_id = p.id AND c.status = 'pending'
        ) AS pending_count
        FROM research_posts p WHERE p.slug = %s AND p.status = 'published'
        """,
        (slug,),
    )
    if not rows:
        raise HTTPException(404, "Post not found")
    post = rows[0]
    # Flood backstop: once a post has this many unreviewed comments something is
    # spamming it — stop accepting until the queue is worked.
    if int(post["pending_count"] or 0) >= _MAX_PENDING_PER_POST:
        raise HTTPException(429, "This post has too many comments awaiting review — try again later")

    _q(
        """
        INSERT INTO research_comments (post_id, author, email, body)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (post["id"], author, email or None, body),
    )
    # Tell the owner there's something in the queue — after the response, and
    # best-effort (see _notify_new_comment).
    background.add_task(_notify_new_comment, post["title"], slug, author, email, body)
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
    image: Optional[str] = None           # hero/OG image URL (site-relative or absolute)


def _validated_body_and_image(payload: PostBody) -> tuple[str, Optional[str]]:
    """Shared create/update checks. Over-long content is REJECTED, not
    truncated — silently chopping the tail off a long article and reporting
    'Saved.' loses work."""
    body = payload.body or ""
    if len(body) > _MAX_BODY:
        raise HTTPException(
            400, f"Body too long ({len(body):,} chars; max {_MAX_BODY:,}) — split the post"
        )
    image = (payload.image or "").strip() or None
    if image and len(image) > _MAX_IMAGE:
        raise HTTPException(400, f"Image URL too long (max {_MAX_IMAGE})")
    return body, image


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
    body, image = _validated_body_and_image(payload)
    summary = (payload.summary or "").strip()[:_MAX_SUMMARY] or None
    status = payload.status if payload.status in ("draft", "published") else "draft"
    slug = _unique_slug(_slugify(payload.slug or title))
    published_at = "NOW()" if status == "published" else "NULL"

    rows = _q(
        f"""
        INSERT INTO research_posts (slug, title, summary, body, tags, status, image, published_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, {published_at})
        RETURNING id, slug
        """,
        (slug, title, summary, body, _clean_tags(payload.tags), status, image),
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
    body, image = _validated_body_and_image(payload)
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
        SET title = %s, summary = %s, body = %s, tags = %s, status = %s, slug = %s, image = %s,
            {pub_clause} updated_at = NOW()
        WHERE id = %s
        RETURNING id, slug
        """,
        (title, summary, body, _clean_tags(payload.tags), status, slug, image, post_id),
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


# ── Images ────────────────────────────────────────────────────────────────────
# In-browser image upload for post bodies (paste/drag in the admin editor) and
# share images — so publishing a post with pictures needs no git commit/deploy.
#
# Storage is a plain directory. On Dokploy set RESEARCH_IMAGE_DIR to a path on
# the persistent volume (e.g. /data/research_images — same pattern as
# MARKET_SNAPSHOT_DIR) or uploads vanish on redeploy. The dev default keeps
# them next to the code.
#
# Upload is a raw request body (not multipart — avoids the python-multipart
# dependency): the editor POSTs the file bytes with ?filename=<original name>.
# The stored name is <slugified-stem>-<content-hash>.<ext with ext sniffed
# from magic bytes (never trusted from the client), so names are unique,
# path-safe, and immutable → the GET can cache forever.
_IMAGE_DIR = os.environ.get("RESEARCH_IMAGE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "research_images"
)
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_IMAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.(png|jpg|gif|webp)$")
_IMAGE_MEDIA = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _sniff_image(data: bytes) -> Optional[str]:
    """File extension from magic bytes — or None if it isn't a supported image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("/images", dependencies=[Depends(require_admin_token)])
async def upload_image(request: Request, filename: str = ""):
    data = await request.body()
    if not data:
        raise HTTPException(400, "Empty upload")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(400, f"Image too large (max {_MAX_IMAGE_BYTES // (1024 * 1024)}MB)")
    ext = _sniff_image(data)
    if not ext:
        raise HTTPException(400, "Unsupported image type (png, jpg, gif or webp)")

    stem = _slugify(os.path.splitext(os.path.basename(filename or ""))[0])[:40]
    digest = hashlib.sha1(data).hexdigest()[:10]
    name = f"{stem}-{digest}.{ext}"  # content-addressed: re-uploads dedupe

    os.makedirs(_IMAGE_DIR, exist_ok=True)
    with open(os.path.join(_IMAGE_DIR, name), "wb") as f:
        f.write(data)
    return {"ok": True, "url": f"/api/research/images/{name}", "filename": name}


@router.get("/images/{name}")
def get_image(name: str):
    # Regex gate (lowercase alnum + ._-, sniffed extension) blocks any traversal.
    if not _IMAGE_NAME_RE.match(name):
        raise HTTPException(404, "Image not found")
    path = os.path.join(_IMAGE_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Image not found")
    return FileResponse(
        path,
        media_type=_IMAGE_MEDIA[name.rsplit(".", 1)[1]],
        # Names embed a content hash — a changed image gets a new URL, so this
        # can be cached forever by browsers (the Vercel edge won't cache /api).
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ── Sitemap helper (imported by main.sitemap_xml) ─────────────────────────────
def published_slugs() -> list[dict]:
    """(slug, updated_at) for published posts — feeds the sitemap."""
    return _q(
        "SELECT slug, updated_at FROM research_posts WHERE status = 'published' "
        "ORDER BY published_at DESC NULLS LAST"
    )
