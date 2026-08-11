import json
from datetime import datetime, timezone
from pathlib import Path

import get_masteries
import get_players
import extraction_db_helper as db
import t_utilities as util

util.set_path_for_extract_modules()

def test_get_players_run_writes_file_and_records_players(tmp_path, mock_db, monkeypatch):
	monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
	run_id = mock_db.start_run("file_output_players_test")
	client = util.FakeAPIClient(players_payload=[util.create_player_payload("p1"), util.create_player_payload("p2")], patch="15.1")

	get_players.run(run_id, api_client=client, region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I")

	conn = mock_db.get_connection()
	task = conn.execute("SELECT status, file_path FROM player_tasks WHERE run_id = ?", (run_id,)).fetchone()
	recorded = {row["player_id"] for row in conn.execute("SELECT player_id FROM players_recorded").fetchall()}
	conn.close()

	assert task["status"] == "success"
	assert task["file_path"] is not None
	util.assert_valid_player_file(
		Path(task["file_path"]),
		region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I", patch="15.1",
		expected_puuids=["p1", "p2"],
	)
	assert recorded == {"p1", "p2"}


def test_get_players_run_skips_writing_file_when_no_new_players(tmp_path, mock_db, db_factory, monkeypatch):
	monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
	conn = mock_db.get_connection()
	factory = db_factory(conn)
	run_id = factory.create_individual_run()
	factory.create_individual_players_recorded({
		"player_id": "p1", "region": "na1", "queue": "RANKED_SOLO_5x5",
		"tier": "GOLD", "division": "I", "mastery_patch": "15.1",
	})
	conn.close()

	client = util.FakeAPIClient(players_payload=[util.create_player_payload("p1")], patch="15.1")
	get_players.run(run_id, api_client=client, region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I")

	conn = mock_db.get_connection()
	task = conn.execute("SELECT status, file_path FROM player_tasks WHERE run_id = ?", (run_id,)).fetchone()
	conn.close()

	assert task["status"] == "success"
	assert task["file_path"] is None
	assert list(tmp_path.rglob("*.json")) == []


def test_get_masteries_run_writes_file_and_updates_status(tmp_path, mock_db, db_factory, monkeypatch):
	monkeypatch.setattr(get_masteries, "OUTPUT_PATH", tmp_path)
	conn = mock_db.get_connection()
	factory = db_factory(conn)
	run_id = factory.create_individual_run()
	puuid = factory.get_uuid()
	recent = datetime.now(timezone.utc).isoformat()
	factory.create_individual_players_recorded({
		"player_id": puuid,
		"region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"paths_logged_at": json.dumps([recent]),
		"mastery_status": "pending",
		"mastery_logged_at": None,
	})
	conn.close()

	client = util.FakeAPIClient(masteries_payload=[util.create_mastery_payload(puuid, champion_id=99)], patch="15.1")
	get_masteries.run(run_id, api_client=client, limit=10)

	conn = mock_db.get_connection()
	record = conn.execute("SELECT mastery_status, mastery_path, mastery_patch FROM players_recorded WHERE player_id = ?", (puuid,)).fetchone()
	conn.close()

	assert record["mastery_status"] == "success"
	assert record["mastery_patch"] == "15.1"
	output_path = Path(record["mastery_path"])
	assert output_path.is_file()

	payload = json.loads(output_path.read_text(encoding="utf-8"))
	assert payload["puuid"] == puuid
	assert payload["region"] == "na1"
	assert payload["masteries"] == [util.create_mastery_payload(puuid, champion_id=99)]


def test_get_masteries_run_marks_task_failed_on_error_response(tmp_path, mock_db, db_factory, monkeypatch):
	monkeypatch.setattr(get_masteries, "OUTPUT_PATH", tmp_path)

	conn = mock_db.get_connection()
	factory = db_factory(conn)
	run_id = factory.create_individual_run()
	puuid = factory.get_uuid()
	recent = datetime.now(timezone.utc).isoformat()
	factory.create_individual_players_recorded({
		"player_id": puuid,
		"region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
		"paths_logged_at": json.dumps([recent]),
		"mastery_status": "pending",
		"mastery_logged_at": None,
	})
	conn.close()

	client = util.FakeAPIClient(masteries_payload=[], patch="15.1", status_code=500)
	get_masteries.run(run_id, api_client=client, limit=10)

	conn = mock_db.get_connection()
	task = conn.execute("SELECT status FROM mastery_tasks WHERE run_id = ?", (run_id,)).fetchone()
	record = conn.execute("SELECT mastery_status, mastery_path FROM players_recorded WHERE player_id = ?", (puuid,)).fetchone()
	conn.close()

	assert task["status"] == "failed"
	assert record["mastery_status"] == "failed"
	assert record["mastery_path"] is None
	assert list(tmp_path.rglob("*.json")) == []