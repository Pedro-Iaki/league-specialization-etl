from collections import defaultdict
import json
from pathlib import Path
import pipeline_db as db
from tqdm import tqdm
from loguru import logger


BASE_DIR = Path(__file__).resolve().parents[2]
PLAYERS_INPUT_PATH = BASE_DIR / "data" / "raw" / "players"
MASTERIES_PATH = BASE_DIR / "data" / "raw" / "masteries"
LOGS_PATH = BASE_DIR / "data" / "logs"

def run_integrity_check(full: bool = False):
	"""Run a full integrity check on the files and database.\n
 		Fast mode skips the file integrity check, which can be lengthy."""
	results = {}
	logger.info(f"Starting integrity check. Full mode: {full}")
	if full:
		logger.info("Running files integrity check, this may take a while...")
		files_log = verify_files_integrity()
		results["files"] = files_log
	logger.info("Running database integrity check...")
	database_log = verify_db_integrity()
	results["database"] = database_log
	logger.info(f"\nIntegrity check completed, check ./data/logs for in-depth results. Summary: \nTotal players in database: {database_log.get('total_player_records', 0)}\nFaulty or incomplete records: {database_log.get('faulty_records_count', 0)}\nDuplicated player rate: {database_log.get('duplicated_players', 0)}\nDiscarded duplicated snapshots: {database_log.get('discarded_player_tasks', 0)}\nPlayer task error rate: {database_log.get('player_task_error_rate', 0)}\nMastery task error rate: {database_log.get('mastery_task_error_rate', 0)}")
	return results

def verify_files_integrity() -> dict:
	missing_masteries_puuids = {}
	missing_player_puuids = {}
	duplicated_player_puuids = []
	duplicated_masteries_puuids = {}
	broken_files = []
	all_puuids_players = defaultdict(list)
	all_puuids_masteries = {}
	
	db.cleanup_stale_runs()

	#get all players
	player_files = set(PLAYERS_INPUT_PATH.rglob("*.json"))
	for player_file in tqdm(player_files, desc="Verifying player files", unit="file"):
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
				all_puuids_players[puuid].append(player_file)

		except Exception as e:
			continue
	
	#get all masteries
	mastery_files = set(MASTERIES_PATH.rglob("*.json"))
	for mastery_file in tqdm(mastery_files, desc="Verifying mastery files", unit="file"):
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
				all_puuids_masteries[puuid] = mastery_file

		except Exception as e:
			continue

	for puuid, mastery_file in tqdm(all_puuids_masteries.items(), desc="Verifying mastery records", unit="record"):
		#if a puuid not present in players but present in masteries, add to missing_player_puuids
		if puuid not in all_puuids_players:
			missing_player_puuids[puuid] = str(mastery_file)

		#if a puuid is present twice in masteries, add to duplicated_puuids
		uniques = sum(1 for player, file in all_puuids_masteries.items() if player == puuid)
		if uniques > 1 and puuid not in duplicated_masteries_puuids:
			duplicated_masteries_puuids[puuid] = [str(file) for player, file in all_puuids_masteries.items() if player == puuid]

	for puuid, paths in tqdm(all_puuids_players.items(), desc="Verifying player records", unit="record"):
		#if a puuid is present in players but not present in masteries, add to missing_masteries_puuids
		if puuid not in all_puuids_masteries:
			missing_masteries_puuids[puuid] = puuid
		
		#if a puuid has more than one file, add to duplicated_puuids
		if len(paths) > 1:
			duplicated_player_puuids.append(puuid)
		
	total_evaluated = len(all_puuids_players) + len(all_puuids_masteries)
	total_errors = len(missing_masteries_puuids) + len(missing_player_puuids) + len(broken_files)
	error_rate = f"{(total_errors / total_evaluated if total_evaluated > 0 else 1) * 100:.2f}%"
	duplicated_mastery_rate = f"{(len(duplicated_masteries_puuids) / len(all_puuids_masteries) if all_puuids_masteries else 0) * 100:.2f}%"
	duplicated_player_rate = f"{(len(duplicated_player_puuids) / len(all_puuids_players) if all_puuids_players else 0) * 100:.2f}%"
	average_duplicity_per_player_file = sum(len(v) for v in all_puuids_players.values()) / len(all_puuids_players) if len(all_puuids_players) else 0 #sum all puuid paths and divide by number of files
	
	conn = db.get_connection()
	db_players = [row["player_id"] for row in conn.execute("SELECT player_id FROM players_recorded")]
	conn.close()
	unregistered_players = [puuid for puuid in all_puuids_players if puuid not in db_players]
	wrongfully_registered_players = [puuid for puuid in db_players if puuid not in all_puuids_players]
 
		
	log_data = {
		"total_evaluated": total_evaluated,
		"total_player_files": len(all_puuids_players),
		"total_mastery_files": len(all_puuids_masteries),
		"total_errors_or_missing": total_errors,
		"error_rate": error_rate,
		"average_duplicity_per_player_file": f"{average_duplicity_per_player_file:.3f}",
		"duplicated_player_rate": duplicated_player_rate,
		"duplicated_players": duplicated_player_puuids,
		"duplicated_mastery_rate": duplicated_mastery_rate,
		"duplicated_masteries": duplicated_masteries_puuids,
		"players_missing_masteries_count": len(missing_masteries_puuids),
		"players_missing_masteries": [{"puuid": puuid, "source_file": source_file} for puuid, source_file in missing_masteries_puuids.items()],
		"masteries_missing_players_count": len(missing_player_puuids),
		"masteries_missing_players": [{"puuid": puuid, "source_file": source_file} for puuid, source_file in missing_player_puuids.items()],
		"unregistered_players_count": len(unregistered_players),
		"unregistered_players": unregistered_players,
		"wrongfully_registered_players_count": len(wrongfully_registered_players),
		"wrongfully_registered_players": wrongfully_registered_players,
		"faulty_files": [{"source_file": str(broken_file)} for broken_file in broken_files],
	}
		
	log_file = LOGS_PATH / "integrity_check.json"
	log_file.parent.mkdir(parents=True, exist_ok=True)
	log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
	
	return log_data

