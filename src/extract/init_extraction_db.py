"""Initialize missing local storage, or explicitly reset the extraction state."""

import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

import extract.extraction_db_helper as db

DB_PATH = "data/database/extraction.db"
SCHEMA_PATH = "src/extract/extraction_schemas.sql"
PLAYERS_DIR = "data/raw/players"
MASTERIES_DIR = "data/raw/masteries"
COMPACTED_DIR = "data/compacted"
QUARANTINE_DIR = "data/quarantine"


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


def reconcile_raw_files() -> int:
    """Quarantine unreferenced Parquet files before collection, preserving their layout."""
    referenced_paths = {Path(path).resolve() for path in db.get_raw_paths_for_reconciliation()}
    quarantine_path = Path(QUARANTINE_DIR).resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    moved = 0
    for directory in (PLAYERS_DIR, MASTERIES_DIR):
        raw_root = Path(directory).resolve()
        for raw_file in raw_root.rglob("*.parquet"):
            resolved_path = raw_file.resolve()
            if resolved_path in referenced_paths:
                continue
            resolved_path.relative_to(raw_root)
            destination = (quarantine_path / raw_root.name / raw_file.relative_to(raw_root)).resolve()
            destination.relative_to(quarantine_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw_file.rename(destination)
            moved += 1
    if moved:
        logger.warning(f"Quarantined {moved} untracked raw Parquet files under {quarantine_path}.")
    else:
        logger.info("Raw-file reconciliation completed: no untracked Parquet files.")
    return moved


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
