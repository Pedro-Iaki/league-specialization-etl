"""Fetch a Riot player list and store it in the raw data folder, under a partitioned structure based on region, queue, tier, and date.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import requests
import random
from time import sleep
import pipeline_db as db
import pydantic_models as models
from client import RiotAPIClient as API
from loguru import logger

BASE_DIR = Path(__file__).resolve().parents[2]  # this puts us in the root of the project
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "players"


def build_players_filename(division: str, time: str=None) -> str:
	"""Build the compact output filename for player extraction."""

	timestamp = time if time else datetime.now(timezone.utc).strftime("%H%M%S")
	return f"players_{division}_{timestamp}.json"


def fetch_players(task_id: int, api_client: API, region: str, queue: str, tier: str, division: str) -> list[dict] | None:
	"""Fetch the current player list from Riot's challenger league endpoint."""

	if api_client is None:
		logger.error("No API client provided. Please set the RIOT_API_KEY environment variable and provide a valid API client.")
		return None

	url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
	db.update_player_task(task_id, "in_progress")
	response = api_client.get(url)
	if not response.ok:
		logger.error(f"Error fetching players for {region} {queue} {tier} {division}: {response.status_code} - {response.text}")
		db.update_player_task(task_id, "failed", error_message=f"Error: {response.status_code} - {response.text}")
		return None

	raw_payload = response.json()

	try:
		validated_players = [models.RiotPlayerEntry.model_validate(p).model_dump() for p in raw_payload]
		return validated_players
	except Exception as e:
		logger.error(f"Error validating player data for {region} {queue} {tier} {division}: {e}")
		db.update_player_task(task_id, "failed", error_message=f"Validation error: {e}")
		return None


def get_partitioned_path(base_path: Path, region: str, queue: str, tier: str, date: str=None) -> Path:
	"""Get a partitioned path based on region, queue, and tier."""

	region_folder_name = f"region={region}"
	region_folder = base_path / region_folder_name
	region_folder.mkdir(parents=True, exist_ok=True)
	queue_folder_name = f"queue={queue}"
	queue_folder = region_folder / queue_folder_name
	queue_folder.mkdir(parents=True, exist_ok=True)
	tier_folder_name = f"tier={tier}"
	tier_folder = queue_folder / tier_folder_name
	tier_folder.mkdir(parents=True, exist_ok=True)	
	date_folder_name = "dt=" + (date if date else datetime.now(timezone.utc).strftime("%y%m%d"))
	date_folder = tier_folder / date_folder_name
	date_folder.mkdir(parents=True, exist_ok=True)
	return date_folder


def save_players(
	players: list[dict],
	output_path: Path,
	region: str,
	queue: str,
	tier: str,
	division: str,
	date: str=None,
	time: str=None,
) -> Path:
	"""Persist the fetched player list as raw JSON."""

	output_path = get_partitioned_path(output_path, region, queue, tier, date) / build_players_filename(division, time)

	payload = {
		"source": "riot-api",
		"region": region,
		"queue": queue,
		"tier": tier,
		"division": division,
		"fetched_at": datetime.now(timezone.utc).isoformat(),
		"players": players,
	}

	output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
	return output_path

def pick_least_populated_tier(region: str, queue: str, date: str, output_path: Path=OUTPUT_PATH) -> str:
	"""Pick the tier with the least number of files in the output path."""

	tiers = ["DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON"]
	tier_counts = {}
	for tier_option in tiers:
		tier_path = get_partitioned_path(output_path, region, queue, tier_option, date)
		file_count = len(list(tier_path.glob("*.json")))
		tier_counts[tier_option] = file_count

	return min(tier_counts, key=tier_counts.get)


def run(run_id: int, api_client: API, region: str, queue: str):
	time = datetime.now(timezone.utc).strftime("%H%M%S")	# Although it seems overkill, we should still store the time first so we avoid 
	date = datetime.now(timezone.utc).strftime("%y%m%d")	# any race conditions with the date changing between the date and time fetches
	tier = pick_least_populated_tier(region, queue, date)
	division = random.choice(["I", "II", "III", "IV"])
	task_id = db.add_player_task(run_id)

	players = fetch_players(task_id=task_id, api_client=api_client, region=region, queue=queue, tier=tier, division=division)
	if players is None:
		return None

	# Discard snapshots fully recorded in the database the past week, partial matches are fine.
	recorded_players = set(db.get_players_in_timespan(region=region, queue=queue, tier=tier, division=division, days_ago=7))
	snapshot_players = [player["puuid"] for player in players if player.get("puuid")]
	if sum(1 for item in snapshot_players if item not in recorded_players) == 0:
		logger.info(f"No new players found for {region} {queue} {tier} {division}.")
		db.update_player_task(task_id, "success", file_path=None)
		return

	output_path = save_players(players, output_path=OUTPUT_PATH, region=region, queue=queue, tier=tier, division=division, date=date, time=time)

	db.update_player_task(task_id, "success", file_path=str(output_path))
	for player in players:
		puuid = player.get("puuid")
		if puuid:
			db.add_player_records(puuid, str(output_path), region=region, queue=queue, tier=tier, division=division, player_task_id=task_id)
