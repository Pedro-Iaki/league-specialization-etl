"""Verify data integrity by checking if all fetched players have corresponding mastery data."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
PLAYERS_INPUT_PATH = BASE_DIR / "data" / "raw" / "players"
MASTERIES_PATH = BASE_DIR / "data" / "raw" / "masteries"


def verify_integrity(players_folder: Path=PLAYERS_INPUT_PATH) -> None:
	"""Loop through every .json in a players folder and verify mastery data exists."""

	missing_puuids = []
	found_puuids = []

	for player_file in players_folder.rglob("*.json"):
		try:
			payload = json.loads(player_file.read_text(encoding="utf-8"))
			players = payload.get("players", [])
			region = payload.get("region")
			queue = payload.get("queue")
			tier = payload.get("tier")
			date = player_file.parent.name.split("=")[-1]  # Extract date from folder name

			for player in players:
				puuid = player.get("puuid")
				if not puuid:
					continue

				mastery_dir = MASTERIES_PATH / f"region={region}" / f"queue={queue}" / f"tier={tier}" / f"dt={date}"

				masteries_found = list(mastery_dir.glob(f"masteries_*_{puuid}.json"))

				if len(masteries_found) == 1:
					continue
				elif len(masteries_found) > 1:
					found_puuids.append(puuid)
				else:
					missing_puuids.append((puuid, str(player_file)))

		except Exception as e:
			print(f"Error processing {player_file}: {e}")
			continue

	if found_puuids:
		print("Found multiple mastery files for the following PUUIDs:")
		for puuid in found_puuids:
			print(f"  - {puuid}")
	if missing_puuids:
		print("Missing mastery data for the following PUUIDs:")
		for puuid, source_file in missing_puuids:
			print(f"  - {puuid} (from {source_file})")
	if not missing_puuids and not found_puuids: #not an else since we can have both missing and found
		print(":D All players have corresponding mastery data!")


if __name__ == "__main__":
	verify_integrity()
