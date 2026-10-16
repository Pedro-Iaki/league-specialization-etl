import pyarrow.parquet as pq
import pytest

from extract import get_players, refresh_stale_players
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


def test_refresh_rank_files_are_unique_for_same_time_and_division(mock_db, monkeypatch, tmp_path):
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    run_id = mock_db.start_run("rank_file_collision")

    class Client:
        def get(self, url, **kwargs):
            return util.FakeResponse([util.create_player_payload(url.rsplit("/", 1)[-1])])

    for puuid in ("p1", "p2"):
        entry = refresh_stale_players.handle_player_extraction(
            {
                "puuid": puuid, "region": "na1", "queue": CONFIG["queue"],
                "date": "261016", "time": "120000", "patch": "15.1",
            },
            mock_db.add_player_task(run_id), Client(),
        )
        assert entry["puuid"] == puuid
    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 2
    assert {puuid for file in files for puuid in pq.read_table(file, columns=["puuid"])["puuid"].to_pylist()} == {
        "p1", "p2",
    }


@pytest.mark.parametrize("phase", ["snapshot", "refresh"])
@pytest.mark.parametrize("error", [RuntimeError("fetch failed"), OSError("disk unavailable"),
                                  ValueError("bad payload"), KeyboardInterrupt()])
def test_extraction_exceptions_finalize_the_ledger(mock_db, monkeypatch, tmp_path, phase, error):
    companion = tmp_path / "collected.parquet"
    companion.write_bytes(b"retain collected files")

    def fail(run_id, *args, **kwargs):
        mock_db.add_player_task(run_id)
        mock_db.add_mastery_task(run_id, "p1")
        raise error

    if phase == "snapshot":
        monkeypatch.setattr(pipeline, "extract_players", fail)
        run = lambda: pipeline.run_snapshot_fetchers(CONFIG, 0, "failure", object())
    else:
        monkeypatch.setattr(pipeline.refresh_stale, "run", fail)
        run = lambda: pipeline.run_stale_refresh(CONFIG, 0, "failure", object(), 1)
    if isinstance(error, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            run()
    else:
        result = run()
        assert result["status"] == ("failed" if phase == "snapshot" else False)
        assert result["error"] == str(error)

    conn = mock_db.get_connection()
    try:
        row = conn.execute("SELECT status, error_message FROM runs").fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == ("Interrupted by operator" if isinstance(error, KeyboardInterrupt) else str(error))
        assert conn.execute("SELECT status FROM player_tasks").fetchone()[0] == "failed"
        assert conn.execute("SELECT status FROM mastery_tasks").fetchone()[0] == "failed"
    finally:
        conn.close()
    assert companion.is_file()
