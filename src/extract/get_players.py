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


BASE_DIR = Path(__file__).resolve().parents[2] #this puts us in the root of the project
OUTPUT_PATH = BASE_DIR / "data" / "raw" / "players"
DEFAULT_REGION = "na1"
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
DEFAULT_TIER = "DIAMOND"
DEFAULT_DIVISION = "I"

def build_players_filename(division: str, time: str = None) -> str:
	"""Build the compact output filename for player extraction."""

	timestamp = time if time else datetime.now(timezone.utc).strftime("%H%M%S")
	return f"players_{division}_{timestamp}.json"


def fetch_players(region: str = DEFAULT_REGION, api_key: str = None, queue: str = DEFAULT_QUEUE, tier: str = DEFAULT_TIER, random_division: bool = False, forced_division: str = DEFAULT_DIVISION) -> list[dict]:
	"""Fetch the current player list from Riot's challenger league endpoint."""

	if api_key is None: raise ValueError("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
	if random_division:
		division = random.choice(["I", "II", "III", "IV"])
	else:
		division = forced_division
  
	url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
	response = requests.get(
		url,
		headers={"X-Riot-Token": api_key},
		timeout=30,
	)
	response.raise_for_status()

	payload = response.json()
	return payload, division, response

def get_partitioned_path(base_path: Path, region: str, queue: str, tier: str, date: str = None) -> Path:
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
	output_path: Path = OUTPUT_PATH,
	region: str = DEFAULT_REGION,
	queue: str = DEFAULT_QUEUE,
	tier: str = DEFAULT_TIER,
	division: str = DEFAULT_DIVISION,
	date: str = None,
	time: str = None,
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
				print(f"Rate limit close. Waiting for {period/10} seconds before retrying...")
				sleep(period/10) #wait for 10% of the period before retrying
				return True
			if count >= period: #if the count is greater than or equal to the limit
				print(f"Rate limit reached. Waiting for {period} seconds before retrying...")
				sleep(period/2) #wait for 50% of the period before retrying
				return False
	else:
		raise ValueError("Rate limit headers not found in the response.")

def pick_least_populated_tier(region: str, queue: str, date: str, output_path: Path = OUTPUT_PATH) -> str:
	"""Pick the tier with the least number of files in the output path."""

	tiers = ["DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON"]
	tier_counts = {}
	for tier_option in tiers:
		tier_path = get_partitioned_path(output_path, region, queue, tier_option, date)
		file_count = len(list(tier_path.glob("*.json")))
		tier_counts[tier_option] = file_count

	return min(tier_counts, key=tier_counts.get)

def run() -> dict:
	load_dotenv(BASE_DIR / "config" / "RIOT_API_KEY.env")
	api_key = os.getenv("RIOT_API_KEY")
	region = DEFAULT_REGION
	queue = DEFAULT_QUEUE
	#Although it seems overkill, we should still store the time first so we avoid 
	#any race conditions with the date changing between the date and time fetches
	time = datetime.now(timezone.utc).strftime("%H%M%S")
	date = datetime.now(timezone.utc).strftime("%y%m%d")
	tier = pick_least_populated_tier(region, queue, date)

	players, division, response = fetch_players(region=region, api_key=api_key, queue=queue, tier=tier, random_division=True)
	output_path = save_players(players, region=region, queue=queue, tier=tier, division=division, date=date, time=time)
	handle_rate_limit(response)
	
	return {
		"region": region,
		"queue": queue,
		"tier": tier,
		"division": division,
		"date": date,
		"time": time,
		"player_path": str(output_path),
		"player_count": len(players)
	}