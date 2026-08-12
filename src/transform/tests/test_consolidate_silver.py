import json

from src.transform import consolidate_silver


def test_collect_latest_player_records_keeps_latest_snapshot_for_each_puuid():
    snapshot_old = {
        "region": "na1",
        "queue": "RANKED_SOLO_5x5",
        "tier": "GOLD",
        "division": "III",
        "patch": "16.14.1",
        "fetched_at": "2026-07-22T00:00:00+00:00",
        "players": [
            {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "GOLD",
                "rank": "III",
                "puuid": "player-1",
                "leaguePoints": 12,
                "wins": 20,
                "losses": 10,
                "veteran": False,
                "inactive": False,
                "freshBlood": False,
                "hotStreak": False,
            }
        ],
    }
    snapshot_new = {
        "region": "na1",
        "queue": "RANKED_SOLO_5x5",
        "tier": "GOLD",
        "division": "III",
        "patch": "16.14.1",
        "fetched_at": "2026-07-23T00:00:00+00:00",
        "players": [
            {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "GOLD",
                "rank": "III",
                "puuid": "player-1",
                "leaguePoints": 99,
                "wins": 30,
                "losses": 5,
                "veteran": True,
                "inactive": False,
                "freshBlood": False,
                "hotStreak": True,
            },
            {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "GOLD",
                "rank": "III",
                "puuid": "player-2",
                "leaguePoints": 5,
                "wins": 3,
                "losses": 2,
                "veteran": False,
                "inactive": False,
                "freshBlood": True,
                "hotStreak": False,
            },
        ],
    }

    by_player = consolidate_silver.collect_latest_player_records({
        "old": snapshot_old,
        "new": snapshot_new,
    })

    assert set(by_player) == {"player-1", "player-2"}
    assert by_player["player-1"]["leaguePoints"] == 99
    assert by_player["player-1"]["fetched_at"] == "2026-07-23T00:00:00+00:00"
    assert by_player["player-2"]["puuid"] == "player-2"
