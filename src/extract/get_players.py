"""Fetches a player snapshot from riot api and saves it to a file\n
Prioritizes fetching players from the least collected divisions that patch, prioritizing those who haven't looped, then those with the least players recorded.\n
It partitions the files by region, queue, tier, patch, and date, and names the files with the division and time of fetch.\n
Each file is a json that contains some metadata, and a list of their player entries, which are validated against the RiotPlayerEntry model.\n
All operational information is stored in the local sqlite database.
"""

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

import extract.extraction_db_helper as db
import pydantic_models as models
from extract import output_helper
from extract.api_client_protocol import APIClient
from load.player_registry import get_fresh_players
from tenacity import P

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "players"
OptStr = str | None


def run(
    run_id: int,
    api_client: APIClient,
    region: str,
    queue: str,
    tier: OptStr = None,
    division: OptStr = None,
    freshness_minutes: int = 10080,
):
    """Fetches a player snapshot from riot api and saves it to a file\n
    Prioritizes fetching players from the least collected divisions that patch, prioritizing those who haven't looped, then those with the least players recorded.\n
    It partitions the files by region, queue, tier, patch, and date, and names the files with the division and time of fetch.\n
    Each file is a json that contains some metadata, and a list of their player entries, which are validated against the RiotPlayerEntry model.\n
    All operational information is stored in the local sqlite database.
    """
    if not region or not queue:
        logger.error("Player extractor not supplied with vital parameters, make sure to assign it.")
        return
    if run_id < 0:
        logger.error("Invalid run id supplied to player extractor, cancelling operation.")
        return

    time = datetime.now(
        timezone.utc
    ).strftime(
        "%H%M%S"
    )  # Although it seems overkill, we should still store the time first so we avoid any race conditions with the date changing between the date and time fetches
    date = datetime.now(timezone.utc).strftime("%y%m%d")
    patch = str(api_client.get_patch())
    if tier is None or division is None:
        tier, division = pick_least_populated_division(region, queue, patch)
    task_id = db.add_player_task(run_id)

    players = fetch_players(
        task_id=task_id,
        api_client=api_client,
        region=region,
        queue=queue,
        tier=tier,
        division=division,
        patch=patch,
    )
    if players is None:
        return

    # Remove players that are fresh in our player registry
    fresh_players = get_fresh_players(freshness_minutes)
    snapshot_player_ids = {player["puuid"] for player in players if player.get("puuid")}
    fresh_player_ids = {player["puuid"] for player in fresh_players if player.get("puuid")}
    snapshot_fresh_ids = snapshot_player_ids.intersection(fresh_player_ids)
    snapshot_viable_players = [p for p in players if p.get("puuid") not in snapshot_fresh_ids]

    # Then discard the snapshot if the remaining players are all already recorded in the database
    recorded_players_ids = set(
        db.get_players_recorded(patch=patch, region=region, queue=queue, tier=tier, division=division)
    )
    all_recorded = {p["puuid"] for p in snapshot_viable_players if p.get("puuid")}.issubset(recorded_players_ids)
    if all_recorded or len(snapshot_viable_players) == 0:
        logger.info(f"No new or stale players found for {region} {queue} {tier} {division}.")
        db.update_player_task(task_id, "success", file_path=None)
        return

    logger.info(
        f"Fetched {len(snapshot_viable_players)}/{len(players)} (unique/total) players for {region} {queue} {tier} {division}."
    )

    output_path = save_players(
        snapshot_viable_players,
        output_path=OUTPUT_PATH,
        player_info={
            "region": region,
            "queue": queue,
            "tier": tier,
            "division": division,
            "date": date,
            "time": time,
        },
        patch=patch,
    )

    db.update_player_task(task_id, "success", file_path=str(output_path))
    for player in snapshot_viable_players:
        puuid = player.get("puuid")
        if puuid:
            db.add_player_records(
                puuid,
                str(output_path),
                region=region,
                queue=queue,
                tier=tier,
                division=division,
                player_task_id=task_id,
                patch=patch,
            )


