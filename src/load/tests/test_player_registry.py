import sqlite3

import pytest

from load import player_registry


class RegistryConnection:
    """Run the production conflict clause locally, adapting only its array input."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """CREATE TABLE player_state_registry (
                puuid TEXT, region TEXT, queue TEXT, queue_games_total INTEGER,
                inactive_streak INTEGER DEFAULT 0, last_updated_at TEXT,
                PRIMARY KEY (puuid, region, queue))"""
        )

    def execute(self, query, params):
        columns = query.split("SELECT puuid", 1)[0]
        conflict_clause = query.split("WHERE true", 1)[1].replace("%s", "?")
        values = [(*observation, params[-1]) for observation in zip(*params[:-1])]
        return self.conn.executemany(columns + "VALUES (?, ?, ?, ?, ?) " + conflict_clause, values)

    def state(self):
        return self.conn.execute(
            "SELECT queue_games_total, inactive_streak, last_updated_at FROM player_state_registry"
        ).fetchone()


def observation(games, day):
    return {
        "puuid": "p1",
        "region": "na1",
        "queueType": "solo",
        "wins": games,
        "losses": 0,
        "observed_at": f"2026-10-{day:02d}T12:00:00+00:00",
    }


def test_repeated_and_older_loads_do_not_change_refresh_tracking():
    registry = RegistryConnection()
    try:
        player_registry.upsert_players([observation(20, 1)], conn=registry)
        player_registry.upsert_players([observation(20, 2)], conn=registry, is_refresh=True)
        state = registry.state()
        assert state[:2] == (20, 1)
        player_registry.upsert_players([observation(20, 2)], conn=registry, is_refresh=True)
        player_registry.upsert_players([observation(15, 1)], conn=registry, is_refresh=True)
        assert registry.state() == state
        player_registry.upsert_players([observation(21, 3)], conn=registry, is_refresh=True)
        assert registry.state()[:2] == (21, 0)
    finally:
        registry.conn.close()


def test_discovery_does_not_count_unchanged_games_as_inactivity():
    registry = RegistryConnection()
    try:
        player_registry.upsert_players([observation(20, 1)], conn=registry)
        player_registry.upsert_players([observation(20, 2)], conn=registry)
        assert registry.state()[:2] == (20, 0)
    finally:
        registry.conn.close()


@pytest.mark.parametrize("page", [None, (2,)])
def test_page_completion_accepts_an_expired_or_already_completed_claim(page):
    class Connection:
        def execute(self, query, params):
            assert params[-1] == "old-claim"
            return self

        def fetchone(self):
            return page

    assert player_registry.complete_rank_page("old-claim", 200, conn=Connection()) == (2 if page else 0)
