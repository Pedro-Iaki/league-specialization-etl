import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from extract import extraction_db_helper as db
from extract import init_extraction_db as init
from extract import run_pipeline as pipeline
from extract.tests import t_utilities as util


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    paths = {
        "DB_PATH": tmp_path / "database" / "extraction.db",
        "PLAYERS_DIR": tmp_path / "raw" / "players",
        "MASTERIES_DIR": tmp_path / "raw" / "masteries",
        "COMPACTED_DIR": tmp_path / "compacted",
    }
    for setting, path in paths.items():
        monkeypatch.setattr(init, setting, str(path))
    monkeypatch.setattr(init, "QUARANTINE_DIR", str(tmp_path / "quarantine"))
    schema = Path(__file__).resolve().parents[1] / "extraction_schemas.sql"
    monkeypatch.setattr(init, "SCHEMA_PATH", str(schema))
    get_connection = init.get_connection
    monkeypatch.setattr(init, "get_connection", lambda db_path=None: get_connection(db_path or str(paths["DB_PATH"])))
    db_connection = db.get_connection
    monkeypatch.setattr(db, "get_connection", lambda: db_connection(str(paths["DB_PATH"])))
    return paths


def test_initialization_creates_database_parent_and_preserves_existing_files(local_storage):
    raw = local_storage["PLAYERS_DIR"] / "collected.parquet"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"existing collection")

    init.initialize_database()

    assert all(path.is_dir() for setting, path in local_storage.items() if setting != "DB_PATH")
    assert raw.read_bytes() == b"existing collection"
    conn = init.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


def test_pipeline_repairs_missing_directory_without_resetting_ledger(
    local_storage, tmp_path, monkeypatch, pipeline_stub
):
    init.initialize_database()
    conn = init.get_connection()
    try:
        db.start_run("previous collection", conn=conn)
        conn.commit()
    finally:
        conn.close()
    local_storage["MASTERIES_DIR"].rmdir()
    compacted = local_storage["COMPACTED_DIR"] / "pending.parquet"
    compacted.write_bytes(b"pending ingestion")
    monkeypatch.setattr(init, "db_exists", lambda: False)
    util._clear_pipeline_env(monkeypatch)
    config = util.EnvFactory.create(tmp_path, "startup")

    assert pipeline.run_pipeline(config)

    conn = init.get_connection()
    try:
        assert conn.execute("SELECT pipeline_name FROM runs").fetchone()[0] == "previous collection"
    finally:
        conn.close()
    assert local_storage["MASTERIES_DIR"].is_dir()
    assert compacted.read_bytes() == b"pending ingestion"
    assert not list(local_storage["DB_PATH"].parent.glob("*.bak"))


def test_explicit_reset_still_backs_up_ledger_and_clears_files(local_storage):
    init.initialize_database()
    conn = init.get_connection()
    try:
        db.start_run("old collection", conn=conn)
        conn.commit()
    finally:
        conn.close()
    raw = local_storage["PLAYERS_DIR"] / "old.parquet"
    raw.write_bytes(b"old collection")

    init.reset_database()

    assert not raw.exists()
    assert len(list(local_storage["DB_PATH"].parent.glob("*.bak"))) == 1
    conn = init.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


def test_reconciliation_quarantines_orphans_and_is_repeatable(local_storage):
    init.initialize_database()
    for directory in (local_storage["PLAYERS_DIR"], local_storage["MASTERIES_DIR"]):
        orphan = directory / "date=260929" / "orphan.parquet"
        orphan.parent.mkdir()
        orphan.write_bytes(b"legacy data")
    compacted = local_storage["COMPACTED_DIR"] / "pending.parquet"
    compacted.write_bytes(b"awaiting ingestion")
    note = local_storage["PLAYERS_DIR"] / "note.txt"
    note.write_text("not a Parquet input")

    assert init.reconcile_raw_files() == 2

    quarantine = list(Path(init.QUARANTINE_DIR).iterdir())
    assert len(quarantine) == 1
    for dataset in ("players", "masteries"):
        assert (quarantine[0] / dataset / "date=260929" / "orphan.parquet").read_bytes() == b"legacy data"
        assert not (local_storage[f"{dataset.upper()}_DIR"] / "date=260929" / "orphan.parquet").exists()
    assert compacted.read_bytes() == b"awaiting ingestion"
    assert note.read_text() == "not a Parquet input"
    assert init.reconcile_raw_files() == 0
    assert len(list(Path(init.QUARANTINE_DIR).iterdir())) == 1


