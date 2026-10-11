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


def test_upload_alone_does_not_update_neon_or_mark_sqlite_complete(tmp_path, monkeypatch):
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
    assert loader.load_compacted() is (failure is None)
    assert events[:2] == ["players", "masteries"]
    if failure == "upload":
        assert "ingestion" not in events
    if failure in ("upload", "ingestion"):
        assert "neon" not in events
    assert events[-1] == ("load_success" if failure is None else "load_failed")


def test_failed_ingestion_preserves_files_and_sqlite_can_retry(tmp_path, mock_db, monkeypatch):
    from pydantic_models import IngestionConfigManifest

    monkeypatch.setattr(loader, "COMPACTED_DIR", tmp_path)
    monkeypatch.setattr(loader, "get_ingestion_config", lambda: IngestionConfigManifest(ingest_job_id=123))
    run_id = mock_db.start_run("ingestion_confirmation")
    task_id = mock_db.add_player_task(run_id)
    mock_db.add_player_records("p1", "players.parquet", task_id, "na1", "solo", "GOLD", "I", "15.1")
    player = {"puuid": "p1", "region": "na1", "queueType": "solo", "wins": 3, "losses": 2}
    for dataset in loader.COMPACTED_FILENAMES:
        pq.write_table(pa.Table.from_pylist([player]), tmp_path / loader.COMPACTED_FILENAMES[dataset])
    monkeypatch.setattr(loader, "_upload", lambda *args: None)
    commits = []
    monkeypatch.setattr(loader.player_registry, "upsert_players", lambda players: commits.append(players))
    monkeypatch.setattr(loader, "run_ingestion", lambda *args: False)
    assert loader.load_compacted() is False
    assert commits == []
    assert mock_db.count_incomplete_loads() == 1
    assert len(list(tmp_path.glob("*.parquet"))) == 2
    monkeypatch.setattr(loader, "run_ingestion", lambda *args: True)
    assert loader.load_compacted() is True
    assert len(commits) == 1
    assert mock_db.count_incomplete_loads() == 0


def test_empty_load_does_not_submit_an_ingestion_job(monkeypatch):
    from pydantic_models import IngestionConfigManifest

    monkeypatch.setattr(loader, "get_ingestion_config", lambda: IngestionConfigManifest(ingest_job_id=123))
    monkeypatch.setattr(loader, "load_dataset", lambda name: {"dataset": name, "status": "skipped"})

    def unexpected(*args):
        raise AssertionError("No job is needed when neither dataset has rows")

    monkeypatch.setattr(loader, "run_ingestion", unexpected)
    assert loader.load_compacted()
