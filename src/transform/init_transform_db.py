#a code similar to init_extraction_db but dedicated to creating the transform db (functionally the same, only change the parameter for now, solve issues later)
#wont matter regardless once we use an orchestrator
"""
Initializes the local transformation database and clears the raw data directories for players and masteries.
This script should be run before starting a new data extraction pipeline to ensure a clean slate.
"""

import sqlite3
import os
import shutil
from loguru import logger

DB_PATH = "data/database/transform.db"
SCHEMA_PATH = "src/transform/transform_schemas.sql"
CLEANED_DIR = "data/cleaned/"

def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
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

def reset_database_and_directories():
    """Executes the cleanup and schema initialization."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        
    clear_directory_contents(CLEANED_DIR)

    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()

    conn = get_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    logger.info("Database and raw directories reset successfully.")

if __name__ == "__main__":
    reset_database_and_directories()