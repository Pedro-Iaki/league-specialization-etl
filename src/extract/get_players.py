"""Fetch a Riot player list and store it in the raw data folder.

The script defaults to a placeholder API key so the request shape is visible
even before a real key is configured.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import requests


BASE_DIR = Path(__file__).resolve().parents[2] #this puts us in the root of the project
OUTPUT_PATH = BASE_DIR / "data" / "raw"
DEFAULT_REGION = "na1"
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
DEFAULT_TIER = "DIAMOND"
DEFAULT_DIVISION = "I"

QUEUE_SHORT_CODES = {
	"RANKED_SOLO_5x5": "S",
	"RANKED_FLEX_SR": "F",
	"RANKED_FLEX_TT": "T"
}

TIER_SHORT_CODES = {
	"IRON": "I",
	"BRONZE": "B",
	"SILVER": "S",
	"GOLD": "G",
	"PLATINUM": "P",
	"EMERALD": "E",
	"DIAMOND": "D",
	"MASTER": "M",
	"GRANDMASTER": "GM",
	"CHALLENGER": "C",
}

def build_players_filename(region: str, queue: str, tier: str, division: str) -> str:
	"""Build the compact output filename for player extraction."""

	timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
	return f"players_{region}_{QUEUE_SHORT_CODES[queue]}_{TIER_SHORT_CODES[tier]}_{division}_{timestamp}.json"


def fetch_players(region: str = DEFAULT_REGION, api_key: str = None, queue: str = DEFAULT_QUEUE, tier: str = DEFAULT_TIER, division: str = DEFAULT_DIVISION) -> list[dict]:
	"""Fetch the current player list from Riot's challenger league endpoint."""

	if api_key is None: raise ValueError("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")

	url = f"https://{region}.api.riotgames.com/lol/league/v4/entries/{queue}/{tier}/{division}"
	response = requests.get(
		url,
		headers={"X-Riot-Token": api_key},
		timeout=30,
	)
	response.raise_for_status()

	payload = response.json()
	return payload


def save_players(
	players: list[dict],
	output_path: Path = OUTPUT_PATH,
	region: str = DEFAULT_REGION,
	queue: str = DEFAULT_QUEUE,
	tier: str = DEFAULT_TIER,
	division: str = DEFAULT_DIVISION,
) -> Path:
	"""Persist the fetched player list as raw JSON."""
 
	output_path = output_path / build_players_filename(
		region=region,
		queue=queue,
		tier=tier,
		division=division,
	)
	output_path.parent.mkdir(parents=True, exist_ok=True)

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


def main() -> None:
	load_dotenv(BASE_DIR / "config" / "RIOT_API_KEY.env")
	api_key = os.getenv("RIOT_API_KEY")
	region = DEFAULT_REGION
	queue = DEFAULT_QUEUE
	tier = DEFAULT_TIER
	division = DEFAULT_DIVISION

	players = fetch_players(region=region, api_key=api_key, queue=queue, tier=tier, division=division)
	output_path = save_players(players, region=region, queue=queue, tier=tier, division=division)
	print(f"Saved {len(players)} players to {output_path}")


if __name__ == "__main__":
	main()
