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
    schema = Path(__file__).resolve().parents[1] / "extraction_schemas.sql"
    monkeypatch.setattr(init, "SCHEMA_PATH", str(schema))
    get_connection = init.get_connection
    monkeypatch.setattr(init, "get_connection", lambda db_path=None: get_connection(db_path or str(paths["DB_PATH"])))
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
