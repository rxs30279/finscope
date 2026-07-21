"""One-off seeder: copy the Resend segment's contacts into the `subscribers` table.

Run once, immediately before cutting subscribers.py over to Postgres (migration
019). After that the table is the source of truth and this script has no further
purpose — it is kept only so the migration is reproducible and auditable.

This module deliberately carries its OWN Resend client rather than importing
subscribers.py: that module is being rewritten to read Postgres in the same
commit, so importing it here would make the seeder's behaviour depend on which
side of the rewrite you are standing on.

Unsubscribed contacts are copied too, with the flag preserved. Dropping them
would silently re-subscribe anyone who had opted out — the single worst outcome
available in this migration, and one that is invisible until someone who
unsubscribed receives a digest.

What this does NOT copy: Resend's account-level suppression list (hard bounces,
spam complaints). Resend exposes no public endpoint for it, and it keeps
applying for as long as Resend is the sender — so nothing is lost today. Those
addresses land in `bounced_at` once the SES event pipeline is live; until then
a hard-bounced address that was never marked unsubscribed in the segment (e.g.
info@bioseekers.com) copies across as active and simply keeps bouncing, exactly
as it does now.

Usage:
    python migrate_subscribers.py --dry-run     # report only, no writes
    python migrate_subscribers.py               # insert

Idempotent: re-running updates nothing it has already written (ON CONFLICT DO
NOTHING), so a partial run can be repeated safely.

Env: RESEND_API_KEY, RESEND_SEGMENT_ID, DB_* (all from backend/.env)
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(_SCRIPT_DIR, ".env"))

from db import connection, query


_RESEND_BASE = "https://api.resend.com"


def _resend_get(path: str) -> dict:
    """GET against Resend, same raw-urllib pattern as the module being replaced."""
    api_key = os.environ["RESEND_API_KEY"]
    req = urllib.request.Request(
        f"{_RESEND_BASE}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Resend sits behind Cloudflare; the default urllib UA trips bot
            # protection (CF 1010).
            "User-Agent": "FINScope-Migrate/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend HTTP {e.code}: {raw}") from e


def fetch_all_contacts() -> list[dict]:
    """Every contact in the segment, unsubscribed ones included.

    Note the difference from subscribers.list_active_contacts(), which filters
    unsubscribed out — here we want them, so the opt-out survives the move.
    """
    sid = os.environ["RESEND_SEGMENT_ID"]
    out: list[dict] = []
    after: str | None = None
    while True:
        path = f"/segments/{sid}/contacts?limit=100"
        if after:
            path += f"&after={urllib.parse.quote(after)}"
        payload = _resend_get(path)
        data = payload.get("data") or []
        out.extend(data)
        if not payload.get("has_more") or not data:
            break
        after = data[-1].get("id")
        if not after:
            break
    return out


def _parse_ts(value):
    """Resend timestamps are ISO 8601, sometimes Z-suffixed. Normalise to aware
    UTC; None if absent or unparseable so the column default takes over."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_rows(contacts: list[dict]) -> list[dict]:
    """Flatten Resend contacts into `subscribers` rows, skipping blanks and
    de-duplicating on email (the segment can in principle carry the same address
    twice; the table's primary key cannot)."""
    seen: set[str] = set()
    rows: list[dict] = []
    for c in contacts:
        email = (c.get("email") or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        unsubscribed = bool(c.get("unsubscribed"))
        created = _parse_ts(c.get("created_at"))
        rows.append({
            "email": email,
            "unsubscribed": unsubscribed,
            "source": "resend_migration",
            # Preserve signup order — the scarcity counter and the digest send
            # list both read oldest-first.
            "created_at": created or datetime.now(timezone.utc),
            # Resend does not expose *when* a contact unsubscribed, so stamp the
            # migration time rather than inventing one; the flag is what matters.
            "unsubscribed_at": datetime.now(timezone.utc) if unsubscribed else None,
        })
    return rows


def insert_rows(rows: list[dict]) -> int:
    """Insert rows, leaving any address already present untouched. Returns the
    number actually written."""
    if not rows:
        return 0
    written = 0
    with connection() as conn:
        cur = conn.cursor()
        for row in rows:
            cur.execute(
                """
                INSERT INTO subscribers
                    (email, unsubscribed, source, created_at, unsubscribed_at)
                VALUES
                    (%(email)s, %(unsubscribed)s, %(source)s, %(created_at)s,
                     %(unsubscribed_at)s)
                ON CONFLICT (email) DO NOTHING
                """,
                row,
            )
            written += cur.rowcount
        conn.commit()
    return written


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]

    for var in ("RESEND_API_KEY", "RESEND_SEGMENT_ID"):
        if not os.environ.get(var):
            print(f"[migrate] {var} not set — aborting")
            return 1

    print(f"[migrate] fetching Resend segment contacts ({'DRY RUN' if dry_run else 'LIVE'})")
    try:
        contacts = fetch_all_contacts()
    except Exception as e:
        print(f"[migrate] FAILED to list Resend contacts: {type(e).__name__}: {e}")
        return 1

    rows = to_rows(contacts)
    active = sum(1 for r in rows if not r["unsubscribed"])
    unsub = len(rows) - active
    print(f"[migrate] Resend: {len(contacts)} contacts → {len(rows)} unique "
          f"({active} active, {unsub} unsubscribed)")

    existing = query("SELECT COUNT(*) AS n FROM subscribers")[0]["n"]
    print(f"[migrate] Postgres subscribers before: {existing}")

    if dry_run:
        preview = ", ".join(r["email"] for r in rows[:5])
        print(f"[migrate] DRY RUN: would insert up to {len(rows)} rows "
              f"(existing addresses skipped). First few: {preview}")
        print("[migrate] DRY RUN: no rows written")
        return 0

    written = insert_rows(rows)

    after = query("SELECT COUNT(*) AS n FROM subscribers")[0]["n"]
    after_active = query(
        "SELECT COUNT(*) AS n FROM subscribers WHERE NOT unsubscribed"
    )[0]["n"]
    print(f"[migrate] inserted {written} new rows; subscribers now {after} "
          f"({after_active} active)")

    # The number that must match is ACTIVE contacts — that is what the digest
    # sends to and what the scarcity counter displays.
    if after_active != active:
        print(f"[migrate] WARNING: active count mismatch — Resend {active}, "
              f"Postgres {after_active}. Investigate before cutting over.")
        return 1

    print("[migrate] active counts match — safe to cut over")
    return 0


if __name__ == "__main__":
    sys.exit(main())
