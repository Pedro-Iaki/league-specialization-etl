import pytest

from extract import config_helper
from extract import run_pipeline as pipeline
from extract.tests import t_utilities as util
from load import load_compacted_to_databricks as loader


@pytest.mark.parametrize("key", ["INGEST_JOB_ID", "INGESTION_TIMEOUT_SECONDS", "DBT_JOB_ID", "DBT_TIMEOUT_SECONDS"])
def test_invalid_job_settings_stop_before_collection(tmp_path, monkeypatch, pipeline_stub, key):
    util._clear_pipeline_env(monkeypatch)
    config = util.EnvFactory.create(
        tmp_path, "invalid_job", overrides={"INGEST_JOB_ID": "555", "DBT_JOB_ID": "666", key: "0"},
    )
    assert not pipeline.run_pipeline(config)
    assert pipeline_stub == {}


def test_selected_job_settings_reach_the_validated_manifest(tmp_path, monkeypatch, pipeline_stub):
    util._clear_pipeline_env(monkeypatch)
    config = util.EnvFactory.create(tmp_path, "selected", overrides={
        "INGEST_JOB_ID": "555", "INGESTION_TIMEOUT_SECONDS": "600",
        "DBT_JOB_ID": "666", "DBT_TIMEOUT_SECONDS": "1200",
    })
    assert pipeline.run_pipeline(config)
    manifest = pipeline_stub["config_manifest"]
    assert (manifest["ingest_job_id"], manifest["ingestion_timeout_seconds"]) == (555, 600)
    assert (manifest["dbt_job_id"], manifest["dbt_timeout_seconds"]) == (666, 1200)


@pytest.mark.parametrize("key", ["INGEST_JOB_ID", "DBT_JOB_ID"])
def test_missing_job_id_stops_before_collection(tmp_path, monkeypatch, pipeline_stub, key):
    util._clear_pipeline_env(monkeypatch)
    config = util.EnvFactory.create(tmp_path, "missing_job", remove={key})
    assert not pipeline.run_pipeline(config)
    assert pipeline_stub == {}


def test_pipeline_reads_selected_configuration_once_and_passes_both_job_settings(tmp_path, mock_db, monkeypatch):
    util._clear_pipeline_env(monkeypatch)
    selected = util.EnvFactory.create(tmp_path, "selected", overrides={
        "INGEST_JOB_ID": "555", "INGESTION_TIMEOUT_SECONDS": "600",
        "DBT_JOB_ID": "666", "DBT_TIMEOUT_SECONDS": "1200", "RUNS_PER_LOAD": "1",
    })
    reads = []
    read_file = config_helper.dotenv_values

    def read_once(path):
        reads.append(path)
        return read_file(path)

    def collect(*args):
        selected.write_text("INGEST_JOB_ID=777\nDBT_JOB_ID=888\n")
        return {"status": "success", "snapshot_size": 100}

    monkeypatch.setattr(config_helper, "dotenv_values", read_once)
    monkeypatch.setattr(pipeline.init_db, "db_exists", lambda: True)
    monkeypatch.setattr(pipeline.db, "is_active", lambda: True)
    monkeypatch.setattr(pipeline.client, "RiotAPIClient", lambda **kwargs: object())
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "run_snapshot_fetchers", collect)
    monkeypatch.setattr(pipeline, "run_stale_refresh", lambda *args: {"status": True})
    monkeypatch.setattr(pipeline.verify, "run_integrity_check", lambda *args: {"database": {"faulty_records_count": 0}})
    monkeypatch.setattr(pipeline.compact, "run", lambda: None)
    monkeypatch.setattr(pipeline.verify, "verify_compaction_integrity", lambda: {
        "task_level_issues_count": 0, "pending_compaction_records_count": {"players": 0, "masteries": 0},
    })
    monkeypatch.setattr(pipeline, "load_champions", lambda: 10)
    monkeypatch.setattr(loader, "load_dataset", lambda name: {"dataset": name, "status": "uploaded", "records": []})
    monkeypatch.setattr(pipeline, "reset_local_data", lambda: None)
    calls = []
    monkeypatch.setattr(loader, "run_job", lambda *args: calls.append(args) or True)
    monkeypatch.setattr(pipeline, "run_job", lambda *args: calls.append(args) or True)

    assert pipeline.run_pipeline(selected)
    assert reads == [selected]
    assert calls == [(555, 600, "Ingestion"), (666, 1200, "dbt")]
