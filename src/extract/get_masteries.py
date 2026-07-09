"""Fetch mastery data for several stored Riot players and save it in the raw data folder, under a partitioned structure based on region, queue, tier, and date."""

from __future__ import annotations

import json
import os
from datetime import datetime, time, timezone
from pathlib import Path
from time import sleep

import requests
from dotenv import load_dotenv


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
	api_key: str | None = None
) -> list[dict]:
	"""Fetch top champion mastery entries for one player."""

	if not api_key:
		raise ValueError("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
	if not region:
		raise ValueError("No region provided. Please set the region parameter.")

	url = f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
	
	response = requests.get(
		url,
		headers={"X-Riot-Token": api_key},
		timeout=30,
	)
	
	if(response.status_code == 429):
		print(f"Rate limit reached for player {puuid}.")
		sleep(30)
	else:
		response.raise_for_status()

	return response

def handle_rate_limit(response):
	# Check the response headers for rate limit information, and wait accordingly
	print(response.headers)
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


def run(manifest: dict) -> None:
	load_dotenv(BASE_DIR / "config" / "RIOT_API_KEY.env")
	api_key = os.getenv("RIOT_API_KEY")
	region = manifest.get("region")
	queue = manifest.get("queue")
	tier = manifest.get("tier")
	date = manifest.get("date")
	time = manifest.get("time")
	division = manifest.get("division")
	player_path = manifest.get("player_path")
	if not region or not queue or not tier or not date or not time or not division or not player_path:
		raise ValueError("Manifest must contain 'region', 'queue', 'tier', 'date', 'time', 'division', and 'player_path' fields.")
	elif not api_key:
		raise ValueError("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")

	players = load_players(Path(player_path))
	if players is None:
		raise ValueError("No players JSON found. Please ensure the players JSON file exists in the expected location.")


	output_path = get_partitioned_path(region, queue, tier, date)
	outputted_players = []
	for player in players:
		puuid = player.get("puuid")
		if not puuid or puuid in outputted_players:
			print(f"Skipping player {puuid} as it has already been processed or is invalid.")
			continue

		mastery_response = fetch_player_masteries(
			puuid=puuid,
			region=region,
			api_key=api_key
		)
		if mastery_response is None:
			print(f"No mastery data found for player {puuid}.")
			continue
		save_masteries(mastery_response.json(), output_path=output_path, time=time, division=division, puuid=puuid)
		outputted_players.append(puuid)
		handle_rate_limit(mastery_response)
		print(f"Saved mastery data for player {puuid} to {output_path}")