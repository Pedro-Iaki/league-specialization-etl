"""
Initializes the local database and clears the raw data directories for players and masteries.
This script should be run before starting a new data extraction pipeline to ensure a clean slate."""


import sqlite3
import os
import shutil
from loguru import logger

def get_connection(db_path="data/database/pipeline_meta.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")  # SQLite disables FK enforcement by default!
    conn.row_factory = sqlite3.Row  # lets you access columns by name
    return conn

def clear_directory_contents(dir_path: str):
    if not os.path.exists(dir_path):
        return

    for entry in os.scandir(dir_path):
        try:
            if entry.is_file() or entry.is_symlink():
                os.remove(entry.path)
            elif entry.is_dir():
                shutil.rmtree(entry.path)
        except Exception as e:
            logger.error(f"Failed to delete {entry.path}. Reason: {e}")

with open("src/extract/schemas.sql", "r") as f:
    SCHEMA = f.read()

if os.path.exists("data/database/pipeline_meta.db"):
    os.remove("data/database/pipeline_meta.db")
    
clear_directory_contents("data/raw/players")
clear_directory_contents("data/raw/masteries")

conn = get_connection()
conn.executescript(SCHEMA)
conn.commit()
conn.close()