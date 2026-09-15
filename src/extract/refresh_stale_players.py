"""Refresh players flagged stale in the Neon player_state_registry.\n
Claims a batch of stale puuids, re-fetches their current rank (via the by-puuid league-entries
endpoint) and their champion masteries, and writes both into the normal raw partitions so the
existing compaction + Databricks load pipeline picks them up on its next pass.\n
This is intentionally separate from get_players.run() (division-page scanning) and only reuses
get_masteries.py's per-puuid helpers directly, since refreshing a known puuid is a different
access pattern than the bulk division scan.
"""

from datetime import datetime, timezone

from loguru import logger

import extract.extraction_db_helper as db
import extract.get_masteries as get_masteries
import extract.get_players as get_players
import pydantic_models as models
from extract.api_client_protocol import APIClient
from load import player_registry


def fetch_player_rank(
    puuid: str,
    region: str,
    queue: str,
    task_id: int,
    api_client: APIClient,
) -> dict | None:
    """Fetch and validate a single player's current league entry for `queue`."""
    db.update_player_task(task_id, "in_progress")
    url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    try:
        response = api_client.get(url)
    except TimeoutError as e:
        logger.error(f"Error fetching rank for player {puuid}: {e}")
        db.update_player_task(task_id, "failed", error_message="retry limit reached.")
        return None

    if not response.ok:
        logger.error(f"Error fetching rank for player {puuid}: {response.status_code} - {response.text}")
        db.update_player_task(task_id, "failed", error_message=f"Error: {response.status_code} - {response.text}")
        return None

    raw_payload = response.json()
    matching = [entry for entry in raw_payload if entry.get("queueType") == queue]
    if not matching:
        logger.warning(f"No {queue} entry found for player {puuid}; may be unranked or removed.")
        db.update_player_task(task_id, "success", file_path=None)
        return None

    try:
        return models.RiotPlayerEntry.model_validate(matching[0]).model_dump()
    except RuntimeError as e:
        logger.error(f"Error validating rank data for player {puuid}: {e}")
        db.update_player_task(task_id, "failed", error_message=f"Validation error: {e}")
        return None


def run(
    run_id: int,
    api_client: APIClient,
    region: str,
    queue: str,
    limit: int,
    freshness_minutes: int,
    claim_timeout_minutes: int,
) -> dict:
    """Claim a batch of stale puuids, refresh their rank + masteries, and release the claim.

    Claims are always released in a `finally` block so an operational failure never leaves a
    player permanently locked out of future refresh attempts (release_expired_claims is the
    backstop for crashed workers that never reach the `finally`).
    """
    released_expired = player_registry.release_expired_claims(claim_timeout_minutes)
    if released_expired:
        logger.warning(f"Reaped {released_expired} expired refresh claim(s).")

    worker = f"refresh_{run_id}"
    puuids = player_registry.claim_stale_players(limit, run_id=worker, threshold_minutes=freshness_minutes)
    if not puuids:
        logger.info("No stale players to refresh.")
        return {"claimed": 0, "players_refreshed": 0, "masteries_refreshed": 0}

    logger.info(f"Claimed {len(puuids)} stale player(s) for refresh.")
    patch = str(api_client.get_patch())
    date = datetime.now(timezone.utc).strftime("%y%m%d")
    time = datetime.now(timezone.utc).strftime("%H%M%S")

    players_refreshed = 0
    masteries_refreshed = 0
    try:
        for puuid in puuids:
            player_task_id = db.add_player_task(run_id)
            entry = fetch_player_rank(puuid, region=region, queue=queue, task_id=player_task_id, api_client=api_client)
            if entry is not None:
                output_path = get_players.save_players(
                    [entry],
                    output_path=get_players.OUTPUT_PATH,
                    region=region,
                    queue=queue,
                    tier=entry["tier"],
                    division=entry["rank"],
                    patch=patch,
                    date=date,
                    time=time,
                )
                db.update_player_task(player_task_id, "success", file_path=str(output_path))
                db.add_player_records(
                    puuid,
                    str(output_path),
                    player_task_id,
                    region,
                    queue,
                    entry["tier"],
                    entry["rank"],
                    patch,
                )
                players_refreshed += 1

            info = db.get_player_info(puuid)
            if not info:
                logger.error(f"No stored player_info found for {puuid}; skipping mastery refresh.")
                continue

            mastery_task_id = db.add_mastery_task(run_id, puuid)
            mastery_payload = get_masteries.fetch_player_masteries(
                puuid,
                patch,
                mastery_task_id,
                region=info.get("region"),
                api_client=api_client,
            )
            if not mastery_payload:
                continue

            mastery_path = get_masteries.save_masteries(mastery_payload, info, patch)
            if mastery_path:
                db.update_mastery_task(mastery_task_id, "success", patch, file_path=str(mastery_path))
                masteries_refreshed += 1
            else:
                db.update_mastery_task(mastery_task_id, "failed", patch, error_message="Failed to save mastery data.")
    finally:
        player_registry.release_claims(puuids)

    logger.info(
        f"Stale refresh complete: {players_refreshed} player rank(s) and {masteries_refreshed} "
        f"mastery snapshot(s) refreshed out of {len(puuids)} claimed."
    )
    return {
        "claimed": len(puuids),
        "players_refreshed": players_refreshed,
        "masteries_refreshed": masteries_refreshed,
    }
