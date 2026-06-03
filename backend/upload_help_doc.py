"""Upload (upsert) a document into the app_documents table.

Used to store the Alpha Move AI user manual in Postgres so the API can serve it
from /api/help-doc (see backend/main.py). Run after applying migration 003.

Usage:
    python upload_help_doc.py                       # defaults to the user manual
    python upload_help_doc.py path\\to\\file.docx user-manual

Reads DB_* connection settings from backend/.env (same as run_migration.py).
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

# The manual lives at the repo root, one level up from backend/.
_DEFAULT_PATH = os.path.join(
    os.path.dirname(_SCRIPT_DIR), "Alpha_Move_AI_User_Manual.docx"
)
_DEFAULT_SLUG = "user-manual"
_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def main(path: str, slug: str):
    with open(path, "rb") as f:
        data = f.read()

    filename = os.path.basename(path)
    content_type = _DOCX_MIME if filename.lower().endswith(".docx") else (
        "application/octet-stream"
    )

    conn = psycopg2.connect(
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        sslmode="require",
    )
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO app_documents (slug, filename, content_type, data, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (slug) DO UPDATE SET
                filename     = EXCLUDED.filename,
                content_type = EXCLUDED.content_type,
                data         = EXCLUDED.data,
                updated_at   = NOW()
            """,
            (slug, filename, content_type, psycopg2.Binary(data)),
        )
        conn.commit()
        print(f"Uploaded '{filename}' ({len(data):,} bytes) as slug '{slug}'.")
    finally:
        conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_PATH
    slug = sys.argv[2] if len(sys.argv) > 2 else _DEFAULT_SLUG
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        sys.exit(1)
    main(path, slug)
