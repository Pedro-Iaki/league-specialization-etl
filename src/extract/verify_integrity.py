"""Verify data integrity by checking if all fetched players have corresponding mastery data."""

from __future__ import annotations

import json
from pathlib import Path
from setuptools.command.build_ext import if_dl

BASE_DIR = Path(__file__).resolve().parents[2]
PLAYERS_INPUT_PATH = BASE_DIR / "data" / "raw" / "players"
MASTERIES_PATH = BASE_DIR / "data" / "raw" / "masteries"
LOGS_PATH = BASE_DIR / "data" / "logs"


def verify_integrity() -> None:
	"""Loop through every .json in a players folder and verify mastery data exists. \n Then, loop through every .json in a masteries folder and verify player data exists. \n Print out any missing or duplicate data."""

	missing_masteries_puuids = {}
	missing_player_puuids = {}
	duplicated_player_puuids = {}
	duplicated_masteries_puuids = {}
	broken_files = []
	all_puuids_players = []
	all_puuids_masteries = []

	#get all players
	for player_file in PLAYERS_INPUT_PATH.rglob("*.json"):
		try:
			payload = json.loads(player_file.read_text(encoding="utf-8"))
			players = payload.get("players", [])
			if not players or not isinstance(players, list):
				broken_files.append(player_file)
				continue
			for player in players:
				puuid = player.get("puuid")
				if not puuid:
					continue
				all_puuids_players.append((player_file, puuid))

		except Exception as e:
			print(f"Error processing {player_file}: {e}")
			continue
	
	#get all masteries
	for mastery_file in MASTERIES_PATH.rglob("*.json"):
		try:
			payload = json.loads(mastery_file.read_text(encoding="utf-8"))
			masteries = payload.get("masteries", [])
			if not masteries or not isinstance(masteries, list):
				broken_files.append(mastery_file)
				continue
			first_mastery = masteries[0]
			if first_mastery:
				puuid = first_mastery.get("puuid")
				if not puuid:
					continue
				all_puuids_masteries.append((mastery_file, puuid))

		except Exception as e:
			print(f"Error processing {mastery_file}: {e}")
			continue

	for mastery_file, puuid in all_puuids_masteries:
		#if a puuid not present in players but present in masteries, add to missing_player_puuids
		if puuid not in [p[1] for p in all_puuids_players]:
			missing_player_puuids[puuid] = str(mastery_file)

		#if a puuid is present twice in masteries, add to duplicated_puuids
		uniques = sum(1 for item in all_puuids_masteries if item[1] == puuid)
		if uniques > 1 and puuid not in duplicated_masteries_puuids:
			duplicated_masteries_puuids[puuid] = [str(mastery_file) for mastery_file, p in all_puuids_masteries if p == puuid]

	for player_file, puuid in all_puuids_players:
		#if a puuid is present in players but not present in masteries, add to missing_masteries_puuids
		if puuid not in [m[1] for m in all_puuids_masteries]:
			missing_masteries_puuids[puuid] = str(player_file)
		
		#if a puuid is present twice in players, add to duplicated_puuids
		uniques = sum(1 for item in all_puuids_players if item[1] == puuid)
		if uniques > 1 and puuid not in duplicated_player_puuids:
			duplicated_player_puuids[puuid] = [str(player_file) for player_file, p in all_puuids_players if p == puuid]

	passed_test = True
	if duplicated_player_puuids:
		passed_test = False
		print(f"Found {len(duplicated_player_puuids)} duplicated player files for the following PUUIDs:")
		if len(duplicated_player_puuids) < 5:
			for puuid in duplicated_player_puuids:
				print(f"  - {puuid} (from {', '.join(str(f) for f in duplicated_player_puuids[puuid])})")
	if duplicated_masteries_puuids:
		passed_test = False
		print(f"Found {len(duplicated_masteries_puuids)} duplicated mastery files for the following PUUIDs:")
		if len(duplicated_masteries_puuids) < 5:
			for puuid in duplicated_masteries_puuids:
					print(f"  - {puuid} (from {', '.join(str(f) for f in duplicated_masteries_puuids[puuid])})")
	if missing_masteries_puuids:		
		passed_test = False
		print(f"Missing mastery data for {len(missing_masteries_puuids)} PUUIDs:")
		if len(missing_masteries_puuids) < 5:
			for puuid, source_file in missing_masteries_puuids.items():
				print(f"  - {puuid} (from {source_file})")
	if missing_player_puuids:
		passed_test = False
		print(f"Found mastery data for {len(missing_player_puuids)} PUUIDs without corresponding player data:")
		if len(missing_player_puuids) < 5:
			for puuid, source_file in missing_player_puuids.items():
				print(f"  - {puuid} (from {source_file})")
	if broken_files:
		passed_test = False
		print(f"Found {len(broken_files)} broken files:")
		if len(broken_files) < 5:
			for broken_file in broken_files:
				print(f"  - {broken_file}")
	
	# Log results to JSON file
	log_data = {
		"duplicated_masteries": duplicated_masteries_puuids,
		"duplicated_players": duplicated_player_puuids,
		"missing_masteries": [{"puuid": puuid, "source_file": source_file} for puuid, source_file in missing_masteries_puuids.items()],
		"missing_players": [{"puuid": puuid, "source_file": source_file} for puuid, source_file in missing_player_puuids.items()],
		"all_players": [{"puuid": puuid, "source_file": str(player_file)} for player_file, puuid in all_puuids_players],
		"all_masteries": [{"puuid": puuid, "source_file": str(mastery_file)} for mastery_file, puuid in all_puuids_masteries],
		"broken_files": [{"source_file": str(broken_file)} for broken_file in broken_files],
	}
	
	log_file = LOGS_PATH / "integrity_check.json"
	log_file.parent.mkdir(parents=True, exist_ok=True)
	log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
	
	if passed_test:
		print(":D All players have corresponding mastery data!")
	else:
		print(f"Integrity check failed. Details logged to {log_file}")


if __name__ == "__main__":
	verify_integrity()
