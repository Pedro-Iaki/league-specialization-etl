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


def run(
    run_id: int,
    api_client: APIClient,
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
    players = player_registry.claim_stale_players(limit, run_id=worker, threshold_minutes=freshness_minutes)
    if not players or len(players) == 0:
        logger.info("No stale players to refresh.")
        return {"claimed": 0, "players_refreshed": 0, "masteries_refreshed": 0}

    logger.info(f"Claimed {len(players)} stale player(s) for refresh.")
    patch = str(api_client.get_patch())
    now = datetime.now(timezone.utc)
    date = now.strftime("%y%m%d")
    time = now.strftime("%H%M%S")

    masteries_refreshed = 0
    players_refreshed = 0
    players_attempted = 0
    try:
        for player in players:
            players_attempted += 1
            logger.info(f"Refreshing player {players_attempted}/{len(players)}.")
            player_entry = handle_player_extraction(
                info={
                    "puuid": player["puuid"],
                    "region": player["region"],
                    "queue": player["queue"],
                    "date": date,
                    "time": time,
                    "patch": patch,
                },
                task_id=db.add_player_task(run_id, is_refresh=True),
                api_client=api_client,
            )
            if not player_entry:
                logger.warning(
                    f"Failed to refresh player, Failures: {players_attempted - players_refreshed}. Skipping."
                )
                continue
            players_refreshed += 1

            logger.info("Refreshing mastery for player...")
            if handle_mastery_extraction(
                info={
                    "puuid": player["puuid"],
                    "region": player["region"],
                    "queue": player["queue"],
                    "date": date,
                    "iso_time": now,
                    "patch": patch,
                    "tier": player_entry["tier"],
                    "division": player_entry["rank"],
                },
                task_id=db.add_mastery_task(run_id, player["puuid"], is_refresh=True),
                api_client=api_client,
            ):
                masteries_refreshed += 1
                logger.info(f"Successfully refreshed mastery. Failures: {players_refreshed - masteries_refreshed}")
            else:
                logger.warning(f"Failed to refresh mastery. Failures: {players_refreshed - masteries_refreshed}")

    finally:
        logger.info("Releasing player claims...")
        player_registry.release_claims([player["puuid"] for player in players])

    logger.info(
        f"Stale refresh complete: {players_refreshed} player rank(s) and {masteries_refreshed} "
        f"mastery snapshot(s) refreshed out of {len(players)} claimed."
    )
    return {
        "status": True,
        "claimed": len(players),
        "players_refreshed": players_refreshed,
        "masteries_refreshed": masteries_refreshed,
    }


def fetch_player_rank(
    puuid: str,
    region: str,
    queue: str,
    task_id: int,
    api_client: APIClient,
) -> dict | None:
    """Fetch and validate a single player's current league entry for `queue`."""
    if api_client is None:
        logger.error(
            "No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client."
        )
        return None
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


def handle_player_extraction(info: dict, task_id: int, api_client: APIClient) -> dict | None:
    puuid = str(info.get("puuid"))
    region = str(info.get("region"))
    queue = str(info.get("queue"))
    date = str(info.get("date"))
    time = str(info.get("time"))
    patch = str(info.get("patch"))
    if not all([puuid, region, queue, date, time, patch]):
        logger.error(f"Missing required player info: {info}")
        return None

    entry = fetch_player_rank(puuid, region=region, queue=queue, task_id=task_id, api_client=api_client)
    if entry is None:
        logger.info(f"Failed to fetch rank for player {puuid} in {region} {queue}.")
        return None

    player_info = {
        "puuid": puuid,
        "region": region,
        "queue": queue,
        "tier": entry["tier"],
        "division": entry["rank"],
        "date": date,
        "time": time,
    }
    output_path = get_players.save_players(
        [entry], output_path=get_players.OUTPUT_PATH, player_info=player_info, patch=patch
    )
    db.update_player_task(task_id, "success", file_path=str(output_path))
    db.add_player_records(
        puuid,
        str(output_path),
        task_id,
        region,
        queue,
        entry["tier"],
        entry["rank"],
        patch,
    )
    return entry


def handle_mastery_extraction(info: dict, task_id: int, api_client: APIClient) -> bool:
    puuid = str(info.get("puuid"))
    region = str(info.get("region"))
    queue = str(info.get("queue"))
    date = str(info.get("date"))
    iso_time = info.get("iso_time")
    patch = str(info.get("patch"))
    tier = str(info.get("tier"))
    division = str(info.get("division"))
    if not all([puuid, region, queue, date, iso_time, patch, tier, division]):
        logger.error(f"Missing required player info: {info}")
        return False

    mastery_payload = get_masteries.fetch_player_masteries(
        puuid,
        patch,
        task_id,
        region=region,
        api_client=api_client,
    )
    if not mastery_payload:
        logger.info(f"failed to fetch mastery data for player {puuid} in {region} {queue}.")
        return False

    mastery_path = get_masteries.save_masteries(
        mastery_payload,
        info={
            "region": region,
            "queue": queue,
            "latest_logged_at": iso_time,
            "tier": tier,
            "division": division,
            "puuid": puuid,
        },
        patch=patch,
    )
    if mastery_path:
        db.update_mastery_task(task_id, "success", patch, file_path=str(mastery_path))
    else:
        db.update_mastery_task(task_id, "failed", patch, error_message="Failed to save mastery data.")
        logger.error(f"Failed to save mastery data for player {puuid} in {region} {queue}.")
        return False
    return True
