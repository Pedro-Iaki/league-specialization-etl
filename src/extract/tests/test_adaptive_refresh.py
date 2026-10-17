import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from extract import get_players
from extract import run_pipeline as pipeline
from extract.tests import t_utilities as util
from pydantic_models import ExtractionConfigManifest


@pytest.mark.parametrize(
    "staleness,scale", [(0, 0), (0.1, 3 / 7), (0.2, 1.5), (0.8 / 3, 4), (1, 4)],
)
def test_refresh_scale_increases_and_caps_before_singular_math(staleness, scale):
    assert pipeline.get_refresh_scale(staleness, 4) == pytest.approx(scale)


@pytest.mark.parametrize(
    "staleness,snapshot_size,cap,pause_discovery,expected_limit,skipped",
    [
        (0, 100, 4, True, 0, False),
        (0.1, 100, 4, True, 43, False),
        (0.2, 100, 4, True, 151, False),
        (0.2, 200, 4, True, 301, False),
        (0.2, 0, 4, True, 308, False),
        (0.8 / 3, 100, 4, True, 820, True),
        (1, 100, 4, True, 820, True),
        (0.25, 100, 2, True, 410, True),
        (0, 100, 4, False, 0, False),
        (0.2, 100, 4, False, 151, False),
        (0.8 / 3, 100, 4, False, 400, False),
        (1, 100, 4, False, 400, False),
        (1, 0, 4, False, 820, False),
        (0.25, 100, 2, False, 200, False),
    ],
)
def test_round_uses_observed_size_or_logged_fallback_and_skips_entire_snapshot(
    tmp_path, monkeypatch, staleness, snapshot_size, cap, pause_discovery, expected_limit, skipped,
):
    calls = []
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline.player_registry, "get_staleness_fraction", lambda *args: staleness)

    def snapshot(*args):
        calls.append("snapshot")
        return {"status": "success", "snapshot_size": snapshot_size}

    def refresh(config, run_n, date, api_client, limit):
        calls.append(limit)
        return {"status": True}

    monkeypatch.setattr(pipeline, "run_snapshot_fetchers", snapshot)
    monkeypatch.setattr(pipeline, "run_stale_refresh", refresh)
    monkeypatch.setattr(pipeline.verify, "run_integrity_check", lambda full: {"database": {"faulty_records_count": 0}})
    monkeypatch.setattr(pipeline.compact, "run", lambda: None)
    monkeypatch.setattr(
        pipeline.verify, "verify_compaction_integrity",
        lambda: {"task_level_issues_count": 0, "pending_compaction_records_count": {"players": 0, "masteries": 0}},
    )
    monkeypatch.setattr(pipeline, "run_load", lambda config: {"status": True})
    monkeypatch.setattr(pipeline.db, "count_incomplete_loads", lambda: 0)
    monkeypatch.setattr(pipeline, "reset_local_data", lambda: None)
    config = {
        "players_fetch_depth": 1, "tiers": ["GOLD"], "divisions": ["I"], "runs_per_load": 10, "full_check": False,
        "region": "na1", "queue": "solo", "freshness_threshold_minutes": 10080,
        "max_refresh_scale": cap,
        "pause_discovery_at_refresh_cap": pause_discovery,
    }

    assert pipeline.extraction_loop(config, api_client=object())
    assert calls == ([expected_limit] if skipped else ["snapshot", expected_limit])
    report = json.loads((tmp_path / "data" / "logs" / "job_results.json").read_text())[0]
    assert report["snapshot_result"]["status"] == ("skipped" if skipped else "success")
    assert report["snapshot_result"]["snapshot_size"] == (None if skipped else snapshot_size)
    assert report["refresh_result"]["refresh_snapshot_size"] == (
        pipeline.FALLBACK_SNAPSHOT_SIZE if skipped or not snapshot_size else snapshot_size
    )
    assert report["refresh_result"]["staleness_fraction"] == staleness
    assert "discovery" not in report
    assert "staleness_fraction" not in report
    assert "refresh_scale" not in report
    if skipped:
        assert "both snapshot fetchers skipped" in report["snapshot_result"]["reason"]


