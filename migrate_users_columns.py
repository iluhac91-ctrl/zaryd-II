import sqlite3
from pathlib import Path

if Path("/data").exists():
    db_path = "/data/station.db"
else:
    db_path = "station.db"

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("PRAGMA table_info(users)")
cols = [row[1] for row in cur.fetchall()]

if "payment_token" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN payment_token TEXT")
    print("added payment_token")

if "card_last_four" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN card_last_four TEXT")
    print("added card_last_four")

if "card_type" not in cols:
    cur.execute("ALTER TABLE users ADD COLUMN card_type TEXT")
    print("added card_type")

conn.commit()
conn.close()
print("done")
