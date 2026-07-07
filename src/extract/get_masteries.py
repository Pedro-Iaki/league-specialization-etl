"""Fetch mastery data for stored Riot players and save it as raw JSON."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
PLAYERS_INPUT_PATH = BASE_DIR / "data" / "raw"
OUTPUT_PATH = BASE_DIR / "data" / "raw"
DEFAULT_COUNT = 20


def load_players(players_input_path: Path = PLAYERS_INPUT_PATH) -> tuple[list[dict], str]:
	"""Load previously fetched players from raw JSON."""

	players_input_path = max(players_input_path.glob("players_*.json"), key=lambda p: p.stem.split("_")[-1])
	payload = json.loads(players_input_path.read_text(encoding="utf-8"))
	return payload["players"], str(players_input_path)  #return the payload and the filename of the file we loaded it from


def fetch_player_masteries(
	puuid: str,
	region: str = None,
	api_key: str | None = None,
	count: int = DEFAULT_COUNT,
) -> list[dict]:
	"""Fetch top champion mastery entries for one player."""

	if not api_key:
		raise ValueError("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
	if not region:
		raise ValueError("No region provided. Please set the region parameter.")

	url = (
		f"https://{region}.api.riotgames.com/lol/champion-mastery/v4/"
		f"champion-masteries/by-puuid/{puuid}/top"
	)
	response = requests.get(
		url,
		params={"count": count},
		headers={"X-Riot-Token": api_key},
		timeout=30,
	)
	response.raise_for_status()
	return response.json()


def fetch_all_masteries(
	players: list[dict],
	region: str = None,
	api_key: str | None = None,
	count: int = DEFAULT_COUNT,
) -> list[dict]:
	"""Fetch mastery data for each player entry that has a puuid."""
 
	if not region:
		raise ValueError("No region provided. Please set the region parameter.")

	limit = 5
	current = 0
	results: list[dict] = []
	for player in players:
		puuid = player.get("puuid")
		if not puuid:
			continue
		current += 1
		if current > limit:
			break
		masteries = fetch_player_masteries(
			puuid=puuid,
			region=region,
			api_key=api_key,
			count=count,
		)
		results.append({"puuid": puuid, "masteries": masteries})

	return results


def save_masteries(mastery_rows: list[dict], output_path: Path = OUTPUT_PATH, players_file: str = None) -> Path:
	"""Persist all fetched masteries as raw JSON."""

	if players_file:
		output_path = output_path / f"masteries_{Path(players_file).name[8:]}"

	output_path.parent.mkdir(parents=True, exist_ok=True)
	payload = {
		"source": "riot-api",
		"fetched_at": datetime.now(timezone.utc).isoformat(),
		"masteries": mastery_rows,
	}
	output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
	return output_path


def main() -> None:
	load_dotenv(BASE_DIR / "config" / "RIOT_API_KEY.env")
	api_key = os.getenv("RIOT_API_KEY")

	players, players_file = load_players()
	region = Path(players_file).name.split("_")[1] if players_file else None
	mastery_rows = fetch_all_masteries(players, api_key=api_key, region=region)
	output_path = save_masteries(mastery_rows, players_file=players_file)
	print(f"Saved mastery data for {len(mastery_rows)} players to {output_path}")


if __name__ == "__main__":
	main()
