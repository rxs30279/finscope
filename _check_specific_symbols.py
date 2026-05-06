"""Check the specific symbols mentioned in the Render error logs."""

import psycopg2
import psycopg2.extras
from datetime import date
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

# The specific symbols from the error
ERROR_SYMBOLS = ["WVIA.L", "TBTG.L", "VIC.L", "TMIP.L", "THX.L"]

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print(f"Today's date: {date.today()}\n")
print("=" * 80)

for symbol in ERROR_SYMBOLS:
    print(f"\n🔍 Checking {symbol}:")

    # Check if symbol exists in price_history
    cur.execute(
        """
        SELECT MIN(date) AS earliest, MAX(date) AS latest, COUNT(*) AS row_count
        FROM price_history
        WHERE symbol = %s
        """,
        (symbol,),
    )
    result = cur.fetchone()

    if result and result["row_count"] > 0:
        earliest = result["earliest"]
        latest = result["latest"]
        count = result["row_count"]
        days_old = (date.today() - latest).days

        print(f"  ✓ Found in database")
        print(f"  📅 Earliest date: {earliest}")
        print(f"  📅 Latest date:   {latest} ({days_old} days ago)")
        print(f"  📊 Total rows:    {count}")
    else:
        print(f"  ✗ NOT found in price_history table")

    # Check if in company_metadata
    cur.execute(
        "SELECT symbol, name FROM company_metadata WHERE symbol = %s", (symbol,)
    )
    meta = cur.fetchone()
    if meta:
        print(f"  📋 In metadata:   YES - {meta['name']}")
    else:
        print(f"  📋 In metadata:   NO")

conn.close()
