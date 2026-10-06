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
        lambda limit, run_id, threshold_minutes: [
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
    return recorded, released


def test_rank_result_updates_tracking_even_if_mastery_fails(monkeypatch):
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
    assert len(recorded) == 1
    assert recorded[0][:4] == ("p1", "na1", "RANKED_SOLO_5x5", 20)
    assert released == [(["p1"], recorded[0][4])]


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
