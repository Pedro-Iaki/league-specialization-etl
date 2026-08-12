import json
from datetime import datetime, timezone
from pathlib import Path
import extraction_db_helper as db
import src.pydantic_models as models
from api_client_protocol import APIClient
from loguru import logger

import output_helper


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "masteries"
OptStr = str | None

def run(run_id: int, api_client: APIClient, limit: int, runs_remaining: int|None = None) -> None:
	players = db.claim_players_missing_masteries(include_stale_success=True, limit=limit)
	if players is None or len(players) == 0:
		logger.error("No players missing masteries found.")
		return
	else:
		logger.info(f"{len(players)} players missing masteries found.")

	patch = str(api_client.get_patch())
	# Add the mastery tasks for each player before creating them
	logger.info(f"Adding mastery task for players.")
	task_ids = []
	for puuid in players:
		if puuid:
			task_ids.append(db.add_mastery_task(run_id, puuid))

	processed = 0
	for puuid in players:
		logger.info(f"Fetching mastery data for new player...")
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
			task_id=task_id
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
		logger.info(f"Saved new mastery data. Remaining: {min(limit, len(players)) - processed}. Runs remaining: {runs_remaining if runs_remaining is not None else 'N/A'}.")
		if processed >= limit:
			break
	
	if len(players) > limit:
		logger.info(f"Reached the limit of {limit} processed players. Stopping.")
	else:
		logger.info(f"Processed all {len(players)} players missing masteries.")
  
def get_player_info(puuid: str) -> dict:
	"""Get the player info from the database."""
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
		logger.error(f"Missing required information for player {puuid}: region={region}, queue={queue}, tier={tier}, division={division}, date={date}")

	return info

def fetch_player_masteries(
	puuid: str,
	patch: str,
	task_id: int,
	region: OptStr = None,
	api_client: APIClient|None = None,
) -> list[dict]|None:
	"""Fetch champion mastery entries for a player."""

	if not api_client:
		logger.error("No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.")
		return None
	if task_id is not None:
		db.update_mastery_task(task_id, "in_progress", patch)

	url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
	response = api_client.get(url)
	
	if not response.ok:
		db.update_mastery_task(task_id, "failed", patch, error_message=f"Error: {response.status_code} - {response.text}")
		return None

	raw_payload = response.json()
	try:
		validated_masteries = [models.ChampionMasteryEntry.model_validate(m).model_dump() for m in raw_payload]
		return validated_masteries
	except Exception as e:
		logger.error(f"Error validating mastery data for player {puuid}: {e}")
		db.update_mastery_task(task_id, "failed", patch, error_message=f"Validation error: {e}")
		return None

def save_masteries(mastery_rows: list[dict], info: dict, patch: str, output_path: Path = OUTPUT_PATH) -> Path|None:
	"""Persist all fetched masteries as raw JSON."""
	
	region = info.get("region")
	queue = info.get("queue")
	date = info.get("latest_logged_at")
	tier = info.get("tier")
	division = info.get("division")
	puuid = info.get("puuid")
	if not region or not queue or not date or not division or not puuid or not tier:
		logger.error(f"Missing required information for saving masteries: region={region}, queue={queue}, date={date}, division={division}, puuid={puuid}, tier={tier}")
		return None

	time = datetime.fromisoformat(str(date))
	date = date.strftime("%y%m%d")
	partitions = [("region", region), ("queue", queue), ("tier", tier), ("patch", patch), ("date", date)]
	partitioned_path = output_helper.get_partitioned_path(output_path, partitions)
	this_path = partitioned_path / f"masteries_{division}_{time.strftime('%H%M%S')}_{puuid}.json"
	payload = {
		"puuid": puuid,
		"region": region,
		"queue": queue,
		"tier": tier,
		"division": division,
		"fetched_at": datetime.now(timezone.utc).isoformat(),
		"masteries": mastery_rows,
	}
	output_helper.write_json(payload, this_path)
	return this_path