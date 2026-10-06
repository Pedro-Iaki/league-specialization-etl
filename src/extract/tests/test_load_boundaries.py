import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import extract.run_pipeline as pipeline
import load.load_compacted_to_databricks as loader


@pytest.mark.parametrize("load_status,pending_count", [(False, 0), (True, 1)])
def test_legacy_runner_retains_files_when_load_is_incomplete(
    tmp_path, monkeypatch, load_status, pending_count
):
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


def test_uploaded_players_are_not_reported_complete_when_registry_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "COMPACTED_DIR", tmp_path)
    pq.write_table(
        pa.Table.from_pylist([{"puuid": "p1", "region": "na1", "queueType": "RANKED_SOLO_5x5", "wins": 3, "losses": 2}]),
        tmp_path / loader.COMPACTED_FILENAMES["players"],
    )
    monkeypatch.setattr(loader, "_upload", lambda *args: None)
    monkeypatch.setattr(loader.db, "update_load_status", lambda *args: 1)

    def fail_registry(*args):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(loader.player_registry, "upsert_players", fail_registry)

    result = loader.load_dataset("players")

    assert result["status"] == "registry_failed"
