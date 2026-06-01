"""Apply a SQL migration file against the configured Supabase database.

Usage:
    python run_migration.py migrations/001_company_active_flag.sql

Reads DB_* connection settings from backend/.env (same as prices.py).
Migrations are written to be idempotent (IF NOT EXISTS), so re-running is safe.
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))


def main(path: str):
    sql_path = path if os.path.isabs(path) else os.path.join(_SCRIPT_DIR, path)
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

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
        cur.execute(sql)
        conn.commit()
        print(f"Migration applied: {os.path.basename(sql_path)}")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
