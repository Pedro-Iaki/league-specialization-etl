import pytest

import extract.refresh_stale_players as refresh


class PatchClient:
    def get_patch(self):
        return "15.1"


def _stub_claims(monkeypatch):
    recorded = []
    released = []
    monkeypatch.setattr(refresh.player_registry, "release_expired_claims", lambda timeout: 0)
    monkeypatch.setattr(
        refresh.player_registry,
        "claim_stale_players",
        lambda limit, run_id, threshold_minutes, **kwargs: [
            {"puuid": "p1", "region": "na1", "queue": "RANKED_SOLO_5x5"}
        ],
    )
    monkeypatch.setattr(refresh.player_registry, "record_refresh_result", lambda *args: recorded.append(args))
    monkeypatch.setattr(
        refresh.player_registry,
        "release_claims",
        lambda puuids, claimed_by: released.append((puuids, claimed_by)),
    )
    monkeypatch.setattr(refresh.db, "add_player_task", lambda *args, **kwargs: 1)
    monkeypatch.setattr(refresh.db, "add_mastery_task", lambda *args, **kwargs: 2)
    monkeypatch.setattr(refresh.db, "get_pending_player_ids", lambda *args, **kwargs: [])
    monkeypatch.setattr(refresh.player_registry, "heartbeat_claims", lambda worker: 1)
    return recorded, released


def test_rank_fetch_leaves_tracking_unchanged_even_if_mastery_fails(monkeypatch):
    recorded, released = _stub_claims(monkeypatch)
    monkeypatch.setattr(
        refresh,
        "handle_player_extraction",
        lambda **kwargs: {"wins": 12, "losses": 8, "tier": "GOLD", "rank": "I"},
    )
    monkeypatch.setattr(refresh, "handle_mastery_extraction", lambda **kwargs: False)

    result = refresh.run(1, PatchClient(), 1, 10080, 30)

    assert result["players_refreshed"] == 1
    assert result["masteries_refreshed"] == 0
    assert recorded == []
    assert len(released) == 1
    assert released[0][0] == ["p1"]


def test_absent_queue_counts_as_inactive_rank_result(monkeypatch):
    recorded, _ = _stub_claims(monkeypatch)

    def absent_entry(**kwargs):
        raise refresh.MissingQueueEntry

    monkeypatch.setattr(refresh, "handle_player_extraction", absent_entry)
    monkeypatch.setattr(
        refresh,
        "handle_mastery_extraction",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mastery should not be fetched")),
    )

    result = refresh.run(1, PatchClient(), 1, 10080, 30)

    assert result["players_refreshed"] == 0
    assert len(recorded) == 1
    assert recorded[0][:4] == ("p1", "na1", "RANKED_SOLO_5x5", None)


def test_failed_rank_request_does_not_update_tracking(monkeypatch):
    recorded, released = _stub_claims(monkeypatch)
    monkeypatch.setattr(refresh, "handle_player_extraction", lambda **kwargs: None)

    result = refresh.run(1, PatchClient(), 1, 10080, 30)

    assert result["players_refreshed"] == 0
    assert recorded == []
    assert len(released) == 1


def test_claims_are_released_when_patch_lookup_fails(monkeypatch):
    import pytest

    _, released = _stub_claims(monkeypatch)

    class Client:
        def get_patch(self):
            raise RuntimeError("patch lookup failed")

    with pytest.raises(RuntimeError, match="patch lookup"):
        refresh.run(1, Client(), 1, 10080, 30)
    assert len(released) == 1


def test_heartbeat_precedes_fetch_and_lost_claim_does_not_block_data(monkeypatch):
    _, released = _stub_claims(monkeypatch)
    events = []
    clock = [0]
    monkeypatch.setattr(refresh, "monotonic", lambda: clock[0])

    class SlowPatchClient(PatchClient):
        def get_patch(self):
            clock[0] = 600
            return super().get_patch()

    monkeypatch.setattr(refresh.player_registry, "heartbeat_claims", lambda worker: events.append("heartbeat") or 0)
    monkeypatch.setattr(refresh, "handle_player_extraction", lambda **kwargs: events.append("rank") or {
        "wins": 12, "losses": 8, "tier": "GOLD", "rank": "I"})
    monkeypatch.setattr(refresh, "handle_mastery_extraction", lambda **kwargs: events.append("mastery") or True)
    result = refresh.run(1, SlowPatchClient(), 1, 10080, 30)
    assert events == ["heartbeat", "rank", "mastery"]
    assert result["players_refreshed"] == result["masteries_refreshed"] == 1
    assert len(released) == 1


def test_claim_heartbeat_is_periodic_during_a_large_refresh(monkeypatch):
    _stub_claims(monkeypatch)
    players = [{"puuid": str(n), "region": "na1", "queue": "solo"} for n in range(820)]
    monkeypatch.setattr(refresh.player_registry, "claim_stale_players", lambda *args, **kwargs: players)
    clock = [0]
    renewed_at = []
    monkeypatch.setattr(refresh, "monotonic", lambda: clock[0])
    monkeypatch.setattr(refresh.player_registry, "heartbeat_claims", lambda worker: renewed_at.append(clock[0]) or 820)

    def fetch(**kwargs):
        clock[0] += 2

    monkeypatch.setattr(refresh, "handle_player_extraction", fetch)
    refresh.run(1, PatchClient(), 820, 10080, 30)
    assert renewed_at == [600, 1200]


