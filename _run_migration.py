import os, psycopg2
from dotenv import load_dotenv

load_dotenv("backend/.env")
conn = psycopg2.connect(
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ["DB_HOST"],
    port=os.environ["DB_PORT"],
    sslmode="require",
)
cur = conn.cursor()
sql = open("backend/breakout_schema.sql").read()
cur.execute(sql)
conn.commit()
print("Migration complete")
conn.close()
