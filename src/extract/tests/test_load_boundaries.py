import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import extract.run_pipeline as pipeline
import load.load_compacted_to_databricks as loader


@pytest.mark.parametrize("load_status,pending_count", [(False, 0), (True, 1)])
def test_legacy_runner_retains_files_when_load_is_incomplete(tmp_path, monkeypatch, load_status, pending_count):
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "run_snapshot_fetchers", lambda *args: True)
    monkeypatch.setattr(pipeline, "run_stale_refresh", lambda *args: {"status": True})
    monkeypatch.setattr(pipeline.verify, "run_integrity_check", lambda full: {"database": {"faulty_records_count": 0}})
    monkeypatch.setattr(pipeline.compact, "run", lambda: None)
    monkeypatch.setattr(pipeline, "run_load", lambda: {"status": load_status})
    monkeypatch.setattr(pipeline.db, "count_incomplete_loads", lambda: pending_count)
    cleared = []
    monkeypatch.setattr(pipeline, "reset_local_data", lambda: cleared.append(True))

    result = pipeline.extraction_loop(
        {"players_fetch_depth": 2, "tiers": ["GOLD"], "divisions": ["I"], "runs_per_load": 1, "full_check": False},
        api_client=object(),
    )

    assert result is False
    assert cleared == []


def test_run_load_reports_failed_compacted_upload(monkeypatch):
    monkeypatch.setattr(pipeline, "load_champions", lambda: 10)
    monkeypatch.setattr(pipeline, "load_compacted", lambda: False)

    assert pipeline.run_load()["status"] is False


@pytest.mark.parametrize("ingested,built", [(False, None), (True, False), (True, True)])
def test_dbt_runs_after_confirmed_load_and_has_a_separate_result(monkeypatch, ingested, built):
    events = []
    monkeypatch.setattr(pipeline, "load_champions", lambda: 10)
    monkeypatch.setattr(pipeline, "load_compacted", lambda: events.append("load_and_commit") or ingested)
    monkeypatch.setattr(pipeline, "run_dbt", lambda: events.append("dbt") or built)
    result = pipeline.run_load()
    assert result["compacted_load_result"] is ingested
    assert result["dbt_build_result"] is built
    assert result["status"] is bool(ingested and built)
    assert events == (["load_and_commit", "dbt"] if ingested else ["load_and_commit"])


def test_dbt_configuration_error_preserves_confirmed_load_result(monkeypatch):
    monkeypatch.setattr(pipeline, "load_champions", lambda: 10)
    monkeypatch.setattr(pipeline, "load_compacted", lambda: True)

    def bad_config():
        raise ValueError("DBT_JOB_ID is not configured")

    monkeypatch.setattr(pipeline, "run_dbt", bad_config)
    result = pipeline.run_load()
    assert result["status"] is False
    assert result["compacted_load_result"] is True


def test_upload_alone_does_not_update_neon_or_mark_sqlite_complete(tmp_path, mock_db, monkeypatch):
    monkeypatch.setattr(loader, "COMPACTED_DIR", tmp_path)
    pq.write_table(
        pa.Table.from_pylist(
            [{"puuid": "p1", "region": "na1", "queueType": "RANKED_SOLO_5x5", "wins": 3, "losses": 2}]
        ),
        tmp_path / loader.COMPACTED_FILENAMES["players"],
    )
    monkeypatch.setattr(loader, "_upload", lambda *args: None)
    statuses = []
    monkeypatch.setattr(loader.db, "update_load_status", lambda dataset, players, status: statuses.append(status))

    def fail_registry(*args):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(loader.player_registry, "upsert_players", fail_registry)

    result = loader.load_dataset("players")

    assert result["status"] == "uploaded"
    assert statuses == ["pending_load"]


@pytest.mark.parametrize("failure", [None, "upload", "ingestion", "registry"])
def test_load_updates_are_gated_by_ingestion_success(monkeypatch, failure):
    from pydantic_models import IngestionConfigManifest

    events = []
    monkeypatch.setattr(loader, "get_ingestion_config", lambda: IngestionConfigManifest(ingest_job_id=123))

    def upload(dataset):
        events.append(dataset)
        return {
            "dataset": dataset,
            "status": "load_failed" if failure == "upload" else "uploaded",
            "records": [{"puuid": "p1", "region": "na1", "queueType": "solo"}],
        }

    def ingest(*args):
        events.append("ingestion")
        return failure != "ingestion"

    def registry(*args):
        events.append("neon")
        if failure == "registry":
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr(loader, "load_dataset", upload)
    monkeypatch.setattr(loader, "run_ingestion", ingest)
    monkeypatch.setattr(loader.player_registry, "upsert_players", registry)
    monkeypatch.setattr(loader, "mark_load_status", lambda results, status: events.append(status))
    monkeypatch.setattr(loader, "complete_loaded_rank_pages", lambda: events.append("cursor"))
    assert loader.load_compacted() is (failure is None)
    assert events[:2] == ["players", "masteries"]
    if failure == "upload":
        assert "ingestion" not in events
    if failure in ("upload", "ingestion"):
        assert "neon" not in events
    if failure is None:
        assert events[-2:] == ["load_success", "cursor"]
    else:
        assert events[-1] == "load_failed"
        assert "cursor" not in events