def test_pending_local_player_is_not_refetched_before_ingestion(mock_db, monkeypatch):
    fetched = []
    player = {"puuid": "p1", "region": "na1", "queue": "solo"}
    monkeypatch.setattr(refresh.player_registry, "release_expired_claims", lambda timeout: 0)
    monkeypatch.setattr(refresh.player_registry, "heartbeat_claims", lambda worker: 1)
    monkeypatch.setattr(refresh.player_registry, "release_claims", lambda *args, **kwargs: 1)
    monkeypatch.setattr(refresh.player_registry, "claim_stale_players", lambda *args, **kwargs:
                        [] if "p1" in kwargs["excluded_puuids"] else [player])

    def rank(info, task_id, api_client):
        fetched.append(info["puuid"])
        mock_db.add_player_records("p1", "rank.parquet", task_id, "na1", "solo", "GOLD", "I", "15.1")
        mock_db.update_player_task(task_id, "success", file_path="rank.parquet")
        return {"tier": "GOLD", "rank": "I", "wins": 10, "losses": 5}

    def mastery(info, task_id, api_client):
        mock_db.update_mastery_task(task_id, "success", "15.1", file_path="mastery.parquet")
        return True

    monkeypatch.setattr(refresh, "handle_player_extraction", rank)
    monkeypatch.setattr(refresh, "handle_mastery_extraction", mastery)
    for n in range(2):
        result = refresh.run(mock_db.start_run(f"refresh_{n}"), PatchClient(), 10, 10080, region="na1", queue="solo")
        assert result["claimed"] == (1 if n == 0 else 0)
    assert fetched == ["p1"]
    mock_db.update_load_status("players", [{"puuid": "p1", "region": "na1", "queueType": "solo"}], "load_success")
    assert mock_db.get_pending_player_ids("na1", "solo", freshness_minutes=10080) == []


@pytest.mark.parametrize("changes, expected", [
    ({}, ["p1"]),
    ({"player_load_status": "pending_load"}, ["p1"]),
    ({"player_load_status": "load_success"}, []),
    ({"player_load_status": "load_failed"}, []),
    ({"mastery_status": "failed"}, []),
    ({"mastery_load_status": "load_failed"}, []),
    ({"task_status": "failed"}, []),
    ({"task_status": "in_progress"}, ["p1"]),
    ({"age_minutes": 61}, []),
    ({"age_minutes": 60}, []),
    ({"region": "eu"}, []),
    ({"queue": "flex"}, []),
])
def test_pending_exclusion_requires_fresh_unloaded_nonfailed_work(mock_conn, changes, expected):
    db = refresh.db
    run_id = db.start_run("test_refresh", conn=mock_conn)
    task_id = db.add_player_task(run_id, conn=mock_conn)
    db.update_player_task(task_id, changes.get("task_status", "success"), conn=mock_conn)
    db.add_player_records(
        "p1", "rank.parquet", task_id, changes.get("region", "na1"),
        changes.get("queue", "solo"), "GOLD", "I", "15.1", conn=mock_conn,
    )
    mock_conn.execute(
        """UPDATE players_recorded
           SET paths_logged_at = json_array(datetime('now', ?)),
               player_load_status = ?, mastery_status = ?, mastery_load_status = ?""",
        (f"-{changes.get('age_minutes', 0)} minutes", changes.get("player_load_status", "pending_compaction"),
         changes.get("mastery_status", "pending"), changes.get("mastery_load_status", "pending_compaction")),
    )

    assert db.get_pending_player_ids("na1", "solo", conn=mock_conn, freshness_minutes=60) == expected


def test_pending_exclusion_ignores_recovered_historical_failures(mock_conn):
    db = refresh.db
    run_id = db.start_run("test_refresh", conn=mock_conn)
    failed_task = db.add_player_task(run_id, conn=mock_conn)
    db.add_player_records("p1", "old.parquet", failed_task, "na1", "solo", "GOLD", "I", "15.1", conn=mock_conn)
    db.update_player_task(failed_task, "failed", conn=mock_conn)
    db.update_load_status("players", [{"puuid": "p1", "region": "na1", "queueType": "solo"}],
                          "load_failed", conn=mock_conn)
    mastery_task = db.add_mastery_task(run_id, "p1", conn=mock_conn)
    db.update_mastery_task(mastery_task, "failed", "15.1", conn=mock_conn)

    recovered_task = db.add_player_task(run_id, conn=mock_conn)
    db.add_player_records("p1", "new.parquet", recovered_task, "na1", "solo", "GOLD", "I", "15.1", conn=mock_conn)
    db.update_player_task(recovered_task, "success", conn=mock_conn)
    recovered_mastery = db.add_mastery_task(run_id, "p1", conn=mock_conn)
    db.update_mastery_task(recovered_mastery, "success", "15.1", file_path="mastery.parquet", conn=mock_conn)

    assert db.get_pending_player_ids("na1", "solo", conn=mock_conn, freshness_minutes=60) == ["p1"]
