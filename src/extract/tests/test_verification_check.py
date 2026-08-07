import json

import t_utilities as util
import verify_integrity

util.set_path_for_extract_modules()


def test_verify_db_integrity_flags_expected_faulty_records(tmp_path, mock_db, db_factory, monkeypatch):
	monkeypatch.setattr(verify_integrity, "LOGS_PATH", tmp_path)
	conn = mock_db.get_connection()
	factory = db_factory(conn)
	run_id = factory.create_individual_run()

	success_task_id = factory.create_individual_player_task({"run_id": run_id, "status": "success", "file_path": "/tmp/a.json"})
	failed_task_id = factory.create_individual_player_task({"run_id": run_id, "status": "failed", "file_path": None, "error_message": "simulated player task failure"})
	success_mastery_id = factory.create_individual_mastery_task({"run_id": run_id, "status": "success", "player_id": factory.get_uuid()})
	factory.create_individual_mastery_task({"run_id": run_id, "status": "failed", "player_id": factory.get_uuid(), "error_message": "simulated mastery task failure"})

	# clean record
	factory.create_individual_players_recorded({
		"player_id": "clean-player", "region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"player_task_ids": json.dumps([success_task_id]), "paths": json.dumps(["/tmp/clean.json"]),
		"mastery_status": "success", "mastery_task_id": success_mastery_id,
	})
	# faulty: mastery still pending
	factory.create_individual_players_recorded({
		"player_id": "pending-mastery-player", "region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"player_task_ids": json.dumps([success_task_id]), "paths": json.dumps(["/tmp/pending.json"]),
		"mastery_status": "pending",
	})
	# faulty: no recorded paths
	factory.create_individual_players_recorded({
		"player_id": "no-paths-player", "region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"player_task_ids": json.dumps([success_task_id]), "paths": json.dumps([]),
		"mastery_status": "success", "mastery_task_id": success_mastery_id,
	})
	# faulty: references a player_task that failed
	factory.create_individual_players_recorded({
		"player_id": "failed-task-player", "region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"player_task_ids": json.dumps([failed_task_id]), "paths": json.dumps(["/tmp/failedtask.json"]),
		"mastery_status": "success", "mastery_task_id": success_mastery_id,
	})
	# faulty: missing rank info
	factory.create_individual_players_recorded({
		"player_id": "missing-rank-player", "region": "", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"player_task_ids": json.dumps([success_task_id]), "paths": json.dumps(["/tmp/missingrank.json"]),
		"mastery_status": "success", "mastery_task_id": success_mastery_id,
	})

	result = verify_integrity.verify_db_integrity()

	assert result["total_player_tasks"] == 2
	assert result["total_mastery_tasks"] == 2
	assert result["total_player_records"] == 5
	assert result["player_task_error_rate"] == "50.00%"
	assert result["mastery_task_error_rate"] == "50.00%"
	assert result["discarded_player_tasks"] == 1  # the failed task has no file_path

	faulty_ids = {record["player_id"] for record in result["faulty_records"]}
	assert faulty_ids == {"pending-mastery-player", "no-paths-player", "failed-task-player", "missing-rank-player"}
	assert result["faulty_records_count"] == 4
	assert "clean-player" not in faulty_ids

	log_file = tmp_path / "db_integrity_check.json"
	assert log_file.is_file()
	assert json.loads(log_file.read_text(encoding="utf-8")) == result
	conn.close()


def test_verify_files_integrity_detects_missing_and_duplicated_puuids(tmp_path, monkeypatch):
	players_dir = tmp_path / "players"
	masteries_dir = tmp_path / "masteries"
	logs_dir = tmp_path / "logs"
	players_dir.mkdir()
	masteries_dir.mkdir()
	logs_dir.mkdir()

	monkeypatch.setattr(verify_integrity, "PLAYERS_INPUT_PATH", players_dir)
	monkeypatch.setattr(verify_integrity, "MASTERIES_PATH", masteries_dir)
	monkeypatch.setattr(verify_integrity, "LOGS_PATH", logs_dir)

	# p1 appears in two player files (duplicated); p2 only in players (missing mastery)
	(players_dir / "file1.json").write_text(json.dumps({"players": [{"puuid": "p1"}, {"puuid": "p2"}]}), encoding="utf-8")
	(players_dir / "file2.json").write_text(json.dumps({"players": [{"puuid": "p1"}]}), encoding="utf-8")
	# a broken/empty player
	(players_dir / "broken.json").write_text(json.dumps({"players": []}), encoding="utf-8")

	# p1 has a matching mastery file; p3 has a mastery file but no player file (missing player)
	(masteries_dir / "m1.json").write_text(json.dumps({"masteries": [{"puuid": "p1"}]}), encoding="utf-8")
	(masteries_dir / "orphan.json").write_text(json.dumps({"masteries": [{"puuid": "p3"}]}), encoding="utf-8")

	result = verify_integrity.verify_files_integrity()

	assert result["total_player_files"] == 2  # unique puuids: p1, p2
	assert result["total_mastery_files"] == 2  # unique puuids: p1, p3

	missing_masteries_puuids = {entry["puuid"] for entry in result["missing_masteries"]}
	assert missing_masteries_puuids == {"p2"}

	missing_players_puuids = {entry["puuid"] for entry in result["missing_players"]}
	assert missing_players_puuids == {"p3"}

	assert "p1" in result["duplicated_players"]
	assert len(result["faulty_files"]) == 1

	log_file = logs_dir / "integrity_check.json"
	assert log_file.is_file()
	assert json.loads(log_file.read_text(encoding="utf-8")) == result