@pytest.mark.parametrize("is_refresh", [False, True])
def test_failed_ingestion_preserves_files_and_sqlite_can_retry(tmp_path, mock_db, monkeypatch, is_refresh):
    from pydantic_models import IngestionConfigManifest

    monkeypatch.setattr(loader, "COMPACTED_DIR", tmp_path)
    monkeypatch.setattr(loader, "get_ingestion_config", lambda: IngestionConfigManifest(ingest_job_id=123))
    run_id = mock_db.start_run("ingestion_confirmation")
    task_id = mock_db.add_player_task(run_id, is_refresh=is_refresh)
    mock_db.add_player_records("p1", "players.parquet", task_id, "na1", "solo", "GOLD", "I", "15.1")
    mock_db.update_player_task(task_id, "success", file_path="players.parquet")
    if not is_refresh:
        mock_db.set_rank_page_claim(task_id, {"claim_token": "discovery", "player_count": 1})
    player = {"puuid": "p1", "region": "na1", "queueType": "solo", "wins": 3, "losses": 2}
    for dataset in loader.COMPACTED_FILENAMES:
        pq.write_table(pa.Table.from_pylist([player]), tmp_path / loader.COMPACTED_FILENAMES[dataset])
    monkeypatch.setattr(loader, "_upload", lambda *args: None)
    commits = []
    monkeypatch.setattr(
        loader.player_registry,
        "upsert_players",
        lambda players, **kwargs: commits.append((players, kwargs.get("is_refresh", False))),
    )
    cursors = []
    monkeypatch.setattr(loader.player_registry, "complete_rank_page", lambda *args: cursors.append(args) or 2)
    monkeypatch.setattr(loader, "run_ingestion", lambda *args: False)
    assert loader.load_compacted() is False
    assert commits == []
    assert cursors == []
    assert mock_db.count_incomplete_loads() == 1
    assert len(list(tmp_path.glob("*.parquet"))) == 2
    monkeypatch.setattr(loader, "run_ingestion", lambda *args: True)
    assert loader.load_compacted() is True
    assert len(commits) == 1
    assert commits[0][1] is is_refresh
    assert commits[0][0][0]["observed_at"]
    assert cursors == ([] if is_refresh else [("discovery", 1)])
    assert mock_db.count_incomplete_loads() == 0
    loader.complete_loaded_rank_pages()
    assert len(cursors) == (0 if is_refresh else 1)


@pytest.mark.parametrize("next_page", [0, 2])
def test_cursor_waits_for_every_player_and_tolerates_expired_claim(mock_db, monkeypatch, next_page):
    run_id = mock_db.start_run("partial_page_load")
    task_id = mock_db.add_player_task(run_id)
    mock_db.set_rank_page_claim(task_id, {"claim_token": "partial", "player_count": 2})
    mock_db.update_player_task(task_id, "success", file_path="players.parquet")
    for puuid in ("p1", "p2"):
        mock_db.add_player_records(puuid, "players.parquet", task_id, "na1", "solo", "GOLD", "I", "15.1")
    players = [{"puuid": puuid, "region": "na1", "queueType": "solo"} for puuid in ("p1", "p2")]
    cursors = []
    monkeypatch.setattr(loader.player_registry, "complete_rank_page", lambda *args: cursors.append(args) or next_page)
    mock_db.update_load_status("players", players[:1], "load_success")
    loader.complete_loaded_rank_pages()
    assert cursors == []
    mock_db.update_load_status("players", players[1:], "load_success")
    loader.complete_loaded_rank_pages()
    assert cursors == [("partial", 2)]
    with mock_db.get_connection() as conn:
        assert conn.execute(
            "SELECT rank_page_claim FROM player_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()[0] is None


def test_old_local_schema_adds_task_details_without_reset(mock_conn):
    mock_conn.execute("ALTER TABLE player_tasks DROP COLUMN rank_page_claim")
    run_id = loader.db.start_run("old_schema", conn=mock_conn)
    task_id = loader.db.add_player_task(run_id, conn=mock_conn)
    loader.db.set_rank_page_claim(task_id, {"claim_token": "old", "player_count": 1}, conn=mock_conn)
    assert mock_conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0] == "running"
    assert mock_conn.execute("SELECT rank_page_claim FROM player_tasks WHERE task_id = ?", (task_id,)).fetchone()[0]


def test_empty_load_does_not_submit_an_ingestion_job(monkeypatch):
    from pydantic_models import IngestionConfigManifest

    monkeypatch.setattr(loader, "get_ingestion_config", lambda: IngestionConfigManifest(ingest_job_id=123))
    monkeypatch.setattr(loader, "load_dataset", lambda name: {"dataset": name, "status": "skipped"})

    def unexpected(*args):
        raise AssertionError("No job is needed when neither dataset has rows")

    monkeypatch.setattr(loader, "run_ingestion", unexpected)
    assert loader.load_compacted()
