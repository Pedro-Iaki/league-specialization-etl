from datetime import datetime
from pathlib import Path
from time import monotonic

from loguru import logger

import extract.extraction_db_helper as db
import pydantic_models as models
from extract import output_helper
from extract.api_client_protocol import APIClient
from extract.progress_helper import PROGRESS_INTERVAL, get_eta_minutes

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "masteries"
OptStr = str | None


def run(run_id: int, api_client: APIClient, limit: int, run_n: int | None = None) -> None:
    started_at = monotonic()
    patch = str(api_client.get_patch())
    players = db.claim_players_missing_masteries(include_stale_success=True, limit=limit)
    if players is None or len(players) == 0:
        logger.info("No player masteries to fetch.")
        return
    goal = len(players)
    logger.info(
        f"Fetching masteries for up to {goal} players... Rough ETA: {get_eta_minutes(goal):.1f} min "
        f"(development-key estimate)."
    )

    # Record tasks before requests so interrupted work remains visible.
    task_ids = []
    for puuid in players:
        if puuid:
            task_ids.append(db.add_mastery_task(run_id, puuid))

    processed = 0
    for player_number, puuid in enumerate(players, start=1):
        remaining = goal - player_number + 1
        if player_number == 1 or player_number % PROGRESS_INTERVAL == 0:
            logger.info(
                f"Fetching mastery {player_number}/{goal}. Rough ETA: {get_eta_minutes(remaining):.1f} min. "
                f"Elapsed: {(monotonic() - started_at) / 60:.1f} min."
            )
        player_info = get_player_info(puuid)
        task_id = db.get_mastery_id_from_list(task_ids, puuid)
        if not task_id:
            logger.error(f"No task ID found for player {puuid}. Skipping.")
            continue
        task_id = int(task_id)
        mastery_payload = fetch_player_masteries(
            puuid=puuid,
            patch=patch,
            region=player_info.get("region"),
            api_client=api_client,
            task_id=task_id,
        )
        if mastery_payload is None:
            logger.error(f"No mastery data found for player {puuid}.")
            continue

        this_path = save_masteries(mastery_payload, output_path=OUTPUT_PATH, info=player_info, patch=patch)
        if this_path:
            db.update_mastery_task(task_id, "success", patch, file_path=str(this_path))
        else:
            db.update_mastery_task(task_id, "failed", patch, error_message="Failed to save mastery data.")
            logger.error(f"Failed to save mastery data for player {puuid}.")
            continue

        processed += 1
        if processed >= limit:
            break

    logger.info(
        f"Masteries saved for {processed}/{goal} players. Elapsed: {(monotonic() - started_at) / 60:.1f} min."
    )


def get_player_info(puuid: str) -> dict:
    info = db.get_player_info(puuid)
    if not info:
        logger.error(f"No player info found for {puuid}.")
        return {}

    region = info.get("region")
    queue = info.get("queue")
    tier = info.get("tier")
    division = info.get("division")
    date = info.get("latest_logged_at")
    if not region or not queue or not tier or not division or not date:
        logger.error(
            f"Missing required information for player {puuid}: region={region}, queue={queue}, tier={tier}, division={division}, date={date}"
        )

    return info


def fetch_player_masteries(
    puuid: str,
    patch: str,
    task_id: int,
    region: OptStr = None,
    api_client: APIClient | None = None,
) -> list[dict] | None:
    """Fetch champion mastery entries for a player."""

    if not api_client:
        logger.error(
            "No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client."
        )
        return None
    if task_id is not None:
        db.update_mastery_task(task_id, "in_progress", patch)

    url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
    try:
        response = api_client.get(url)
    except TimeoutError as e:
        logger.error(f"Error fetching mastery data for player {puuid}: {e}")
        db.update_mastery_task(task_id, "failed", patch, error_message="retry limit reached.")
        return None

    if not response.ok:
        db.update_mastery_task(
            task_id,
            "failed",
            patch,
            error_message=f"Error: {response.status_code} - {response.text}",
        )
        return None

    raw_payload = response.json()
    try:
        validated_masteries = [models.ChampionMasteryEntry.model_validate(m).model_dump() for m in raw_payload]
        return validated_masteries
    except RuntimeError as e:
        logger.error(f"Error validating mastery data for player {puuid}: {e}")
        db.update_mastery_task(task_id, "failed", patch, error_message=f"Validation error: {e}")
        return None


def save_masteries(mastery_rows: list[dict], info: dict, patch: str, output_path: Path = OUTPUT_PATH) -> Path | None:
    """Persist all fetched masteries as partitioned Parquet."""

    region = info.get("region")
    queue = info.get("queue")
    date = info.get("latest_logged_at")
    tier = info.get("tier")
    division = info.get("division")
    puuid = info.get("puuid")
    if not region or not queue or not date or not division or not puuid or not tier:
        logger.error(
            f"Missing required information for saving masteries: region={region}, queue={queue}, date={date}, division={division}, puuid={puuid}, tier={tier}"
        )
        return None

    time = datetime.fromisoformat(str(date))
    date = date.strftime("%y%m%d")
    partitions = [
        ("region", region),
        ("queueType", queue),
        ("tier", tier),
        ("rank", division),
        ("patch", patch),
        ("date", date),
    ]
    partitioned_path = output_helper.get_partitioned_path(output_path, partitions)
    this_path = partitioned_path / f"masteries_{time.strftime('%H%M%S')}_{puuid}.parquet"

    output_helper.write_parquet(mastery_rows, this_path)
    return this_path
