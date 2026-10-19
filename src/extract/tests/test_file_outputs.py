import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import extract.tests.t_utilities as util
from extract import compact_parquets, get_masteries, get_players

util.set_path_for_extract_modules()


def test_get_players_run_writes_file_and_records_players(tmp_path, mock_db, monkeypatch):
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    run_id = mock_db.start_run("file_output_players_test")
    client = util.FakeAPIClient(
        players_payload=[
            util.create_player_payload("p1"),
            util.create_player_payload("p2"),
        ],
        patch="15.1",
    )

    get_players.run(
        run_id,
        api_client=client,
        region="na1",
        queue="RANKED_SOLO_5x5",
        tier="GOLD",
        division="I",
    )

    conn = mock_db.get_connection()
    task = conn.execute("SELECT status, file_path FROM player_tasks WHERE run_id = ?", (run_id,)).fetchone()
    recorded = {row["player_id"] for row in conn.execute("SELECT player_id FROM players_recorded").fetchall()}
    conn.close()

    assert task["status"] == "success"
    assert task["file_path"] is not None
    util.assert_valid_player_file(Path(task["file_path"]), expected_puuids=["p1", "p2"])
    assert recorded == {"p1", "p2"}


def test_get_players_run_skips_local_pending_players_until_ingestion(tmp_path, mock_db, monkeypatch):
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    previous_run = mock_db.start_run("already collected")
    previous_task = mock_db.add_player_task(previous_run)
    mock_db.update_player_task(previous_task, "success", file_path="existing.parquet")
    mock_db.add_player_records(
        "p1", "existing.parquet", previous_task, "na1", "RANKED_SOLO_5x5", "GOLD", "I", "15.1",
    )
    completed = []
    released = []
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda *args: completed.append(args))
    monkeypatch.setattr(get_players.player_registry, "release_rank_page", lambda token: released.append(token))
    run_id = mock_db.start_run("repeat snapshot")

    client = util.FakeAPIClient(players_payload=[util.create_player_payload("p1")], patch="15.1")
    get_players.run(
        run_id,
        api_client=client,
        region="na1",
        queue="RANKED_SOLO_5x5",
        tier="GOLD",
        division="I",
    )

    conn = mock_db.get_connection()
    task = conn.execute("SELECT status, file_path FROM player_tasks WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()

    assert task["status"] == "success"
    assert task["file_path"] is None
    assert list(tmp_path.rglob("*.parquet")) == []
    assert completed == []
    assert released == ["test-claim"]

    mock_db.update_load_status("players", [{"puuid": "p1", "region": "na1", "queueType": "RANKED_SOLO_5x5"}], "load_success")
    monkeypatch.setattr(get_players, "get_fresh_players", lambda *args, **kwargs: [{"puuid": "p1"}])
    get_players.run(mock_db.start_run("after ingestion"), client, "na1", "RANKED_SOLO_5x5", tier="GOLD", division="I")
    assert completed == [("test-claim", 1)]
    assert list(tmp_path.rglob("*.parquet")) == []


def test_snapshot_filters_individual_local_players_but_keeps_stale_and_failed_work(tmp_path, mock_db, monkeypatch):
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    previous_run = mock_db.start_run("previous snapshot")
    previous_task = mock_db.add_player_task(previous_run)
    mock_db.update_player_task(previous_task, "success", file_path="existing.parquet")
    for player in ("local", "stale", "failed", "other_queue"):
        mock_db.add_player_records(
            player, "existing.parquet", previous_task, "na1",
            "RANKED_FLEX_SR" if player == "other_queue" else "RANKED_SOLO_5x5", "GOLD", "I", "15.1",
        )
    conn = mock_db.get_connection()
    try:
        conn.execute("UPDATE players_recorded SET paths_logged_at = json_array(datetime('now', '-61 minutes')) WHERE player_id = 'stale'")
        conn.execute("UPDATE players_recorded SET mastery_status = 'failed' WHERE player_id = 'failed'")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(get_players, "get_fresh_players", lambda *args, **kwargs: [{"puuid": "remote"}])
    client = util.FakeAPIClient(
        players_payload=[util.create_player_payload(p) for p in ("remote", "local", "stale", "failed", "other_queue", "new")],
        patch="15.1",
    )
    run_id = mock_db.start_run("mixed snapshot")

    observed = get_players.run(run_id, client, "na1", "RANKED_SOLO_5x5", tier="GOLD", division="I", freshness_minutes=60)

    assert observed == 6
    conn = mock_db.get_connection()
    try:
        task = conn.execute("SELECT file_path, rank_page_claim FROM player_tasks WHERE run_id = ?", (run_id,)).fetchone()
        assert json.loads(conn.execute("SELECT paths FROM players_recorded WHERE player_id = 'local'").fetchone()[0]) == ["existing.parquet"]
        assert conn.execute("SELECT 1 FROM players_recorded WHERE player_id = 'remote'").fetchone() is None
    finally:
        conn.close()
    util.assert_valid_player_file(Path(task["file_path"]), expected_puuids=["stale", "failed", "other_queue", "new"])
    assert json.loads(task["rank_page_claim"])["player_count"] == 6


def test_get_masteries_run_writes_file_and_updates_status(tmp_path, mock_db, db_factory, monkeypatch):
    monkeypatch.setattr(get_masteries, "OUTPUT_PATH", tmp_path)
    conn = mock_db.get_connection()
    factory = db_factory(conn)
    run_id = factory.create_individual_run()
    puuid = factory.get_uuid()
    recent = datetime.now(timezone.utc).isoformat()
    factory.create_individual_players_recorded(
        {
            "player_id": puuid,
            "region": "na1",
            "queue": "RANKED_SOLO_5x5",
            "tier": "GOLD",
            "division": "I",
            "paths_logged_at": json.dumps([recent]),
            "mastery_status": "pending",
            "mastery_logged_at": None,
        }
    )
    conn.close()

    client = util.FakeAPIClient(
        masteries_payload=[util.create_mastery_payload(puuid, champion_id=99)],
        patch="15.1",
    )
    get_masteries.run(run_id, api_client=client, limit=10)

    conn = mock_db.get_connection()
    record = conn.execute(
        "SELECT mastery_status, mastery_path, mastery_patch FROM players_recorded WHERE player_id = ?",
        (puuid,),
    ).fetchone()
    conn.close()

    assert record["mastery_status"] == "success"
    assert record["mastery_patch"] == "15.1"
    output_path = Path(record["mastery_path"])
    assert output_path.is_file()

    table = pq.read_table(output_path)
    assert table["puuid"].to_pylist()[0] == puuid


def test_compact_dataset_players_merges_and_marks_pending_load(tmp_path, mock_db, db_factory, monkeypatch):
    compact_dir = tmp_path / "data" / "compacted"
    monkeypatch.setattr(compact_parquets, "COMPACTED_DIR", compact_dir)

    file1 = tmp_path / "part1.parquet"
    file2 = tmp_path / "part2.parquet"
    pq.write_table(pa.table({"puuid": ["p1", "p2"]}), file1)
    pq.write_table(pa.table({"puuid": ["p2", "p3"]}), file2)

    conn = mock_db.get_connection()
    factory = db_factory(conn)
    factory.create_individual_players_recorded({"player_id": "p1", "paths": json.dumps([str(file1)])})
    factory.create_individual_players_recorded({"player_id": "p2", "paths": json.dumps([str(file2)])})
    factory.create_individual_players_recorded({"player_id": "p3", "paths": json.dumps([str(file2)])})
    conn.close()

    summary = compact_parquets.compact_dataset("players")

    assert summary == {"records_scanned": 3, "records_compacted": 3, "files_merged": 2, "rows_written": 3}
    output_path = compact_dir / compact_parquets.COMPACTED_FILENAMES["players"]
    assert sorted(pq.read_table(output_path)["puuid"].to_pylist()) == ["p1", "p2", "p3"]
    assert file1.is_file() and file2.is_file()  # raw files are left in place; deletion belongs to the load step

    conn = mock_db.get_connection()
    rows = {
        row["player_id"]: (row["player_load_status"], row["latest_player_compacted_path"])
        for row in conn.execute(
            "SELECT player_id, player_load_status, latest_player_compacted_path FROM players_recorded"
        )
    }
    conn.close()
    for player_id in ("p1", "p2", "p3"):
        assert rows[player_id] == ("pending_load", str(output_path))


def test_compact_dataset_masteries_merges_and_marks_pending_load(tmp_path, mock_db, db_factory, monkeypatch):
    compact_dir = tmp_path / "data" / "compacted"
    monkeypatch.setattr(compact_parquets, "COMPACTED_DIR", compact_dir)

    file1 = tmp_path / "mastery1.parquet"
    pq.write_table(pa.table({"puuid": ["p1"], "championId": [99]}), file1)

    conn = mock_db.get_connection()
    factory = db_factory(conn)
    run_id = factory.create_individual_run()
    factory.create_individual_mastery_task({"run_id": run_id, "player_id": "p1", "file_path": str(file1)})
    factory.create_individual_players_recorded(
        {"player_id": "p1", "mastery_status": "success", "mastery_path": str(file1)}
    )
    conn.close()

    summary = compact_parquets.compact_dataset("masteries")

    assert summary == {"records_scanned": 1, "records_compacted": 1, "files_merged": 1, "rows_written": 1}
    output_path = compact_dir / compact_parquets.COMPACTED_FILENAMES["masteries"]
    assert pq.read_table(output_path)["puuid"].to_pylist() == ["p1"]

    conn = mock_db.get_connection()
    row = conn.execute(
        "SELECT mastery_load_status, mastery_compacted_path FROM players_recorded WHERE player_id = ?", ("p1",)
    ).fetchone()
    conn.close()
    assert row["mastery_load_status"] == "pending_load"
    assert row["mastery_compacted_path"] == str(output_path)


def test_compact_dataset_skips_missing_file_but_compacts_rest(tmp_path, mock_db, db_factory, monkeypatch):
    compact_dir = tmp_path / "data" / "compacted"
    monkeypatch.setattr(compact_parquets, "COMPACTED_DIR", compact_dir)

    file1 = tmp_path / "part1.parquet"
    pq.write_table(pa.table({"puuid": ["p1"]}), file1)
    missing_file = tmp_path / "does_not_exist.parquet"

    conn = mock_db.get_connection()
    factory = db_factory(conn)
    factory.create_individual_players_recorded({"player_id": "p1", "paths": json.dumps([str(file1)])})
    factory.create_individual_players_recorded({"player_id": "p2", "paths": json.dumps([str(missing_file)])})
    conn.close()

    summary = compact_parquets.compact_dataset("players")

    assert summary["records_scanned"] == 2
    assert summary["records_compacted"] == 1

    conn = mock_db.get_connection()
    rows = {
        row["player_id"]: row["player_load_status"]
        for row in conn.execute("SELECT player_id, player_load_status FROM players_recorded")
    }
    conn.close()
    assert rows["p1"] == "pending_load"
    assert rows["p2"] == "pending_compaction"


def test_compact_dataset_is_idempotent(tmp_path, mock_db, db_factory, monkeypatch):
    compact_dir = tmp_path / "data" / "compacted"
    monkeypatch.setattr(compact_parquets, "COMPACTED_DIR", compact_dir)

    file1 = tmp_path / "part1.parquet"
    pq.write_table(pa.table({"puuid": ["p1"]}), file1)

    conn = mock_db.get_connection()
    factory = db_factory(conn)
    factory.create_individual_players_recorded({"player_id": "p1", "paths": json.dumps([str(file1)])})
    conn.close()

    first = compact_parquets.compact_dataset("players")
    second = compact_parquets.compact_dataset("players")

    assert first["records_compacted"] == 1
    assert second == {"records_scanned": 0, "records_compacted": 0, "files_merged": 0, "rows_written": 0}


def test_get_masteries_run_marks_task_failed_on_error_response(tmp_path, mock_db, db_factory, monkeypatch):
    monkeypatch.setattr(get_masteries, "OUTPUT_PATH", tmp_path)

    conn = mock_db.get_connection()
    factory = db_factory(conn)
    run_id = factory.create_individual_run()
    puuid = factory.get_uuid()
    recent = datetime.now(timezone.utc).isoformat()
    factory.create_individual_players_recorded(
        {
            "player_id": puuid,
            "region": "na1",
            "queue": "RANKED_SOLO_5x5",
            "tier": "GOLD",
            "division": "I",
            "paths_logged_at": json.dumps([recent]),
            "mastery_status": "pending",
            "mastery_logged_at": None,
        }
    )
    conn.close()

    client = util.FakeAPIClient(masteries_payload=[], patch="15.1", status_code=500)
    get_masteries.run(run_id, api_client=client, limit=10)

    conn = mock_db.get_connection()
    task = conn.execute("SELECT status FROM mastery_tasks WHERE run_id = ?", (run_id,)).fetchone()
    record = conn.execute(
        "SELECT mastery_status, mastery_path FROM players_recorded WHERE player_id = ?",
        (puuid,),
    ).fetchone()
    conn.close()

    assert task["status"] == "failed"
    assert record["mastery_status"] == "failed"
    assert record["mastery_path"] is None
    assert list(tmp_path.rglob("*.parquet")) == []
