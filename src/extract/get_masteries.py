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
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "masteries"

def fetch_player_masteries(
	puuid: str,
	region: str = None,
	api_client: API = None,
	task_id: int | None = None
) -> list[dict]:
	"""Fetch champion mastery entries for a player."""

	if not api_client:
		logger.error("No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.")
		return None
	if task_id is not None:
		db.update_mastery_task(task_id, "in_progress")

	url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
	response = api_client.get(url)
	
	if not response.ok:
		db.update_mastery_task(task_id, "failed", error_message=f"Error: {response.status_code} - {response.text}")
		return None

	raw_payload = response.json()
	try:
		validated_masteries = [models.ChampionMasteryEntry.model_validate(m).model_dump() for m in raw_payload]
		return validated_masteries
	except Exception as e:
		logger.error(f"Error validating mastery data for player {puuid}: {e}")
		db.update_mastery_task(task_id, "failed", error_message=f"Validation error: {e}")
		return None

def get_partitioned_path(info: dict) -> Path:
	"""Get a partitioned path based on region, queue, and tier."""
	
	date = info.get("latest_logged_at")
	date = date.strftime("%y%m%d") if date else None

	region_folder_name = f"region={info.get('region')}"
	region_folder = OUTPUT_PATH / region_folder_name
	region_folder.mkdir(parents=True, exist_ok=True)
	queue_folder_name = f"queue={info.get('queue')}"
	queue_folder = region_folder / queue_folder_name
	queue_folder.mkdir(parents=True, exist_ok=True)
	tier_folder_name = f"tier={info.get('tier')}"
	tier_folder = queue_folder / tier_folder_name
	tier_folder.mkdir(parents=True, exist_ok=True)	
	date_folder_name = "dt=" + (date if date else "ERROR!DATE_NOT_PROVIDED") #this shouldnt happen, if it does, we cannot afford to have the date be different.
	date_folder = tier_folder / date_folder_name
	date_folder.mkdir(parents=True, exist_ok=True)
	return date_folder

def save_masteries(mastery_rows: list[dict], output_path: Path = OUTPUT_PATH, date: str = None, division: str = None, puuid: str = None) -> Path:
	"""Persist all fetched masteries as raw JSON."""

	this_path = output_path / f"masteries_{division}_{date.strftime('%H%M%S')}_{puuid}.json"
	payload = {
		"source": "riot-api",
		"fetched_at": datetime.now(timezone.utc).isoformat(),
		"masteries": mastery_rows,
	}
	this_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
	return this_path

def get_player_info(puuid: str) -> dict:
	"""Get the player info from the database."""
	info = db.get_player_info(puuid)
	if not info:
		logger.error(f"No player info found for {puuid}.")
		return {}

	region = info.get("region")
	queue = info.get("queue")
	tier = info.get("tier")
	date = info.get("latest_logged_at")
	if not region or not queue or not tier or not date:
		logger.error(f"Missing required information for player {puuid}: region={region}, queue={queue}, tier={tier}, date={date}")

	return info

def run(run_id: int, api_client: API, limit: int) -> None:
	players = db.get_players_missing_masteries(True, limit)
	if players is None or len(players) == 0:
		logger.error("No players missing masteries found.")
		return
	else:
		logger.info(f"{len(players)} players missing masteries found.")

	# Add the mastery tasks for each player before creating them
	logger.info(f"Adding mastery task for players.")
	task_ids = []
	for puuid in players:
		if puuid:
			task_ids.append(db.add_mastery_task(run_id, puuid))

	processed = 0
	for puuid in players:
		if not puuid or db.get_mastery_status_for_player(puuid) == "in_progress":
			# We skip player in progress in case another thread is working on it already
			logger.info(f"Skipping player {puuid} as they are already in progress or invalid.")
			continue
		
		logger.info(f"Fetching mastery data for player {puuid}.")
		player_info = get_player_info(puuid)
		task_id = db.get_mastery_id_from_list(task_ids, puuid)

		mastery_payload = fetch_player_masteries(
			puuid=puuid,
			region=player_info.get("region"),
			api_client=api_client,
			task_id=task_id
		)
		if mastery_payload is None:
			logger.error(f"No mastery data found for player {puuid}.")
			continue


		output_path = get_partitioned_path(player_info)
		this_path = save_masteries(mastery_payload, output_path=output_path, date=player_info.get("latest_logged_at"), division=player_info.get("division"), puuid=puuid)
		db.update_mastery_task(task_id, "success", file_path=str(this_path))
	
		processed += 1
		logger.info(f"Saved new mastery data. Remaining: {min(limit, len(players)) - processed}.")
		if processed >= limit:
			break
	
	if len(players) > limit:
		logger.info(f"Reached the limit of {limit} processed players. Stopping.")
	else:
		logger.info(f"Processed all {len(players)} players missing masteries.")