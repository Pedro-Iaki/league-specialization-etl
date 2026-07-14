"""Fetch mastery data for several stored Riot players and save it in the raw data folder, under a partitioned structure based on region, queue, tier, and date."""

from __future__ import annotations, division

import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from time import sleep
import requests
from dotenv import load_dotenv
import pipeline_db as db
import pydantic_models as models
from client import RiotAPIClient as API
from loguru import logger


BASE_DIR = Path(__file__).resolve().parents[2]
PLAYERS_INPUT_PATH = BASE_DIR / "data" / "raw" / "players"
DEFAULT_REGION = "na1"
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
DEFAULT_TIER = "DIAMOND"
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "masteries"


def load_players(players_input_path: Path = None) -> tuple[list[dict], str]:
	"""Load previously fetched players from raw JSON."""

	if players_input_path is None:
		raise ValueError("No players input path provided. Please set the players_input_path parameter.")
	payload = json.loads(players_input_path.read_text(encoding="utf-8"))
	return payload.get("players", None)


def fetch_player_masteries(
	puuid: str,
	region: str = None,
	api_key: str | None = None,
	task_id: int | None = None
) -> tuple[list[dict], requests.Response]:
	"""Fetch top champion mastery entries for one player."""

	if not api_key:
		raise ValueError("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
	if not region:
		raise ValueError("No region provided. Please set the region parameter.")
	if task_id is not None:
			db.update_mastery_task(task_id, "in_progress")
			#print(f"No task found for player {puuid}. Skipping.")

	url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
	response = requests.get(
		url,
		headers={"X-Riot-Token": api_key},
		timeout=60,
	)
	
	if(response.status_code == 429):
		print(f"Rate limit reached for player {puuid}.")
		sleep(60)
		return fetch_player_masteries(puuid=puuid, region=region, api_key=api_key, task_id=task_id)
	elif not response.ok:
		db.update_mastery_task(task_id, "failed", error_message=f"Error: {response.status_code} - {response.text}")
		return None, response

	raw_payload = response.json()
	try:
		validated_masteries = [models.RiotChampionMastery.model_validate(m).model_dump() for m in raw_payload]
		return validated_masteries, response
	except Exception as e:
		print(f"Error validating mastery data for player {puuid}: {e}")
		db.update_mastery_task(task_id, "failed", error_message=f"Validation error: {e}")
		return None, response

def handle_rate_limit(response):
	# Check the response headers for rate limit information, and wait accordingly
	limit_header = response.headers.get("X-App-Rate-Limit")
	count_header = response.headers.get("X-App-Rate-Limit-Count")
	if limit_header and count_header:
		intervals = [item.split(":") for item in count_header.split(",")]
		for count, period in intervals:
			count = int(count)
			period = int(period)
			if count >= period*.8: #if the count is greater than or equal to 80% of the limit				
				#print(f"Rate limit close. Waiting for {period/10} seconds before retrying...")
				sleep(period/10) #wait for 10% of the period before retrying
				return True
			if count >= period: #if the count is greater than or equal to the limit
				#print(f"Rate limit reached. Waiting for {period} seconds before retrying...")
				sleep(period/2) #wait for 50% of the period before retrying
				return False
	else:
		raise ValueError("Rate limit headers not found in the response.")

def get_partitioned_path(region: str, queue: str, tier: str, date: str = None) -> Path:
	"""Get a partitioned path based on region, queue, and tier."""

	region_folder_name = f"region={region}"
	region_folder = OUTPUT_PATH / region_folder_name
	region_folder.mkdir(parents=True, exist_ok=True)
	queue_folder_name = f"queue={queue}"
	queue_folder = region_folder / queue_folder_name
	queue_folder.mkdir(parents=True, exist_ok=True)
	tier_folder_name = f"tier={tier}"
	tier_folder = queue_folder / tier_folder_name
	tier_folder.mkdir(parents=True, exist_ok=True)	
	date_folder_name = "dt=" + (date if date else "ERROR!DATE_NOT_PROVIDED") #this shouldnt happen, if it does, we cannot afford to have the date be different.
	date_folder = tier_folder / date_folder_name
	date_folder.mkdir(parents=True, exist_ok=True)
	return date_folder

def save_masteries(mastery_rows: list[dict], output_path: Path = OUTPUT_PATH, time: str = None, division: str = None, puuid: str = None) -> Path:
	"""Persist all fetched masteries as raw JSON."""

	this_path = output_path / f"masteries_{division}_{time}_{puuid}.json"
	payload = {
		"source": "riot-api",
		"fetched_at": datetime.now(timezone.utc).isoformat(),
		"masteries": mastery_rows,
	}
	this_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
	return this_path


def run(manifest: dict, run_id: int, api_key: str, api_client: API) -> None:
	region = manifest.get("region")
	queue = manifest.get("queue")
	tier = manifest.get("tier")
	date = manifest.get("date")
	time = manifest.get("time")
	division = manifest.get("division")
	player_path = manifest.get("player_path")
	if not region or not queue or not tier or not date or not time or not division or not player_path:
		logger.error("Manifest must contain 'region', 'queue', 'tier', 'date', 'time', 'division', and 'player_path' fields.")
		return
	elif not api_key:
		logger.error("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
		return

	players = load_players(Path(player_path))
	if players is None:
		logger.error("No players JSON found. Please ensure the players JSON file exists in the expected location.")
		return

	# Add the mastery tasks for each player before creating them
	task_ids = []
	for player in players:
		puuid = player.get("puuid")
		if puuid:
			task_ids.append(db.add_mastery_task(run_id, region, queue, tier, division, puuid))

	output_path = get_partitioned_path(region, queue, tier, date)
	processed_players = []
	for player in players:
		puuid = player.get("puuid")
		if not puuid or puuid in processed_players:
			#print(f"Skipping player {puuid} as it has already been processed or is invalid.")
			continue

		task_id = db.get_task_from_list_with_puuid(task_ids, puuid)

		mastery_payload, response = fetch_player_masteries(
			puuid=puuid,
			region=region,
			api_key=api_key,
			task_id=task_id
		)
		if mastery_payload is None:
			#print(f"No mastery data found for player {puuid}.")
			continue

		this_path = save_masteries(mastery_payload, output_path=output_path, time=time, division=division, puuid=puuid)
		processed_players.append(puuid)
		db.update_mastery_task(task_id, "success", file_path=str(this_path))

		handle_rate_limit(response)

		print(f"Saved new mastery data. Remaining: {len(players) - len(processed_players)}.")