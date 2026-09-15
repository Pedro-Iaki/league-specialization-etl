import os
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env.local"
DEFAULT_FRESHNESS_MINUTES = 10080  # A Week

_SCHEMA = "src/load/player_registry_schema.sql"


def get_connection() -> psycopg.Connection:
    load_dotenv(ENV_PATH)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("Missing DATABASE_URL, check .env.local")
    return psycopg.connect(database_url)


def _normalize_row(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = ["puuid", "dataset", "first_loaded_at", "last_updated_at", "is_fresh"]
    return dict(zip(keys, row))


def ensure_schema(conn: psycopg.Connection | None = None) -> None:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        conn.execute(_SCHEMA)
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def upsert_players(puuids: list[str], dataset: str, conn: psycopg.Connection | None = None) -> int:
    """Insert new players or refresh last_updated_at for players already registered."""
    if not puuids:
        return 0

    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        ensure_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO player_state_registry (puuid, dataset)
            SELECT unnest(%s::text[]), %s
            ON CONFLICT (puuid, dataset) DO UPDATE SET
                last_updated_at = now()
            """,
            (puuids, dataset),
        )
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()


def get_stale_players(
    threshold_minutes: int = DEFAULT_FRESHNESS_MINUTES,
    conn: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                puuid,
                dataset,
                first_loaded_at,
                last_updated_at
            FROM player_state_registry
            WHERE (now() - last_updated_at) >= (%s * interval '1 minute')
            ORDER BY last_updated_at ASC
            """,
            (threshold_minutes, threshold_minutes),
        ).fetchall()
        return [normalized for row in rows if (normalized := _normalize_row(row)) is not None]
    finally:
        if own_conn:
            conn.close()


def get_player_state(
    puuid: str,
    threshold_minutes: int = DEFAULT_FRESHNESS_MINUTES,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return a single player's registry row, including a computed is_fresh boolean."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                puuid,
                dataset,
                first_loaded_at,
                last_updated_at,
                (now() - last_updated_at) < (%s * interval '1 minute') AS is_fresh
            FROM player_state_registry
            WHERE puuid = %s
            """,
            (threshold_minutes, puuid),
        ).fetchone()
        return _normalize_row(row)
    finally:
        if own_conn:
            conn.close()
