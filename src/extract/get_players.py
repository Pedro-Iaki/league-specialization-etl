"""Fetches a player snapshot from riot api and saves it to a file\n
		Prioritizes fetching players from the least collected divisions that patch, prioritizing those who haven't looped, then those with the least players recorded.\n
		It partitions the files by region, queue, tier, patch, and date, and names the files with the division and time of fetch.\n
		Each file is a json that contains some metadata, and a list of their player entries, which are validated against the RiotPlayerEntry model.\n
		All operational information is stored in the local sqlite database.
	"""
import json
from datetime import datetime, timezone
from pathlib import Path
import extraction_db_helper as db
import pydantic_models as models
from api_client_protocol import APIClient
from loguru import logger
import output_helper

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "players"
OptStr = str | None

def run(run_id: int, api_client: APIClient, region: str, queue: str, tier: OptStr = None, division: OptStr = None):
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
	
	time = datetime.now(timezone.utc).strftime("%H%M%S")	# Although it seems overkill, we should still store the time first so we avoid any race conditions with the date changing between the date and time fetches
	date = datetime.now(timezone.utc).strftime("%y%m%d")
	patch = str(api_client.get_patch())
	if tier is None or division is None:
		tier, division = pick_least_populated_division(region, queue, patch)
	task_id = db.add_player_task(run_id)

	players = fetch_players(task_id=task_id, api_client=api_client, region=region, queue=queue, tier=tier, division=division, patch=patch)
	if players is None:
		return None

	# Discard snapshots fully recorded in the database this patch, partial matches are fine.
	recorded_players = set(db.get_players_in_patch(patch=patch, region=region, queue=queue, tier=tier, division=division))
	snapshot_players = set(player["puuid"] for player in players if player.get("puuid"))
	unique_new_players = sum(1 for item in snapshot_players if item not in recorded_players)
	if unique_new_players == 0:
		logger.info(f"No new players found for {region} {queue} {tier} {division}.")
		db.update_player_task(task_id, "success", file_path=None)
		return

	logger.info(f"Fetched {unique_new_players}/{len(players)} (unique/total) players for {region} {queue} {tier} {division}.")

	output_path = save_players(players, output_path=OUTPUT_PATH, region=region, queue=queue, tier=tier, division=division, patch=patch, date=date, time=time)

	db.update_player_task(task_id, "success", file_path=str(output_path))
	for player in players:
		puuid = player.get("puuid")
		if puuid:
			db.add_player_records(puuid, str(output_path), region=region, queue=queue, tier=tier, division=division, player_task_id=task_id, patch=patch)

def pick_least_populated_division(region: str, queue: str, patch: str, tier: OptStr = None, division: OptStr = None) -> tuple[str, str]:
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
	candidate = min( # Get the smallest where:
		stats.items(),
		key=lambda item: (
			item[1][0], # Smallest loop
			item[1][1] # then, smallest count
		),
	 )
	tier = candidate[0][0]
	division = candidate[0][1]
	return tier, division

def fetch_players(task_id: int, api_client: APIClient, region: str, queue: str, tier: str, division: str, patch: str) -> list[dict] | None:
	if api_client is None:
		logger.error("No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.")
		return None

	page, loop = db.get_page_and_loop(region, queue, tier, division, patch)
	url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
	db.update_player_task(task_id, "in_progress")
	response = api_client.get(url, params={"page": page})
	if not response.ok:
		logger.error(f"Error fetching players for {region} {queue} {tier} {division}: {response.status_code} - {response.text}")
		db.update_player_task(task_id, "failed", error_message=f"Error: {response.status_code} - {response.text}")
		return None

	raw_payload = response.json()

	try:
		validated_players = [models.RiotPlayerEntry.model_validate(p).model_dump() for p in raw_payload]
		db.update_page_info(region, queue, tier, division, patch, len(validated_players))
		if len(validated_players) == 0:
			logger.warning(f"No players found for {region} {queue} {tier} {division}. Re-Fetching next page.")
			return fetch_players(task_id=task_id, api_client=api_client, region=region, queue=queue, tier=tier, division=division, patch=patch)
		else:
			return validated_players
	except Exception as e:
		logger.error(f"Error validating player data for {region} {queue} {tier} {division}: {e}")
		db.update_player_task(task_id, "failed", error_message=f"Validation error: {e}")
		return None

def save_players(
	players: list[dict],
	output_path: Path,
	region: str,
	queue: str,
	tier: str,
	division: str,
	patch: str,
	date: str,
	time: str
) -> Path:
	partitions = [("region", region), ("queue", queue), ("tier", tier), ("patch", patch), ("date", date)]
	output_path = output_helper.get_partitioned_path(output_path, partitions)
	output_path = output_path / build_players_filename(division, time)

	payload = {
		"region": region,
		"queue": queue,
		"tier": tier,
		"division": division,
		"patch": patch,
		"loose_date": date,
		"fetched_at": datetime.now(timezone.utc).isoformat(),
		"players": players,
	}
	
	output_helper.write_json(payload, output_path)
	return output_path

def build_players_filename(division: str, time: OptStr=None) -> str:
	timestamp = time if time else datetime.now(timezone.utc).strftime("%H%M%S")
	return f"players_{division}_{timestamp}.json"
