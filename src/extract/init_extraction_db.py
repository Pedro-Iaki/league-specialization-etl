"""
Initializes the local database and clears the raw data directories for players and masteries.
This script should be run before starting a new data extraction pipeline to ensure a clean slate.
"""

import os
import shutil
import sqlite3

from loguru import logger

DB_PATH = "data/database/extraction.db"
SCHEMA_PATH = "src/extract/extraction_schemas.sql"
PLAYERS_DIR = "data/raw/players"
MASTERIES_DIR = "data/raw/masteries"


def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def db_exists():
    return (
        os.path.exists(DB_PATH)
        and os.path.exists(PLAYERS_DIR)
        and os.path.exists(MASTERIES_DIR)
    )


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


def reset_database_and_directories():
    """Executes the cleanup and schema initialization."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    clear_directory_contents(PLAYERS_DIR)
    clear_directory_contents(MASTERIES_DIR)

    with open(SCHEMA_PATH, "r") as f:
        schema = f.read()

    conn = get_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    logger.info("Database and raw directories reset successfully.")