def verify_db_integrity() -> dict[any]: # type: ignore #
	conn = db.get_connection()
	
	player_tasks = conn.execute("SELECT * FROM player_tasks").fetchall()
	player_tasks = {row["task_id"]: dict(row) for row in player_tasks}
	
	mastery_tasks = conn.execute("SELECT * FROM mastery_tasks").fetchall()
	mastery_tasks = {row["task_id"]: dict(row) for row in mastery_tasks}
	
	player_records = conn.execute("SELECT * FROM players_recorded").fetchall()
	player_records = {row["player_id"]: dict(row) for row in player_records}
	
	conn.close()
	
	player_task_errors = [t for t in player_tasks.values() if t["status"] == "failed"]
	mastery_task_errors = [t for t in mastery_tasks.values() if t["status"] == "failed"]
	player_task_error_rate = f"{(len(player_task_errors) / len(player_tasks) if player_tasks else 0) * 100:.2f}%"
	mastery_task_error_rate = f"{(len(mastery_task_errors) / len(mastery_tasks) if mastery_tasks else 0) * 100:.2f}%"
	no_path_tasks = len([t for t in player_tasks.values() if not t["file_path"] or t["file_path"].strip() == ""])
	
	player_error_messages = {}
	for task in player_task_errors:
		msg = task.get("error_message", "none")
		player_error_messages[msg] = player_error_messages.get(msg, 0) + 1
	
	mastery_error_messages = {}
	for task in mastery_task_errors:
		msg = task.get("error_message", "none")
		mastery_error_messages[msg] = mastery_error_messages.get(msg, 0) + 1
	
	faulty_records = []
	paths_counts = []
	
	for record in tqdm(player_records.values(), desc="Verifying player records", unit="record"):
		issues = []
		
		mastery_status = record.get("mastery_status")

		if mastery_status != "success":
			issues.append(f"mastery_status: {mastery_status}")
		
		paths = record.get("paths")
		if not paths:
			issues.append("no_paths")
		else:
			try:
				paths_list = json.loads(paths) if isinstance(paths, str) else paths
				if not paths_list or len(paths_list) == 0:
					issues.append("empty_paths")
				else:
					paths_counts.append(len(paths_list))
			except:
				issues.append("invalid_paths")

		
		player_task_ids = record.get("player_task_ids")
		if not player_task_ids:
			issues.append("no_player_task_ids")
		else:
			try:
				task_ids = json.loads(player_task_ids) if isinstance(player_task_ids, str) else player_task_ids
				if not task_ids:
					issues.append("empty_player_task_ids")
				else:
					for task_id in task_ids:
						if task_id in player_tasks and player_tasks[task_id]["status"] != "success":
							issues.append(f"player_task_{task_id}_not_success")
			except:
				issues.append("invalid_player_task_ids")
		
		mastery_task_id = record.get("mastery_task_id")
		if not mastery_task_id:
			issues.append("no_mastery_task_id")
		else:
			if mastery_status == "success" and not mastery_task_id:
				issues.append("success_but_no_mastery_task_id")
			elif mastery_task_id:
				if mastery_task_id in mastery_tasks and mastery_tasks[mastery_task_id]["status"] != "success":
						issues.append(f"mastery_task_{mastery_task_id}_not_success")
		
		if not record.get("region") or not record.get("queue") or not record.get("tier") or not record.get("division"):
			issues.append("missing_rank_info")
		
		if issues:
			faulty_records.append({
				"player_id": record["player_id"],
				"issues": issues
			})
	
	log_data = {
		"total_player_tasks": len(player_tasks),
		"total_mastery_tasks": len(mastery_tasks),
		"total_player_records": len(player_records),
		"discarded_player_tasks": no_path_tasks,
		"player_task_error_rate": player_task_error_rate,
		"mastery_task_error_rate": mastery_task_error_rate,
		"player_task_errors_by_message": player_error_messages,
		"mastery_task_errors_by_message": mastery_error_messages,
		"faulty_records_count": len(faulty_records),
		"faulty_records": faulty_records,
		"duplicated_players": f"{(sum(paths_counts) / len(paths_counts) if paths_counts else 0)*100-100:.2f}%",
		"duplicated_players_total": len([p for p in paths_counts if p > 1]),
	}
	
	log_file = LOGS_PATH / "db_integrity_check.json"
	log_file.parent.mkdir(parents=True, exist_ok=True)
	log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
	
	return log_data


if __name__ == "__main__":
	run_integrity_check(True)