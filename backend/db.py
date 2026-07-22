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
    advisory_lock(key) — context manager for a cross-process mutex, used by the
                         cron entry points to stop overlapping runs
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

# Port used *only* by advisory_lock(). Everything else goes through Supabase's
# transaction-mode pooler (6543), where a session-level advisory lock is worse
# than useless, in two compounding ways. Consecutive statements can be routed to
# different backends, so pg_try_advisory_lock returns true to every caller and
# excludes nobody. And the lock it takes outlives the client: the pooler keeps
# that backend alive, so the lock leaks and is held forever by an idle session
# no disconnect will clear. Both were observed against prod on 6543 — two
# concurrent holders each got the lock, and one leaked onto backend pid 2993712
# until it was terminated by hand.
#
# NEVER take an advisory lock over the pooled connection. The session-mode
# pooler pins one backend per connection, which is the property a lock needs.
_LOCK_PORT = os.environ.get("DB_SESSION_PORT", "5432")

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


@contextmanager
def advisory_lock(key: int):
    """Cross-process mutex: yields True if this process took the lock, False if
    another process already holds it. Never blocks — the caller decides whether
    losing the race is fatal or just a no-op exit.

    Opens its own connection on `_LOCK_PORT` rather than borrowing from the pool,
    for two reasons. The pool speaks to the transaction-mode pooler, where these
    locks do not work at all (see _LOCK_PORT). And an advisory lock is bound to
    the session, so a pooled connection handed back mid-run would either release
    the lock early or carry it into an unrelated caller.

    Closing the connection on exit releases the lock. Because that release is
    server-side, it also covers a crashed or killed process — no stale lock can
    outlive the run that took it, so there is no timeout or reaper to maintain.

    Fails *open*: if the lock connection cannot be established, the caller is
    told it holds the lock. Duplicated work is a cost; a pipeline that refuses
    to run because it could not reach the session pooler is an outage.
    """
    try:
        conn = psycopg2.connect(**dict(DB_CONFIG, port=_LOCK_PORT))
    except Exception as e:
        print(f"[db] advisory lock unavailable ({type(e).__name__}: {e}) — proceeding unlocked")
        yield True
        return
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
        (acquired,) = cur.fetchone()
        yield bool(acquired)
    finally:
        conn.close()
