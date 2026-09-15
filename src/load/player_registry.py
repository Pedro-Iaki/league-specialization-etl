import os
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env.local"
DEFAULT_FRESHNESS_MINUTES = 10080  # A Week

_SCHEMA_PATH = Path(__file__).resolve().parent / "player_registry_schema.sql"


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
    """Create the registry table if missing, and migrate older live tables in place.

    Older Neon tables predate the `dataset`/claim columns and had a single-column
    `puuid` primary key, so `CREATE TABLE IF NOT EXISTS` alone is a no-op against them.
    These statements are idempotent and safe to run on every call.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        conn.execute(_SCHEMA_PATH.read_text())  # type: ignore
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
    dataset: str | None = None,
    conn: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        query = """
            SELECT
                puuid,
                dataset,
                first_loaded_at,
                last_updated_at
            FROM player_state_registry
            WHERE (now() - last_updated_at) >= (%s * interval '1 minute')
        """
        params: list[Any] = [threshold_minutes, threshold_minutes]
        if dataset is not None:
            query += " AND dataset = %s"
            params.append(dataset)
        query += " ORDER BY last_updated_at ASC"
        rows = conn.execute(query, params).fetchall()
        return [normalized for row in rows if (normalized := _normalize_row(row)) is not None]
    finally:
        if own_conn:
            conn.close()


def get_player_state(
    puuid: str,
    dataset: str,
    threshold_minutes: int = DEFAULT_FRESHNESS_MINUTES,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return a single player's registry row for the given dataset, including a computed is_fresh boolean."""
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
            WHERE puuid = %s AND dataset = %s
            """,
            (threshold_minutes, puuid, dataset),
        ).fetchone()
        return _normalize_row(row)
    finally:
        if own_conn:
            conn.close()


def claim_stale_players(
    limit: int,
    run_id: str,
    threshold_minutes: int = DEFAULT_FRESHNESS_MINUTES,
    conn: psycopg.Connection | None = None,
) -> list[str]:
    """Atomically claim up to `limit` stale players' 'players' rows for a refresh job.

    Only the 'players' row is claimed; a mastery refresh for the same puuid piggybacks
    on this same claim instead of taking its own, since both fetches happen together.
    Uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent claimers never grab the same row.
    """
    if limit <= 0:
        return []

    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        ensure_schema(conn)
        rows = conn.execute(
            """
            UPDATE player_state_registry
            SET claim_status = 'claimed', claimed_by = %s, claimed_at = now()
            WHERE (puuid, dataset) IN (
                SELECT puuid, dataset
                FROM player_state_registry
                WHERE dataset = 'players'
                  AND claim_status = 'idle'
                  AND (now() - last_updated_at) >= (%s * interval '1 minute')
                ORDER BY last_updated_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING puuid
            """,
            (run_id, threshold_minutes, limit),
        ).fetchall()
        if own_conn:
            conn.commit()
        return [row[0] for row in rows]
    finally:
        if own_conn:
            conn.close()


def release_claims(puuids: list[str], conn: psycopg.Connection | None = None) -> int:
    """Release claims on the given puuids' 'players' rows, regardless of fetch outcome."""
    if not puuids:
        return 0

    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE player_state_registry
            SET claim_status = 'idle', claimed_by = NULL, claimed_at = NULL
            WHERE dataset = 'players' AND puuid = ANY(%s::text[])
            """,
            (puuids,),
        )
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()


def release_expired_claims(claim_timeout_minutes: int, conn: psycopg.Connection | None = None) -> int:
    """Reap claims left stuck by a crashed or killed refresh worker."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        ensure_schema(conn)
        cur = conn.execute(
            """
            UPDATE player_state_registry
            SET claim_status = 'idle', claimed_by = NULL, claimed_at = NULL
            WHERE claim_status = 'claimed'
              AND (now() - claimed_at) >= (%s * interval '1 minute')
            """,
            (claim_timeout_minutes,),
        )
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()
