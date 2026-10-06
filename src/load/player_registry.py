import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env.local"
DEFAULT_FRESHNESS_MINUTES = 10080  # A Week

_SCHEMA_PATH = Path(__file__).resolve().parent / "player_registry_schema.sql"


def get_connection(direct: bool = False) -> psycopg.Connection:
    load_dotenv(ENV_PATH)
    database_url = (
        os.getenv("DATABASE_URL_UNPOOLED")
        if direct
        else os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_UNPOOLED")
    )
    if not database_url:
        required = "DATABASE_URL_UNPOOLED" if direct else "DATABASE_URL or DATABASE_URL_UNPOOLED"
        raise ValueError(f"Missing {required}, check .env.local")
    return psycopg.connect(database_url)


def _normalize_row(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = ["puuid", "first_loaded_at", "last_updated_at", "is_fresh"]
    return dict(zip(keys, row))


def ensure_schema(conn: psycopg.Connection) -> None:
    conn.execute(_SCHEMA_PATH.read_text())  # type: ignore


def upsert_players(players: list[dict], conn: psycopg.Connection | None = None) -> int:
    """Register uploaded player snapshots without counting a repeated upload as inactivity."""
    if not players:
        return 0

    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        puuids = [player["puuid"] for player in players]
        regions = [player["region"] for player in players]
        queues = [player["queueType"] for player in players]
        games_totals = [
            int(player["wins"]) + int(player["losses"])
            if player.get("wins") is not None and player.get("losses") is not None
            else None
            for player in players
        ]
        cur = conn.execute(
            """
            INSERT INTO player_state_registry (puuid, region, queue, queue_games_total)
            SELECT * FROM unnest(%s::text[], %s::text[], %s::text[], %s::integer[])
            WHERE true
            ON CONFLICT (puuid, region, queue) DO UPDATE SET
                inactive_streak = CASE
                    WHEN EXCLUDED.queue_games_total IS NOT NULL
                     AND player_state_registry.queue_games_total IS DISTINCT FROM EXCLUDED.queue_games_total
                    THEN 0
                    ELSE player_state_registry.inactive_streak
                END,
                queue_games_total = COALESCE(EXCLUDED.queue_games_total, player_state_registry.queue_games_total),
                last_updated_at = now()
            """,
            (puuids, regions, queues, games_totals),
        )
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()


def record_refresh_result(
    puuid: str,
    region: str,
    queue: str,
    queue_games_total: int | None,
    claimed_by: str,
    conn: psycopg.Connection | None = None,
) -> int:
    """Record a completed refresh; None means the tracked queue had no entry."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE player_state_registry
            SET inactive_streak = CASE
                    WHEN queue_games_total IS NULL THEN 0
                    WHEN %s::integer IS NULL THEN inactive_streak + 1
                    WHEN queue_games_total <> %s::integer THEN 0
                    ELSE inactive_streak + 1
                END,
                queue_games_total = COALESCE(%s::integer, queue_games_total),
                last_updated_at = now()
            WHERE puuid = %s AND region = %s AND queue = %s
              AND claimed_by = %s
            """,
            (queue_games_total, queue_games_total, queue_games_total, puuid, region, queue, claimed_by),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"Refresh claim no longer belongs to {claimed_by} for {region}/{queue}/{puuid}")
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()


def get_fresh_players(
    threshold_minutes: int = DEFAULT_FRESHNESS_MINUTES,
    *,
    puuids: list[str],
    region: str,
    queue: str,
    conn: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    if not puuids:
        return []
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT puuid, first_loaded_at, last_updated_at
            FROM player_state_registry
            WHERE last_updated_at >= (now() - (%s * interval '1 minute'))
              AND region = %s AND queue = %s
              AND puuid = ANY(%s::text[])
            """,
            (threshold_minutes, region, queue, puuids),
        ).fetchall()
        return [normalized for row in rows if (normalized := _normalize_row(row)) is not None]
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
                first_loaded_at,
                last_updated_at
            FROM player_state_registry
            WHERE last_updated_at < (now() - (%s * interval '1 minute'))
        """,
            (threshold_minutes,),
        ).fetchall()
        return [normalized for row in rows if (normalized := _normalize_row(row)) is not None]
    finally:
        if own_conn:
            conn.close()


