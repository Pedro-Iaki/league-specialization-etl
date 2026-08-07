import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import t_utilities as util

util.set_path_for_extract_modules()
import get_players
import get_masteries
import pipeline_db as db

TIERS = ["GOLD", "SILVER", "BRONZE", "PLATINUM", "DIAMOND"]


class SteadyClient:
	def get_patch(self):
		return "15.1"

	def get(self, url, **kwargs):
		return util.FakeResponse([util.create_player_payload("steady-p1"), util.create_player_payload("steady-p2")])


def _run_get_players(run_id: int, tier: str):
	fake_client = _TierClient(tier)
	get_players.run(run_id, api_client=fake_client, region="na1", queue="RANKED_SOLO_5x5", tier=tier, division="I")
	return tier


class _TierClient:
	def __init__(self, tier: str):
		self.tier = tier

	def get_patch(self):
		return "15.1"

	def get(self, url, **kwargs):
		tier_key = self.tier.lower()
		return util.FakeResponse([util.create_player_payload(f"{tier_key}-p1"), util.create_player_payload(f"{tier_key}-p2")])


def test_concurrent_get_players_runs_do_not_corrupt_files_or_database(tmp_path, mock_db, monkeypatch):
	monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
	run_id = mock_db.start_run("multi_thread_test")

	with ThreadPoolExecutor(max_workers=len(TIERS)) as executor:
		futures = [executor.submit(_run_get_players, run_id, tier) for tier in TIERS]
		completed_tiers = [future.result() for future in as_completed(futures)]

	assert set(completed_tiers) == set(TIERS)

	conn = mock_db.get_connection()
	tasks = conn.execute("SELECT status, file_path FROM player_tasks WHERE run_id = ?", (run_id,)).fetchall()
	recorded = {row["player_id"] for row in conn.execute("SELECT player_id FROM players_recorded").fetchall()}
	conn.close()

	assert len(tasks) == len(TIERS)
	assert all(task["status"] == "success" for task in tasks)
	assert all(task["file_path"] is not None for task in tasks)
	for task in tasks:
		assert Path(task["file_path"]).is_file()

	expected_players = {f"{tier.lower()}-p1" for tier in TIERS} | {f"{tier.lower()}-p2" for tier in TIERS}
	assert recorded == expected_players

	all_files = list(tmp_path.rglob("players_I_*.json"))
	assert len(all_files) == len(TIERS)

	found_tiers = set()
	for file in all_files:
		tier = json.loads(file.read_text(encoding="utf-8"))["tier"]
		util.assert_valid_player_file(
			file, region="na1", queue="RANKED_SOLO_5x5", tier=tier, division="I", patch="15.1",
			expected_puuids=[f"{tier.lower()}-p1", f"{tier.lower()}-p2"],
		)
		found_tiers.add(tier)
	assert found_tiers == set(TIERS)


def test_concurrent_fetch_players_same_division_keeps_page_consistent(mock_db, db_factory):
	run_id = mock_db.start_run("multi_thread_paging_test")
	worker_count = 8

	def _worker():
		task_id = mock_db.add_player_task(run_id)
		return get_players.fetch_players(task_id, SteadyClient(), region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="IV", patch="15.1")

	with ThreadPoolExecutor(max_workers=worker_count) as executor:
		futures = [executor.submit(_worker) for _ in range(worker_count)]
		results = [future.result() for future in as_completed(futures)]

	assert all(result is not None and len(result) == 2 for result in results)

	page, loop = mock_db.get_page_and_loop("na1", "RANKED_SOLO_5x5", "GOLD", "IV", "15.1")
	assert 2 <= page <= 1 + worker_count
	assert loop == 0


def _seed_pending_players(mock_db, db_factory, count: int) -> list[str]:
	conn = mock_db.get_connection()
	factory = db_factory(conn)
	recent = datetime.now(timezone.utc).isoformat()
	puuids = []
	for _ in range(count):
		puuid = factory.get_uuid()
		factory.create_individual_players_recorded({
			"player_id": puuid,
			"region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I",
			"paths_logged_at": json.dumps([recent]),
			"mastery_status": "pending",
			"mastery_logged_at": None,
		})
		puuids.append(puuid)
	conn.close()
	return puuids


def test_concurrent_get_masteries_do_not_process_the_same_player_twice(tmp_path, mock_db, db_factory, monkeypatch):
	monkeypatch.setattr(get_masteries, "OUTPUT_PATH", tmp_path)
	run_id = mock_db.start_run("multi_thread_masteries_test")

	player_count = 12
	worker_count = 4
	seeded_puuids = _seed_pending_players(mock_db, db_factory, player_count)

	client = util.FakeAPIClient(masteries_payload=[util.create_mastery_payload("shared", champion_id=1)], patch="15.1")

	def _worker():
		get_masteries.run(run_id, api_client=client, limit=player_count)

	with ThreadPoolExecutor(max_workers=worker_count) as executor:
		futures = [executor.submit(_worker) for _ in range(worker_count)]
		for future in as_completed(futures):
			future.result()

	conn = mock_db.get_connection()
	records = conn.execute(
		"SELECT player_id, mastery_status FROM players_recorded WHERE player_id IN ({seq})".format(
			seq=",".join(["?"] * len(seeded_puuids))
		),
		seeded_puuids,
	).fetchall()
	conn.close()

	assert {row["player_id"] for row in records} == set(seeded_puuids)
	assert all(row["mastery_status"] == "success" for row in records)

	mastery_files = list(tmp_path.rglob("masteries_*.json"))
	assert len(mastery_files) == player_count


def test_concurrent_update_mastery_task_matches_records(mock_db, db_factory):

	worker_count = 6
	puuids = []
	task_ids = []
	conn = mock_db.get_connection()
	factory = db_factory(conn)
	for i in range(worker_count):
		run_id = factory.create_individual_run()
		puuid = factory.get_uuid()
		puuids.append(puuid)
		task_id = factory.create_individual_mastery_task({"run_id": run_id, "player_id": puuid, "status": "pending"})
		task_ids.append(task_id)
		factory.create_individual_players_recorded({"player_id": puuid, "mastery_status": "pending"})
	conn.close()

	def _worker(i: int):
		puuid = puuids[i] 
		status = "success" if i % 2 == 0 else "failed"
		mock_db.update_mastery_task(
			task_ids[i], status, "15.1",
			file_path=f"/tmp/mastery_{puuid}_{i}.json" if status == "success" else None,
			error_message=None if status == "success" else "simulated failure"
		)

	with ThreadPoolExecutor(max_workers=worker_count) as executor:
		futures = [executor.submit(_worker, i) for i in range(worker_count)]
		for future in as_completed(futures):
			future.result()

	conn = mock_db.get_connection()
	tasks = conn.execute("SELECT status, file_path FROM mastery_tasks WHERE task_id IN ({seq})".format(
		seq=",".join(["?"] * len(task_ids))
	), task_ids).fetchall()
	records = conn.execute("SELECT mastery_status, mastery_path FROM players_recorded WHERE player_id IN ({seq})".format(
		seq=",".join(["?"] * len(puuids))
	), puuids).fetchall()
	conn.close()
 
	assert len(tasks) == len(records) == worker_count
	matches_found = 0
	for task in tasks:
		found = False
		for record in records:
			if record["mastery_path"] == task["file_path"]:
				found = True
				assert task["status"] == record["mastery_status"]
		if found:
			matches_found += 1
	assert matches_found == worker_count