"""Refresh known players through Riot's per-player rank and mastery endpoints.

Both outputs use the normal raw partitions for compaction and ingestion. Unlike
discovery's division-page scan, refresh revisits players claimed from the registry.
"""

from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from loguru import logger

import extract.extraction_db_helper as db
import pydantic_models as models
from extract import get_masteries, get_players
from extract.api_client_protocol import APIClient
from extract.progress_helper import PROGRESS_INTERVAL, get_eta_minutes
from load import player_registry


class MissingQueueEntry(Exception):
    """The API answered successfully but the player has no entry for this queue."""


def run(
    run_id: int,
    api_client: APIClient,
    limit: int,
    freshness_minutes: int,
    claim_timeout_minutes: int = player_registry.CLAIM_TIMEOUT_MINUTES,
    *,
    region: str | None = None,
    queue: str | None = None,
) -> dict:
    """Claim stale players, refresh rank and mastery, then release owned claims.

    Release owned claims in finally; expiry cleanup handles workers that crash
    before reaching it. Successful files remain valid even if ownership expires.
    """
    released_expired = player_registry.release_expired_claims(claim_timeout_minutes)
    if released_expired:
        logger.warning(f"Reaped {released_expired} expired refresh claim(s).")

    worker = f"refresh_{run_id}_{uuid4().hex}"
    players = player_registry.claim_stale_players(
        limit, run_id=worker, threshold_minutes=freshness_minutes, region=region, queue=queue,
        excluded_puuids=db.get_pending_player_ids(region, queue, freshness_minutes=freshness_minutes),
    )
    if not players or len(players) == 0:
        logger.info("No stale players to refresh.")
        return {"status": True, "claimed": 0, "players_refreshed": 0, "masteries_refreshed": 0, "failures": 0}

    goal = len(players)
    started_at = monotonic()
    logger.info(
        f"Refreshing {goal} stale players and their masteries... Rough ETA: {get_eta_minutes(2 * goal):.1f} min "
        f"(development-key estimate)."
    )
    masteries_refreshed = 0
    players_refreshed = 0
    players_attempted = 0
    failures = 0
    last_heartbeat = started_at
    # Renew well before expiry, at one third of the claim timeout.
    heartbeat_interval_seconds = claim_timeout_minutes * 60 / 3
    try:
        patch = str(api_client.get_patch())
        now = datetime.now(timezone.utc)
        date = now.strftime("%y%m%d")
        time = now.strftime("%H%M%S")
        for player in players:
            heartbeat_time = monotonic()
            if heartbeat_time - last_heartbeat >= heartbeat_interval_seconds:
                player_registry.heartbeat_claims(worker)
                last_heartbeat = heartbeat_time
            players_attempted += 1
            remaining = goal - players_attempted + 1
            if players_attempted == 1 or players_attempted % PROGRESS_INTERVAL == 0:
                logger.info(
                    f"Refreshing player {players_attempted}/{goal}. Rough ETA: {get_eta_minutes(2 * remaining):.1f} min. "
                    f"Elapsed: {(monotonic() - started_at) / 60:.1f} min."
                )
            try:
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
            except MissingQueueEntry:
                player_registry.record_refresh_result(
                    player["puuid"], player["region"], player["queue"], None, worker
                )
                continue
            if not player_entry:
                failures += 1
                logger.warning(
                    f"Failed to refresh player, Failures: {failures}. Skipping."
                )
                continue
            players_refreshed += 1

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
            else:
                failures += 1
                logger.warning(f"Failed to refresh mastery. Failures: {failures}")

    finally:
        player_registry.release_claims([player["puuid"] for player in players], claimed_by=worker)

    logger.info(
        f"Refreshed ranks for {players_refreshed}/{goal} players and saved masteries for {masteries_refreshed}. "
        f"Failed refreshes: {failures}. Elapsed: {(monotonic() - started_at) / 60:.1f} min."
    )
    return {
        "status": failures == 0,
        "claimed": len(players),
        "players_refreshed": players_refreshed,
        "masteries_refreshed": masteries_refreshed,
        "failures": failures,
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
        raise MissingQueueEntry

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
        logger.warning(f"Failed to fetch rank for player {puuid} in {region} {queue}.")
        return None

    player_info = {
        "puuid": puuid,
        "region": region,
        "queue": queue,
        "tier": entry["tier"],
        "division": entry["rank"],
        "date": date,
        "time": time,
        "task_id": task_id,
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
        logger.warning(f"Failed to fetch mastery data for player {puuid} in {region} {queue}.")
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