def get_player_state(
    puuid: str,
    region: str,
    queue: str,
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
                first_loaded_at,
                last_updated_at,
                last_updated_at >= (now() - (%s * interval '1 minute')) AS is_fresh
            FROM player_state_registry
            WHERE puuid = %s
              AND region = %s
              AND queue = %s
            """,
            (threshold_minutes, puuid, region, queue),
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
) -> list[dict[str, str]]:
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
        rows = conn.execute(
            """
            WITH candidates AS (
                SELECT puuid, region, queue
                FROM player_state_registry
                WHERE claim_status = 'idle'
                  AND last_updated_at < (now() - (%s * interval '1 minute'))
                ORDER BY
                    greatest(
                        inactive_streak - floor(
                            extract(epoch FROM (now() - last_updated_at)) / (%s * 60)
                        )::integer,
                        0
                    ),
                    last_updated_at,
                    puuid
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE player_state_registry AS registry
            SET claim_status = 'claimed', claimed_by = %s, claimed_at = now()
            FROM candidates
            WHERE registry.puuid = candidates.puuid
              AND registry.region = candidates.region
              AND registry.queue = candidates.queue
            RETURNING registry.puuid, registry.region, registry.queue
            """,
            (threshold_minutes, threshold_minutes, limit, run_id),
        ).fetchall()
        stale_players = [{"puuid": str(row[0]), "region": str(row[1]), "queue": str(row[2])} for row in rows]
        if own_conn:
            conn.commit()

        return stale_players
    finally:
        if own_conn:
            conn.close()


def release_claims(puuids: list[str], claimed_by: str, conn: psycopg.Connection | None = None) -> int:
    """Release only claims still owned by this refresh worker."""
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
            WHERE puuid = ANY(%s::text[]) AND claimed_by = %s
            """,
            (puuids, claimed_by),
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
        cur = conn.execute(
            """
            UPDATE player_state_registry
            SET claim_status = 'idle', claimed_by = NULL, claimed_at = NULL
            WHERE claim_status = 'claimed'
              AND claimed_at < (now() - (%s * interval '1 minute'))
            """,
            (claim_timeout_minutes,),
        )
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()


def claim_rank_page(
    region: str,
    queue: str,
    patch: str,
    tiers: list[str],
    divisions: list[str],
    claim_timeout_minutes: int = 30,
    conn: psycopg.Connection | None = None,
) -> dict[str, str | int] | None:
    """Reserve one division page in shared Postgres state.

    Equal-depth choices visit division I across tiers before division II. Page
    reservations prevent separate collectors from requesting the same cursor.
    """
    if not tiers or not divisions:
        return None
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO rank_page_progress (region, queue, tier, division, patch)
            SELECT %s, %s, tiers.tier, divisions.division, %s
            FROM unnest(%s::text[]) AS tiers(tier)
            CROSS JOIN unnest(%s::text[]) AS divisions(division)
            WHERE true
            ON CONFLICT DO NOTHING
            """,
            (region, queue, patch, tiers, divisions),
        )
        token = uuid4().hex
        row = conn.execute(
            """
            WITH candidate AS (
                SELECT region, queue, tier, division, patch
                FROM rank_page_progress
                WHERE region = %s AND queue = %s AND patch = %s
                  AND tier = ANY(%s::text[]) AND division = ANY(%s::text[])
                  AND (claim_token IS NULL OR claimed_at < now() - (%s * interval '1 minute'))
                ORDER BY loop_count, pages_fetched,
                    array_position(%s::text[], division),
                    array_position(%s::text[], tier),
                    players_seen
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE rank_page_progress AS progress
            SET claim_token = %s, claimed_at = now()
            FROM candidate
            WHERE progress.region = candidate.region
              AND progress.queue = candidate.queue
              AND progress.tier = candidate.tier
              AND progress.division = candidate.division
              AND progress.patch = candidate.patch
            RETURNING progress.tier, progress.division, progress.current_page, progress.loop_count
            """,
            (region, queue, patch, tiers, divisions, claim_timeout_minutes, divisions, tiers, token),
        ).fetchone()
        if own_conn:
            conn.commit()
        if row is None:
            return None
        return {
            "tier": str(row[0]),
            "division": str(row[1]),
            "page": int(row[2]),
            "loop": int(row[3]),
            "claim_token": token,
        }
    finally:
        if own_conn:
            conn.close()


def complete_rank_page(
    claim_token: str,
    player_count: int,
    conn: psycopg.Connection | None = None,
) -> int:
    """Advance a reserved cursor after a validated API page."""
    if player_count < 0:
        raise ValueError("player_count must be nonnegative")
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        row = conn.execute(
            """
            UPDATE rank_page_progress
            SET loop_count = CASE WHEN %s = 0 THEN loop_count + 1 ELSE loop_count END,
                current_page = CASE WHEN %s = 0 THEN 1 ELSE current_page + 1 END,
                last_player_count = %s,
                players_seen = players_seen + %s,
                pages_fetched = pages_fetched + 1,
                claim_token = NULL,
                claimed_at = NULL,
                last_updated_at = now()
            WHERE claim_token = %s
            RETURNING current_page
            """,
            (player_count, player_count, player_count, player_count, claim_token),
        ).fetchone()
        if row is None:
            raise RuntimeError("Rank page claim expired or was already completed")
        if own_conn:
            conn.commit()
        return int(row[0])
    finally:
        if own_conn:
            conn.close()


def release_rank_page(claim_token: str, conn: psycopg.Connection | None = None) -> int:
    """Leave the cursor unchanged when a page request fails."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE rank_page_progress
            SET claim_token = NULL, claimed_at = NULL
            WHERE claim_token = %s
            """,
            (claim_token,),
        )
        if own_conn:
            conn.commit()
        return cur.rowcount
    finally:
        if own_conn:
            conn.close()
