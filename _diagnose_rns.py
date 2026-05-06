"""Diagnose why Tier C stories don't appear in the RNS feed."""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))
import psycopg2
import psycopg2.extras

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "host": os.environ.get("DB_HOST", ""),
    "port": os.environ.get("DB_PORT", "5432"),
    "sslmode": "require",
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# 1. Check Tier C stories in the last 72 hours
cur.execute("""
    SELECT COUNT(*) as cnt, MIN(score) as min_score, MAX(score) as max_score, ROUND(AVG(score)::numeric, 1) as avg_score
    FROM rns_announcements
    WHERE tier = 'C'
      AND published_at >= NOW() - INTERVAL '72 hours'
""")
print("=== Tier C stats (72h) ===")
print(dict(cur.fetchone()))

# 2. Check all tiers count in last 72 hours
cur.execute("""
    SELECT tier, COUNT(*) as cnt, MIN(score) as min_s, MAX(score) as max_s
    FROM rns_announcements
    WHERE published_at >= NOW() - INTERVAL '72 hours'
    GROUP BY tier
    ORDER BY tier
""")
print("\n=== All tiers (72h) ===")
for r in cur.fetchall():
    print(" ", dict(r))

# 3. Check if any stories have score = 0 or NULL
cur.execute("""
    SELECT COUNT(*) FROM rns_announcements
    WHERE published_at >= NOW() - INTERVAL '72 hours'
      AND (score IS NULL OR score = 0)
""")
print("\n=== Stories with score=0 or NULL ===")
row = cur.fetchone()
print(row["count"] if row else 0)

# 4. Check the most recent 10 Tier C stories
cur.execute("""
    SELECT id, published_at, ticker, LEFT(headline, 60) as headline, score, tier
    FROM rns_announcements
    WHERE tier = 'C'
      AND published_at >= NOW() - INTERVAL '72 hours'
    ORDER BY published_at DESC
    LIMIT 10
""")
print("\n=== Recent Tier C stories ===")
for r in cur.fetchall():
    print(" ", dict(r))

# 5. Check total stories in last 72 hours
cur.execute("""
    SELECT COUNT(*) FROM rns_announcements
    WHERE published_at >= NOW() - INTERVAL '72 hours'
""")
print("\n=== Total stories (72h) ===")
row = cur.fetchone()
print(row["count"] if row else 0)

# 6. Simulate the exact backend query with min_score=0
cur.execute("""
    SELECT COUNT(*) as cnt
    FROM rns_announcements r
    LEFT JOIN ttm_financials f ON f.company_symbol = r.symbol
    WHERE r.published_at >= NOW() - INTERVAL '72 hours'
      AND r.score >= 0
""")
print("\n=== Backend query with min_score=0 (72h) ===")
print(dict(cur.fetchone()))

# 7. Simulate the exact backend query with min_score=0, grouped by tier
cur.execute("""
    SELECT r.tier, COUNT(*) as cnt
    FROM rns_announcements r
    LEFT JOIN ttm_financials f ON f.company_symbol = r.symbol
    WHERE r.published_at >= NOW() - INTERVAL '72 hours'
      AND r.score >= 0
    GROUP BY r.tier
    ORDER BY r.tier
""")
print("\n=== Backend query with min_score=0, by tier ===")
for r in cur.fetchall():
    print(" ", dict(r))

# 8. Check if there are Tier C stories with score < 20 (the default min_score)
cur.execute("""
    SELECT COUNT(*) as cnt
    FROM rns_announcements
    WHERE tier = 'C'
      AND published_at >= NOW() - INTERVAL '72 hours'
      AND score < 20
""")
print("\n=== Tier C stories with score < 20 ===")
print(cur.fetchone()[0])

conn.close()
