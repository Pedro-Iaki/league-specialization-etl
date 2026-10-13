import errno
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from extract import compact_parquets as compact
from extract import run_pipeline as pipeline
from extract import verify_integrity as verify


@pytest.fixture
def collection(tmp_path, mock_db, monkeypatch):
    raw_dir = tmp_path / "raw"
    compacted_dir = tmp_path / "compacted"
    monkeypatch.setattr(compact, "RAW_DIR", raw_dir)
    monkeypatch.setattr(compact, "COMPACTED_DIR", compacted_dir)
    monkeypatch.setattr(compact.compact_dataset.retry, "sleep", lambda seconds: None)
    monkeypatch.setattr(verify, "PLAYERS_INPUT_PATH", raw_dir / "players")
    monkeypatch.setattr(verify, "MASTERIES_PATH", raw_dir / "masteries")
    monkeypatch.setattr(verify, "LOGS_PATH", tmp_path / "logs")

    def add_player(puuid):
        run_id = mock_db.start_run("compaction_test")
        player_path = raw_dir / "players" / f"{puuid}.parquet"
        mastery_path = raw_dir / "masteries" / f"{puuid}.parquet"
        player_path.parent.mkdir(parents=True, exist_ok=True)
        mastery_path.parent.mkdir(parents=True, exist_ok=True)
        rank = {"puuid": puuid, "region": "na1", "queueType": "solo", "wins": 3, "losses": 2}
        pq.write_table(pa.Table.from_pylist([rank]), player_path)
        pq.write_table(pa.Table.from_pylist([{**rank, "championId": champion} for champion in (1, 2)]), mastery_path)
        player_task = mock_db.add_player_task(run_id)
        mock_db.update_player_task(player_task, "success", file_path=str(player_path))
        mock_db.add_player_records(puuid, str(player_path), player_task, "na1", "solo", "GOLD", "I", "15.1")
        mastery_task = mock_db.add_mastery_task(run_id, puuid)
        mock_db.update_mastery_task(mastery_task, "success", "15.1", file_path=str(mastery_path))
        mock_db.finish_run(run_id, "success")
        return rank

    add_player("p1")
    return add_player


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "missing",
        "unreadable",
        "missing_player",
        "missing_column",
        "missing_champion",
        "pending",
        "missing_source",
        "failed_task",
        "missing_reference",
    ],
)
def test_runner_checks_compacted_output_before_any_upload(collection, tmp_path, monkeypatch, damage):
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "run_snapshot_fetchers", lambda *args: {"status": "success", "snapshot_size": 100})
    monkeypatch.setattr(pipeline, "run_stale_refresh", lambda *args: {"status": True})
    uploads = []
    cleared = []
    monkeypatch.setattr(pipeline, "run_load", lambda: uploads.append(True) or {"status": True})
    monkeypatch.setattr(pipeline.db, "count_incomplete_loads", lambda: 0)
    monkeypatch.setattr(pipeline, "reset_local_data", lambda: cleared.append(True))
    real_compact = compact.run

    def compact_and_damage():
        if damage == "missing_source":
            collection("p2")
            (compact.RAW_DIR / "players" / "p2.parquet").unlink()
        real_compact()
        output = compact.COMPACTED_DIR / compact.COMPACTED_FILENAMES["players"]
        if damage == "missing":
            output.unlink()
        elif damage == "unreadable":
            output.write_bytes(b"broken parquet")
        elif damage == "missing_player":
            table = pq.read_table(output)
            pq.write_table(table.set_column(0, "puuid", pa.array(["another-player"])), output)
        elif damage == "missing_column":
            pq.write_table(pq.read_table(output).drop(["losses"]), output)
        elif damage == "missing_champion":
            output = compact.COMPACTED_DIR / compact.COMPACTED_FILENAMES["masteries"]
            pq.write_table(pq.read_table(output).slice(0, 1), output)
        elif damage == "pending":
            collection("p2")
        elif damage in ("failed_task", "missing_reference"):
            conn = compact.db.get_connection()
            try:
                if damage == "failed_task":
                    conn.execute("UPDATE compaction_tasks SET status = 'failed' WHERE dataset = 'players'")
                else:
                    conn.execute("UPDATE players_recorded SET latest_player_compacted_task_id = NULL")
                conn.commit()
            finally:
                conn.close()

    monkeypatch.setattr(compact, "run", compact_and_damage)
    result = pipeline.extraction_loop(
        {"players_fetch_depth": 2, "tiers": ["GOLD"], "divisions": ["I"], "runs_per_load": 1, "full_check": False,
         "region": "na1", "queue": "solo", "freshness_threshold_minutes": 10080, "stale_claim_timeout_minutes": 30,
         "max_refresh_scale": 4},
        api_client=object(),
    )
    assert result is (damage is None)
    assert uploads == ([True] if damage is None else [])
    assert cleared == ([True] if damage is None else [])
    assert (tmp_path / "raw" / "players" / "p1.parquet").exists()
    assert (tmp_path / "logs" / "compaction_integrity_check.json").exists()


