"""Fetch ranked player pages and save validated snapshots as partitioned Parquet."""

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

import extract.extraction_db_helper as db
import pydantic_models as models
from extract import output_helper
from extract.api_client_protocol import APIClient
from load import player_registry
from load.player_registry import get_fresh_players

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "players"
OptStr = str | None
DEFAULT_TIERS = ["DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON"]
DEFAULT_DIVISIONS = ["I", "II", "III", "IV"]


def run(
    run_id: int,
    api_client: APIClient,
    region: str,
    queue: str,
    tier: OptStr = None,
    division: OptStr = None,
    freshness_minutes: int = 10080,
    tiers: list[str] | None = None,
    divisions: list[str] | None = None,
):
    """Fetch one page, using shared pagination for the general tier/division crawl."""
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
    eligible_tiers = [tier] if tier else (tiers or DEFAULT_TIERS)
    eligible_divisions = [division] if division else (divisions or DEFAULT_DIVISIONS)
    page_claim = player_registry.claim_rank_page(
        region, queue, patch, eligible_tiers, eligible_divisions
    )
    if page_claim is None:
        logger.info("No rank page is available for {} {} {}.", region, queue, patch)
        return
    tier = str(page_claim["tier"])
    division = str(page_claim["division"])
    try:
        task_id = db.add_player_task(run_id)
    except Exception:
        player_registry.release_rank_page(str(page_claim["claim_token"]))
        raise

    players = fetch_players(
        task_id=task_id,
        api_client=api_client,
        region=region,
        queue=queue,
        tier=tier,
        division=division,
        page_claim=page_claim,
    )
    if players is None:
        return

    # Remove players that are fresh in our player registry
    snapshot_player_ids = {player["puuid"] for player in players if player.get("puuid")}
    fresh_players = get_fresh_players(
        freshness_minutes,
        region=region,
        queue=queue,
        puuids=list(snapshot_player_ids),
    )
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


def fetch_players(
    task_id: int,
    api_client: APIClient,
    region: str,
    queue: str,
    tier: str,
    division: str,
    page_claim: dict[str, str | int],
) -> list[dict] | None:
    if api_client is None:
        player_registry.release_rank_page(str(page_claim["claim_token"]))
        logger.error(
            "No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client."
        )
        return None
    page = int(page_claim["page"])
    url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
    page_completed = False
    try:
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
        validated_players = [models.RiotPlayerEntry.model_validate(p).model_dump() for p in raw_payload]
        player_registry.complete_rank_page(str(page_claim["claim_token"]), len(validated_players))
        page_completed = True
        if len(validated_players) == 0:
            logger.info("No players found for {} {} {} {}; page cursor reset.", region, queue, tier, division)
            return []
        else:
            return validated_players
    except (RuntimeError, ValueError) as e:
        logger.error(f"Error validating player data for {region} {queue} {tier} {division}: {e}")
        db.update_player_task(task_id, "failed", error_message=f"Validation error: {e}")
        return None
    finally:
        if not page_completed:
            player_registry.release_rank_page(str(page_claim["claim_token"]))


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
