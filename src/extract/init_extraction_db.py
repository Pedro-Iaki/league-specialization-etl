"""Initialize missing local storage, or explicitly reset the extraction state."""

import os
import shutil
import sqlite3
import time

from loguru import logger

DB_PATH = "data/database/extraction.db"
SCHEMA_PATH = "src/extract/extraction_schemas.sql"
PLAYERS_DIR = "data/raw/players"
MASTERIES_DIR = "data/raw/masteries"
COMPACTED_DIR = "data/compacted"


def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def db_exists():
    return all(os.path.exists(path) for path in (DB_PATH, PLAYERS_DIR, MASTERIES_DIR, COMPACTED_DIR))


def initialize_database():
    """Create missing folders and a new ledger without clearing existing data."""
    for directory in (os.path.dirname(DB_PATH), PLAYERS_DIR, MASTERIES_DIR, COMPACTED_DIR):
        os.makedirs(directory, exist_ok=True)
    if os.path.exists(DB_PATH):
        return
    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()

    conn = get_connection(DB_PATH)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    logger.info("Local extraction database initialized.")


def reset_database():
    """Explicitly back up the ledger, clear local files, and initialize fresh state."""
    if os.path.exists(DB_PATH):
        os.rename(DB_PATH, f"{DB_PATH}_{int(time.time())}.bak")

    clear_raw_and_compacted_data()
    initialize_database()
    logger.info("Database and raw directories reset successfully.")


def clear_raw_and_compacted_data():
    """Delete all extracted raw data and compacted outputs without touching the database."""
    clear_directory_contents(PLAYERS_DIR)
    clear_directory_contents(MASTERIES_DIR)
    clear_directory_contents(COMPACTED_DIR)


def clear_directory_contents(dir_path: str):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        return

    for entry in os.scandir(dir_path):
        try:
            if entry.is_file() or entry.is_symlink():
                os.remove(entry.path)
            elif entry.is_dir():
                shutil.rmtree(entry.path)
        except RuntimeError as e:
            logger.error(f"Failed to delete {entry.path}. Reason: {e}")