def test_completed_tasks_do_not_require_deleted_outputs(collection, mock_db):
    compact.run()
    player = {"puuid": "p1", "region": "na1", "queueType": "solo"}
    for dataset, filename in compact.COMPACTED_FILENAMES.items():
        mock_db.update_load_status(dataset, [player], "load_success")
        (compact.COMPACTED_DIR / filename).unlink()
    report = verify.verify_compaction_integrity()
    assert report["tasks_checked"] == 0
    assert verify.is_load_ready({"database": {"faulty_records_count": 0}, "compaction": report})


def test_cumulative_output_uses_latest_row_count(collection):
    compact.run()
    collection("p2")
    compact.run()
    report = verify.verify_compaction_integrity()
    assert report["tasks_checked"] == 4
    assert report["task_level_issues_count"] == 0


@pytest.mark.parametrize("failure", ["write", "sharing", "ledger"])
def test_transient_compaction_failure_retries_without_losing_data(collection, mock_db, monkeypatch, failure):
    output = compact.COMPACTED_DIR / compact.COMPACTED_FILENAMES["players"]
    output.parent.mkdir(parents=True)
    old_rank = {"puuid": "old", "region": "na1", "queueType": "solo", "wins": 1, "losses": 0}
    pq.write_table(pa.Table.from_pylist([old_rank]), output)
    calls = []
    real_write = pq.write_table
    real_update = mock_db.update_compaction_task

    def flaky_write(table, path, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            path.write_bytes(b"partial file")
            assert pq.read_table(output)["puuid"].to_pylist() == ["old"]
            if failure == "sharing":
                error = PermissionError(errno.EACCES, "file in use")
                error.winerror = 32
                raise error
            raise OSError(errno.EAGAIN, "temporary file error")
        real_write(table, path, **kwargs)

    def flaky_ledger(task_id, status, **kwargs):
        if status == "success":
            calls.append(task_id)
            if len(calls) == 1:
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error
        real_update(task_id, status, **kwargs)

    if failure in ("write", "sharing"):
        monkeypatch.setattr(pq, "write_table", flaky_write)
    else:
        monkeypatch.setattr(mock_db, "update_compaction_task", flaky_ledger)
    result = compact.compact_dataset("players")
    assert 2 <= len(calls) <= compact.MAX_COMPACTION_ATTEMPTS
    assert result["records_compacted"] == 1
    assert sorted(pq.read_table(output)["puuid"].to_pylist()) == ["old", "p1"]
    assert not output.with_suffix(".tmp").exists()
    conn = mock_db.get_connection()
    try:
        statuses = [row[0] for row in conn.execute("SELECT status FROM compaction_tasks ORDER BY task_id")]
        assert statuses[-1] == "success"
        assert all(status == "failed" for status in statuses[:-1])
    finally:
        conn.close()


def test_exhausted_retries_leave_raw_records_pending(collection, mock_db, monkeypatch):
    attempts = []

    def failed_write(table, path, **kwargs):
        attempts.append(path)
        path.write_bytes(b"partial")
        raise OSError(errno.EBUSY, "disk busy")

    monkeypatch.setattr(pq, "write_table", failed_write)
    with pytest.raises(RuntimeError, match="retaining local files"):
        compact.run()
    assert len(attempts) == compact.MAX_COMPACTION_ATTEMPTS
    conn = mock_db.get_connection()
    try:
        assert conn.execute("SELECT player_load_status FROM players_recorded").fetchone()[0] == "pending_compaction"
        assert all(row[0] == "failed" for row in conn.execute("SELECT status FROM compaction_tasks"))
    finally:
        conn.close()
    assert not (compact.COMPACTED_DIR / compact.COMPACTED_FILENAMES["players"]).exists()
    assert list(compact.COMPACTED_DIR.glob("*.tmp")) == []
    assert (compact.RAW_DIR / "players" / "p1.parquet").exists()


def test_corrupt_source_is_reported_and_not_retried(collection, mock_db):
    source = compact.RAW_DIR / "players" / "p1.parquet"
    source.write_bytes(b"broken")
    report = verify.verify_files_integrity()
    assert {entry["source_file"] for entry in report["faulty_files"]} == {str(source)}
    with pytest.raises(RuntimeError, match="Compaction failed"):
        compact.run()
    conn = mock_db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM compaction_tasks").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM compaction_tasks").fetchone()[0] == "failed"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError(errno.ENOENT, "source missing"),
        PermissionError(errno.EACCES, "write denied"),
        sqlite3.OperationalError("no such table: missing_table"),
    ],
)
def test_permanent_compaction_failure_stops_without_retry(collection, mock_db, monkeypatch, failure):
    attempts = []
    real_update = mock_db.update_compaction_task

    def failed_write(*args, **kwargs):
        attempts.append(True)
        raise failure

    def failed_completion(task_id, status, **kwargs):
        if status == "success":
            failed_write()
        real_update(task_id, status, **kwargs)

    if isinstance(failure, sqlite3.OperationalError):
        monkeypatch.setattr(mock_db, "update_compaction_task", failed_completion)
    else:
        monkeypatch.setattr(pq, "write_table", failed_write)

    with pytest.raises(type(failure)):
        compact.compact_dataset("players")
    assert len(attempts) == 1
    conn = mock_db.get_connection()
    try:
        assert conn.execute("SELECT player_load_status FROM players_recorded").fetchone()[0] == "pending_compaction"
        assert conn.execute("SELECT status FROM compaction_tasks").fetchone()[0] == "failed"
    finally:
        conn.close()


def test_compaction_helper_keeps_caller_transaction_and_connection(collection, mock_db):
    conn = mock_db.get_connection()
    try:
        task_id = mock_db.add_compaction_task("players", "output.parquet", conn=conn)
        conn.commit()
        mock_db.complete_compaction_task(
            task_id, "players", ["p1"], "output.parquet", ["source.parquet"], 1, conn=conn,
        )
        assert conn.execute("SELECT status FROM compaction_tasks").fetchone()[0] == "success"
        conn.rollback()
        assert conn.execute("SELECT status FROM compaction_tasks").fetchone()[0] == "pending"
        assert conn.execute("SELECT player_load_status FROM players_recorded").fetchone()[0] == "pending_compaction"
    finally:
        conn.close()


def test_compaction_verification_closes_connection_when_query_fails(collection, mock_db, monkeypatch):
    conn = mock_db.get_connection()
    conn.execute("DROP TABLE compaction_tasks")
    conn.commit()
    monkeypatch.setattr(verify.db, "get_connection", lambda: conn)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        verify.verify_compaction_integrity()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")
