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
    monkeypatch.setattr(refresh.player_registry, "heartbeat_claims", lambda worker: events.append("heartbeat") or 0)
    monkeypatch.setattr(refresh, "handle_player_extraction", lambda **kwargs: events.append("rank") or {
        "wins": 12, "losses": 8, "tier": "GOLD", "rank": "I"})
    monkeypatch.setattr(refresh, "handle_mastery_extraction", lambda **kwargs: events.append("mastery") or True)
    result = refresh.run(1, PatchClient(), 1, 10080, 30)
    assert events == ["heartbeat", "rank", "mastery"]
    assert result["players_refreshed"] == result["masteries_refreshed"] == 1
    assert len(released) == 1
