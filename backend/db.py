"""Shared PostgreSQL connection pool + query helpers.

Single source of truth for DB access across every router. This module imports
NOTHING from application modules, so any module can import it without the
circular-import risk that originally forced each one to carry its own private
`ThreadedConnectionPool` (main, prices, news, analysts, dividends, shorts, rns —
seven pools, only main's query() had reconnect-on-drop retry).

Public API:
    DB_CONFIG          — psycopg2 connection kwargs
    get_pool()         — lazily-built process-wide ThreadedConnectionPool
    query(sql, params) — read-only, returns list[dict], retries once on a
                         dropped connection (SSL/idle timeout)
    connection()       — context manager yielding a pooled raw connection for
                         writes / custom cursors (caller manages commit)
"""
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}

# One pool for the whole process. Sized to cover peak concurrent DB access
# across all routers combined — the seven old pools were 5-10 each, but only a
# handful of connections are ever borrowed at once (endpoints getconn/putconn
# quickly; the ThreadPoolExecutors in market/main hit yfinance, not the DB).
# Override via env if a load profile ever needs it.
_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "20"))

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(_POOL_MIN, _POOL_MAX, **DB_CONFIG)
    return _pool


def query(sql, params=None):
    """Run a read-only query and return list[dict].

    Retries once if the pooled connection was dropped underneath us (Supabase
    SSL/idle timeout surfaces as OperationalError) — the stale connection is
    discarded and a fresh one is used.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    except psycopg2.OperationalError:
        pool.putconn(conn, close=True)
        conn = pool.getconn()
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        pool.putconn(conn)


@contextmanager
def connection():
    """Borrow a raw connection from the shared pool (for writes / custom
    cursors) and return it to the pool on exit. The caller owns commit/rollback.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)
