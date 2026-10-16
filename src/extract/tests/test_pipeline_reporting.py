import json

import pytest

from extract import run_pipeline as pipeline


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        pipeline, "run_snapshot_fetchers", lambda *args: {"status": "success", "snapshot_size": 100}
    )
    monkeypatch.setattr(pipeline, "run_stale_refresh", lambda *args: {"status": True})
    monkeypatch.setattr(pipeline.verify, "run_integrity_check", lambda full: {"database": {"faulty_records_count": 0}})
    monkeypatch.setattr(pipeline.compact, "run", lambda: None)
    monkeypatch.setattr(
        pipeline.verify,
        "verify_compaction_integrity",
        lambda: {"task_level_issues_count": 0, "pending_compaction_records_count": {"players": 0, "masteries": 0}},
    )
    monkeypatch.setattr(pipeline, "run_load", lambda config: {"status": True})
    monkeypatch.setattr(pipeline.db, "count_incomplete_loads", lambda: 0)
    monkeypatch.setattr(pipeline, "reset_local_data", lambda: None)
    return {
        "players_fetch_depth": 1,
        "tiers": ["GOLD"],
        "divisions": ["I"],
        "runs_per_load": 3,
        "full_check": False,
        "region": "na1",
        "queue": "solo",
        "freshness_threshold_minutes": 10080,
        "max_refresh_scale": 4,
    }


@pytest.mark.parametrize("rounds,loaded_at", [(1, [1]), (2, [2]), (5, [3, 5]), (6, [3, 6])])
def test_load_cadence_and_final_partial_group(runner, tmp_path, monkeypatch, rounds, loaded_at):
    collected = []
    loads = []
    monkeypatch.setattr(
        pipeline, "run_snapshot_fetchers",
        lambda config, n, *args: collected.append(n + 1) or {"status": "success", "snapshot_size": 100},
    )
    monkeypatch.setattr(pipeline, "run_load", lambda config: loads.append(collected[-1]) or {"status": True})
    runner["players_fetch_depth"] = rounds
    assert pipeline.extraction_loop(runner, object())
    assert loads == loaded_at
    report = json.loads((tmp_path / "data" / "logs" / "job_results.json").read_text())
    assert len(report) == rounds
    assert all(round["status"] and round["stage"] == "complete" for round in report)
    assert all(round["snapshot_result"]["status"] == "success" for round in report)


@pytest.mark.parametrize(
    "stage",
    [
        "staleness",
        "snapshot",
        "refresh",
        "integrity",
        "compaction",
        "compaction_integrity",
        "load",
        "dbt_build",
        "interrupt",
    ],
)
def test_failed_round_is_saved_and_prevents_cleanup(runner, tmp_path, monkeypatch, stage):
    def failure(*args, **kwargs):
        raise OSError("temporary stage error")

    if stage == "staleness":
        monkeypatch.setattr(pipeline.player_registry, "get_staleness_fraction", failure)
    elif stage == "snapshot":
        monkeypatch.setattr(
            pipeline, "run_snapshot_fetchers", lambda *args: {"status": "failed", "error": "HTTP 503"}
        )
    elif stage == "refresh":
        monkeypatch.setattr(pipeline, "run_stale_refresh", lambda *args: {"status": False, "error": "HTTP 503"})
    elif stage == "integrity":
        monkeypatch.setattr(
            pipeline.verify, "run_integrity_check", lambda full: {"database": {"faulty_records_count": 1}}
        )
    elif stage == "compaction":
        monkeypatch.setattr(pipeline.compact, "run", failure)
    elif stage == "compaction_integrity":
        monkeypatch.setattr(pipeline.verify, "verify_compaction_integrity", lambda: {"task_level_issues_count": 1})
    elif stage in ("load", "dbt_build"):
        monkeypatch.setattr(
            pipeline,
            "run_load",
            lambda config: {"status": False, "compacted_load_result": stage == "dbt_build", "dbt_build_result": False,
                     "error": "warehouse technical failure"},
        )
    else:

        def interrupt(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(pipeline.compact, "run", interrupt)
    cleanup = []
    monkeypatch.setattr(pipeline, "reset_local_data", lambda: cleanup.append(True))
    assert not pipeline.extraction_loop(runner, object())
    report = json.loads((tmp_path / "data" / "logs" / "job_results.json").read_text())
    assert len(report) == 1
    assert report[0]["status"] is False
    assert report[0]["stage"] == ("compaction" if stage == "interrupt" else stage)
    assert report[0]["error"]
    assert cleanup == []
    assert isinstance(report[0]["snapshot_result"], dict)
    if stage == "staleness":
        assert report[0]["snapshot_result"]["status"] == "not_started"
        assert report[0]["refresh_result"]["error"] == "temporary stage error"
    elif stage in ("snapshot", "refresh"):
        assert report[0][f"{stage}_result"]["error"] == "HTTP 503"
        assert "HTTP 503" not in report[0]["error"]
    elif stage in ("compaction", "interrupt"):
        assert report[0]["integrity_result"]["compaction"]["error"]
        assert "temporary stage error" not in report[0]["error"]
    elif stage in ("load", "dbt_build"):
        assert report[0]["load_result"]["error"] == "warehouse technical failure"
        assert "warehouse technical" not in report[0]["error"]


@pytest.mark.parametrize("stage", ["snapshot", "refresh", "load"])
def test_raised_errors_remain_in_stage_details_with_a_human_summary(runner, tmp_path, monkeypatch, stage):
    def failure(*args):
        raise OSError("raw technical failure detail")

    target = {"snapshot": "run_snapshot_fetchers", "refresh": "run_stale_refresh", "load": "run_load"}[stage]
    monkeypatch.setattr(pipeline, target, failure)
    assert not pipeline.extraction_loop(runner, object())
    report = json.loads((tmp_path / "data" / "logs" / "job_results.json").read_text())[0]
    assert report["stage"] == stage
    assert report[f"{stage}_result"]["error"] == "raw technical failure detail"
    assert "raw technical" not in report["error"]


def test_snapshot_interrupt_retains_an_explicit_snapshot_result(runner, tmp_path, monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "run_snapshot_fetchers", interrupt)
    assert not pipeline.extraction_loop(runner, object())
    report = json.loads((tmp_path / "data" / "logs" / "job_results.json").read_text())[0]
    assert report["snapshot_result"]["status"] == "interrupted"
    assert report["stage"] == "snapshot"
    assert report["error"] == "Interrupted by operator; local files retained."