def pick_least_populated_division(
    region: str, queue: str, patch: str, tier: OptStr = None, division: OptStr = None
) -> tuple[str, str]:
    if tier and division:
        return tier, division

    tiers = ["DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON"]
    divisions = ["I", "II", "III", "IV"]

    if tier:
        tiers = [tier]
    if division:
        divisions = [division]

    # Get a dictionary of (tier, division) -> (loop, count)
    stats = db.get_page_info(region=region, queue=queue, patch=patch, tiers=tiers, divisions=divisions)
    candidate = min(  # Get the smallest where:
        stats.items(),
        key=lambda item: (
            item[1][0],  # Smallest loop
            item[1][1],  # then, smallest count
        ),
    )
    tier = str(candidate[0][0])
    division = str(candidate[0][1])
    return tier, division


def fetch_players(
    task_id: int,
    api_client: APIClient,
    region: str,
    queue: str,
    tier: str,
    division: str,
    patch: str,
    recursion_limit: int = 5,
) -> list[dict] | None:
    if api_client is None:
        logger.error(
            "No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client."
        )
        return None
    if recursion_limit <= 0:
        logger.error(f"Recursion limit reached while fetching players for {region} {queue} {tier} {division}.")
        return None

    page, _loop = db.get_page_and_loop(region, queue, tier, division, patch)
    url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
    db.update_player_task(task_id, "in_progress")

    try:
        response = api_client.get(url, params={"page": page})
    except TimeoutError as e:
        logger.error(f"Error fetching players for {region} {queue} {tier} {division}: {e}")
        db.update_player_task(task_id, "failed", error_message="retry limit reached.")
        return None

    if not response.ok:
        logger.error(
            f"Error fetching players for {region} {queue} {tier} {division}: {response.status_code} - {response.text}"
        )
        db.update_player_task(
            task_id,
            "failed",
            error_message=f"Error: {response.status_code} - {response.text}",
        )
        return None

    raw_payload = response.json()

    try:
        validated_players = [models.RiotPlayerEntry.model_validate(p).model_dump() for p in raw_payload]
        db.update_page_info(region, queue, tier, division, patch, len(validated_players))
        if len(validated_players) == 0:
            logger.warning(f"No players found for {region} {queue} {tier} {division}. Re-Fetching next page.")
            return fetch_players(
                task_id=task_id,
                api_client=api_client,
                region=region,
                queue=queue,
                tier=tier,
                division=division,
                patch=patch,
                recursion_limit=recursion_limit - 1,
            )
        else:
            return validated_players
    except RuntimeError as e:
        logger.error(f"Error validating player data for {region} {queue} {tier} {division}: {e}")
        db.update_player_task(task_id, "failed", error_message=f"Validation error: {e}")
        return None


def save_players(players: list[dict], output_path: Path, player_info: dict, patch: str) -> Path:
    partitions = [
        ("region", player_info["region"]),
        ("queueType", player_info["queue"]),
        ("tier", player_info["tier"]),
        ("rank", player_info["division"]),
        ("patch", patch),
        ("date", player_info["date"]),
    ]
    output_path = output_helper.get_partitioned_path(output_path, partitions)
    output_path = output_path / build_players_filename(player_info["time"])

    slim_players = drop_partitioned_player_columns(players)
    output_helper.write_parquet(slim_players, output_path)
    return output_path


def build_players_filename(time: OptStr = None) -> str:
    timestamp = time if time else datetime.now(timezone.utc).strftime("%H%M%S")
    return f"players_{timestamp}.parquet"


def drop_partitioned_player_columns(players: list[dict]) -> list[dict]:
    slim_players = []
    partitions = ["queueType", "tier", "rank"]
    for player in players:
        slim_player = player.copy()
        for key in partitions:
            if key in slim_player:
                del slim_player[key]
        slim_players.append(slim_player)

    return slim_players