def test_reconciliation_preserves_all_ledger_references_even_if_files_are_old_or_broken(local_storage):
    init.initialize_database()
    paths = {
        "player_task": local_storage["PLAYERS_DIR"] / "old_task.parquet",
        "player_record": local_storage["PLAYERS_DIR"] / "old_record.parquet",
        "mastery_task": local_storage["MASTERIES_DIR"] / "old_mastery.parquet",
        "compaction": local_storage["PLAYERS_DIR"] / "old_compaction.parquet",
    }
    for path in paths.values():
        path.write_bytes(b"invalid Parquet that must remain for verification")
    conn = init.get_connection()
    try:
        run_id = db.start_run("previous work", conn=conn)
        player_task = db.add_player_task(run_id, conn=conn)
        db.update_player_task(player_task, "failed", file_path=str(paths["player_task"]), conn=conn)
        db.add_player_records(
            "p1", str(paths["player_record"]), player_task, "na1", "solo", "GOLD", "I", "16.19", conn=conn,
        )
        mastery_task = db.add_mastery_task(run_id, "p1", conn=conn)
        db.update_mastery_task(mastery_task, "success", "16.19", file_path=str(paths["mastery_task"]), conn=conn)
        conn.execute(
            "INSERT INTO compaction_tasks (dataset, output_path, paths_compressed) VALUES (?, ?, ?)",
            ("players", "compacted.parquet", json.dumps([str(paths["compaction"])])),
        )
        db.finish_run(run_id, "failed", conn=conn)
        conn.commit()
    finally:
        conn.close()

    assert init.reconcile_raw_files() == 0
    assert all(path.exists() for path in paths.values())
    assert not Path(init.QUARANTINE_DIR).exists()


def test_reconciliation_refuses_to_move_files_during_an_active_local_run(local_storage):
    init.initialize_database()
    orphan = local_storage["PLAYERS_DIR"] / "being_written.parquet"
    orphan.write_bytes(b"not registered yet")
    run_id = db.start_run("active collection")

    with pytest.raises(RuntimeError, match="running"):
        init.reconcile_raw_files()

    assert orphan.exists()
    assert not Path(init.QUARANTINE_DIR).exists()
    db.finish_run(run_id, "success")


def test_reconciliation_propagates_move_failure_without_removing_source(local_storage, monkeypatch):
    init.initialize_database()
    orphan = local_storage["PLAYERS_DIR"] / "orphan.parquet"
    orphan.write_bytes(b"preserve this")

    def denied(*args):
        raise PermissionError("file is locked")

    monkeypatch.setattr(Path, "rename", denied)
    with pytest.raises(PermissionError, match="locked"):
        init.reconcile_raw_files()
    assert orphan.read_bytes() == b"preserve this"


def test_startup_stops_before_api_client_when_reconciliation_fails(tmp_path, monkeypatch, pipeline_stub, caplog):
    util._clear_pipeline_env(monkeypatch)
    config = util.EnvFactory.create(tmp_path, "reconciliation_failure")

    def failed():
        raise OSError("cannot move orphan")

    def unexpected_client(**kwargs):
        pytest.fail("API client must not start after reconciliation failed")

    monkeypatch.setattr(init, "reconcile_raw_files", failed)
    monkeypatch.setattr(pipeline.client, "RiotAPIClient", unexpected_client)
    assert not pipeline.run_pipeline(config)
    assert pipeline_stub == {}
    assert "cannot move orphan" in caplog.text


def test_startup_reconciles_before_collection(tmp_path, monkeypatch, pipeline_stub):
    util._clear_pipeline_env(monkeypatch)
    config = util.EnvFactory.create(tmp_path, "reconciliation_order")
    calls = []
    monkeypatch.setattr(init, "reconcile_raw_files", lambda: calls.append("reconcile") or 0)
    monkeypatch.setattr(pipeline, "extraction_loop", lambda *args, **kwargs: calls.append("collect") or True)

    assert pipeline.run_pipeline(config)
    assert calls == ["reconcile", "collect"]


def test_new_run_has_a_heartbeat_before_its_first_task(mock_conn):
    run_id = db.start_run("new collection", conn=mock_conn)
    run = mock_conn.execute("SELECT started_at, last_heartbeat FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert run["last_heartbeat"] == run["started_at"]


def test_stale_cleanup_expires_legacy_null_heartbeat_only_when_started_long_ago(mock_conn):
    recent = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    for name, started_at, heartbeat in (
        ("stalled before first task", old, None),
        ("recent before first task", recent, None),
        ("active collection", old, recent),
    ):
        mock_conn.execute(
            "INSERT INTO runs (pipeline_name, started_at, last_heartbeat) VALUES (?, ?, ?)",
            (name, started_at, heartbeat),
        )

    db.cleanup_stale_runs(conn=mock_conn)

    statuses = {row["pipeline_name"]: row["status"] for row in mock_conn.execute("SELECT * FROM runs")}
    assert statuses == {
        "stalled before first task": "failed",
        "recent before first task": "running",
        "active collection": "running",
    }
