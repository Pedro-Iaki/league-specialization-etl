from functools import partial

import pytest

from extract import get_masteries, get_players
from extract import run_pipeline as pipeline
from extract.tests import t_utilities as util

CONFIG = {
    "region": "na1",
    "queue": "RANKED_SOLO_5x5",
    "tiers": ["GOLD"],
    "divisions": ["I"],
    "freshness_threshold_minutes": 10080,
    "mastery_task_limit": 10,
}


@pytest.mark.parametrize("outcome,succeeded", [
    ("rank_failure", False), ("mastery_failure", False), ("empty", True), ("success", True),
])
def test_snapshot_result_agrees_with_its_sqlite_run(mock_db, monkeypatch, tmp_path, outcome, succeeded):
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path / "players")
    monkeypatch.setattr(get_masteries, "OUTPUT_PATH", tmp_path / "masteries")

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            if outcome == "empty":
                return util.FakeResponse([])
            if outcome == "rank_failure" or (outcome == "mastery_failure" and "champion-masteries" in url):
                return util.FakeResponse([], status_code=500)
            if "champion-masteries" in url:
                return util.FakeResponse([util.create_mastery_payload("p1")])
            return util.FakeResponse([util.create_player_payload("p1")])

    result = pipeline.run_snapshot_fetchers(CONFIG, 0, "test", Client())
    status = "success" if succeeded else "failed"
    assert result["status"] == status
    conn = mock_db.get_connection()
    try:
        assert conn.execute("SELECT status FROM runs").fetchone()[0] == status
        if outcome == "mastery_failure":
            assert conn.execute("SELECT status FROM player_tasks").fetchone()[0] == "success"
            task = conn.execute("SELECT status, error_message FROM mastery_tasks").fetchone()
            assert task["status"] == "failed"
            assert "500" in task["error_message"]
    finally:
        conn.close()
    if outcome == "mastery_failure":
        assert result["snapshot_size"] == 1
        assert result["error"]
        assert list(tmp_path.rglob("players_*.parquet"))


def test_task_success_check_is_scoped_and_includes_unfinished_tasks(mock_db):
    older = mock_db.start_run("older_failed_run")
    failed = mock_db.add_player_task(older)
    mock_db.update_player_task(failed, "failed")
    current = mock_db.start_run("current_run")
    assert mock_db.run_tasks_succeeded(current)
    task = mock_db.add_player_task(current)
    assert not mock_db.run_tasks_succeeded(current)
    mock_db.update_player_task(task, "success")
    assert mock_db.run_tasks_succeeded(current)
    mastery = mock_db.add_mastery_task(current, "p1")
    assert not mock_db.run_tasks_succeeded(current)
    mock_db.update_mastery_task(mastery, "in_progress", "15.1")
    assert not mock_db.run_tasks_succeeded(current)
    mock_db.update_mastery_task(mastery, "success", "15.1")
    assert mock_db.run_tasks_succeeded(current)
    mock_db.update_mastery_task(mastery, "failed", "15.1", error_message="HTTP 500")
    assert not mock_db.run_tasks_succeeded(current)


@pytest.mark.parametrize("outcome,succeeded", [
    ("rank_failure", False), ("mastery_failure", False), ("partial", False),
    ("missing_queue", True), ("no_claims", True), ("success", True),
])
def test_refresh_result_agrees_with_its_sqlite_run(mock_db, monkeypatch, tmp_path, outcome, succeeded):
    registry = pipeline.refresh_stale.player_registry
    players = [{"puuid": puuid, "region": "na1", "queue": CONFIG["queue"]}
               for puuid in (("p1", "p2") if outcome == "partial" else ("p1",))]
    monkeypatch.setattr(registry, "release_expired_claims", lambda *args: 0)
    monkeypatch.setattr(registry, "claim_stale_players", lambda *args, **kwargs:
                        [] if outcome == "no_claims" else players)
    monkeypatch.setattr(registry, "heartbeat_claims", lambda *args: 1)
    released = []
    monkeypatch.setattr(registry, "release_claims", lambda *args, **kwargs: released.append(args))
    monkeypatch.setattr(registry, "record_refresh_result", lambda *args: 1)
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path / "players")
    monkeypatch.setattr(get_masteries, "save_masteries",
                        partial(get_masteries.save_masteries, output_path=tmp_path / "masteries"))

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            if outcome == "missing_queue":
                return util.FakeResponse([])
            if (outcome == "rank_failure"
                    or (outcome == "mastery_failure" and "champion-masteries" in url)
                    or (outcome == "partial" and url.endswith("/p2"))):
                return util.FakeResponse([], status_code=500)
            if "champion-masteries" in url:
                return util.FakeResponse([util.create_mastery_payload("p1")])
            return util.FakeResponse([util.create_player_payload("p1")])

    result = pipeline.run_stale_refresh(CONFIG, 0, "test", Client(), len(players))
    assert result["status"] is succeeded
    assert result["failures"] == (0 if succeeded else 1)
    conn = mock_db.get_connection()
    try:
        row = conn.execute("SELECT status, error_message FROM runs").fetchone()
        assert row["status"] == ("success" if succeeded else "failed")
        if not succeeded:
            assert row["error_message"] == result["error"]
            task = conn.execute(
                """SELECT error_message FROM player_tasks WHERE status = 'failed'
                   UNION ALL SELECT error_message FROM mastery_tasks WHERE status = 'failed'"""
            ).fetchone()
            assert "500" in task["error_message"]
    finally:
        conn.close()
    if outcome != "no_claims":
        assert len(released) == 1
    if outcome in ("mastery_failure", "partial"):
        assert result["players_refreshed"] == 1
        assert list(tmp_path.rglob("players_*.parquet"))
