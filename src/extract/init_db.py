import sqlite3

def get_connection(db_path="data/database/pipeline_meta.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")  # SQLite disables FK enforcement by default!
    conn.row_factory = sqlite3.Row  # lets you access columns by name
    return conn

with open("src/extract/schemas.sql", "r") as f:
	SCHEMA = f.read()

conn = get_connection()
conn.executescript(SCHEMA)
conn.commit()
conn.close()