def test_snapshot_result_contains_page_size_and_runs_both_fetchers(mock_db, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "extract_players", lambda *args, **kwargs: calls.append("players") or 123)
    monkeypatch.setattr(pipeline, "extract_masteries", lambda *args, **kwargs: calls.append("masteries"))
    config = {
        "mastery_task_limit": 400, "region": "na1", "queue": "solo",
        "freshness_threshold_minutes": 10080, "tiers": ["GOLD"], "divisions": ["I"],
    }

    assert pipeline.run_snapshot_fetchers(config, 0, "today", object()) == {
        "status": "success", "snapshot_size": 123,
    }
    assert calls == ["players", "masteries"]


@pytest.mark.parametrize("fresh_count", [1, 3])
def test_page_size_counts_all_observed_players_before_freshness_filter(
    tmp_path, mock_db, monkeypatch, fresh_count,
):
    players = [{"puuid": f"p{number}"} for number in range(3)]
    monkeypatch.setattr(get_players, "fetch_players", lambda **kwargs: players)
    monkeypatch.setattr(get_players, "get_fresh_players", lambda *args, **kwargs: players[:fresh_count])
    monkeypatch.setattr(get_players, "save_players", lambda *args, **kwargs: tmp_path / "snapshot.parquet")
    run_id = mock_db.start_run("snapshot size")

    assert get_players.run(
        run_id, SimpleNamespace(get_patch=lambda: "1"), "na1", "solo", tier="GOLD", division="I",
    ) == 3


def test_runner_passes_final_limit_and_scope_to_worker_once(mock_db, monkeypatch):
    received = {}

    def fetch(run_id, **kwargs):
        received.update(kwargs)
        return {"status": True}

    monkeypatch.setattr(pipeline.refresh_stale, "run", fetch)
    config = {
        "region": "na1",
        "queue": "solo",
        "freshness_threshold_minutes": 10080,
    }
    assert pipeline.run_stale_refresh(config, 0, "today", object(), 150)["status"]
    assert received["limit"] == 150
    assert (received["region"], received["queue"]) == ("na1", "solo")


def test_zero_refresh_allocation_does_not_start_a_run(mock_db, monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("zero allocation must not call the refresh worker")

    monkeypatch.setattr(pipeline.refresh_stale, "run", unexpected_fetch)
    assert pipeline.run_stale_refresh({}, 0, "today", object(), 0)["claimed"] == 0
    conn = mock_db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("configured,expected", [(None, 4), ("2.5", 2.5)])
def test_refresh_scale_configuration_has_default_and_accepts_decimal(tmp_path, monkeypatch, configured, expected):
    util._clear_pipeline_env(monkeypatch)
    overrides = {"MAX_REFRESH_SCALE": configured} if configured else None
    config_path = util.EnvFactory.create(tmp_path, "refresh", overrides=overrides)
    config = pipeline.get_configs(config_path)
    assert ExtractionConfigManifest.model_validate(config).max_refresh_scale == expected


@pytest.mark.parametrize(
    "configured,process_override,expected",
    [
        (None, None, True),
        ("true", None, True),
        ("false", None, False),
        ("true", "false", False),
        ("false", "true", True),
    ],
)
def test_discovery_pause_setting_reaches_runner(
    tmp_path, monkeypatch, pipeline_stub, configured, process_override, expected,
):
    util._clear_pipeline_env(monkeypatch)
    overrides = {"PAUSE_DISCOVERY_AT_REFRESH_CAP": configured} if configured is not None else None
    config_path = util.EnvFactory.create(tmp_path, "discovery_pause", overrides=overrides)
    if process_override is not None:
        monkeypatch.setenv("PAUSE_DISCOVERY_AT_REFRESH_CAP", process_override)

    assert pipeline.run_pipeline(config_path)
    assert pipeline_stub["config_manifest"]["pause_discovery_at_refresh_cap"] is expected


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_refresh_scale_configuration_rejects_nonpositive_or_nonfinite_values(value):
    with pytest.raises(ValidationError):
        ExtractionConfigManifest(
            api_key="test", players_fetch_depth=1, mastery_task_limit=400,
            full_check=False, region="na1", queue="solo", max_refresh_scale=value,
            ingest_job_id=123, dbt_job_id=456,
        )
