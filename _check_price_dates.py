"""Check how many stocks have old price data in the database."""

import psycopg2
import psycopg2.extras
from datetime import date, timedelta
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))

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

# Get latest date for each symbol
cur.execute("""
    SELECT symbol, MAX(date) AS latest_date
    FROM price_history
    GROUP BY symbol
    ORDER BY latest_date ASC
""")

rows = cur.fetchall()

today = date.today()
print(f"Today's date: {today}")
print(f"Total symbols with price data: {len(rows)}")
print("\n" + "=" * 80)

# Categorize by age
very_old = []  # > 1 year old
old = []  # 30 days to 1 year
recent = []  # < 30 days

for row in rows:
    symbol = row["symbol"]
    latest = row["latest_date"]
    days_old = (today - latest).days

    if days_old > 365:
        very_old.append((symbol, latest, days_old))
    elif days_old > 30:
        old.append((symbol, latest, days_old))
    else:
        recent.append((symbol, latest, days_old))

print(f"\n📊 SUMMARY:")
print(f"  Very old (>1 year):     {len(very_old)} stocks")
print(f"  Old (30 days - 1 year): {len(old)} stocks")
print(f"  Recent (<30 days):      {len(recent)} stocks")

if very_old:
    print(f"\n⚠️  VERY OLD DATA (>1 year):")
    for symbol, latest, days in very_old[:20]:  # Show first 20
        print(f"  {symbol:12s} last updated: {latest} ({days} days ago)")
    if len(very_old) > 20:
        print(f"  ... and {len(very_old) - 20} more")

if old:
    print(f"\n⚠️  OLD DATA (30 days - 1 year):")
    for symbol, latest, days in old[:10]:  # Show first 10
        print(f"  {symbol:12s} last updated: {latest} ({days} days ago)")
    if len(old) > 10:
        print(f"  ... and {len(old) - 10} more")

conn.close()
