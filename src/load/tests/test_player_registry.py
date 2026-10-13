import math
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


def test_staleness_weights_scope_penalty_decay_and_expired_claims():
    class Connection:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.create_function("now", 0, lambda: 100000)
            self.conn.create_function("greatest", 2, max)
            self.conn.create_function("power", 2, math.pow)
            self.conn.create_function("floor", 1, math.floor)
            self.conn.execute("""CREATE TABLE player_state_registry (
                region TEXT, queue TEXT, last_updated_at INTEGER, inactive_streak INTEGER,
                claim_status TEXT, claimed_at INTEGER)""")

        def execute(self, query, params):
            query = query.replace("%s", "?").replace("interval '1 minute'", "60").replace("::integer", "")
            query = query.replace("extract(epoch FROM (now() - last_updated_at))", "(now() - last_updated_at)")
            return self.conn.execute(query, params)

    registry = Connection()
    try:
        registry.conn.executemany(
            "INSERT INTO player_state_registry VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("na1", "solo", 99999, 0, "idle", None),  # fresh
                ("na1", "solo", 99900, 0, "idle", None),  # stale, weight 1
                ("na1", "solo", 99900, 3, "idle", None),  # one period elapsed: penalty 2, weight 1/4
                ("na1", "solo", 99900, 0, "claimed", 99999),  # another worker owns it
                ("na1", "solo", 99900, 0, "claimed", 98000),  # expired, weight 1
                ("eu", "solo", 0, 0, "idle", None),
                ("na1", "flex", 0, 0, "idle", None),
            ],
        )
        assert player_registry.get_staleness_fraction("na1", "solo", 1, conn=registry) == pytest.approx(2.25 / 5)
        assert player_registry.get_staleness_fraction("missing", "solo", 1, conn=registry) == 0
    finally:
        registry.conn.close()


def test_heartbeat_cleanup_and_release_preserve_other_workers_claims():
    class Connection:
        def __init__(self):
            self.conn = sqlite3.connect(":memory:")
            self.conn.create_function("now", 0, lambda: 10000)
            self.conn.execute("""CREATE TABLE player_state_registry (
                puuid TEXT, claim_status TEXT, claimed_by TEXT, claimed_at INTEGER)""")
            self.conn.executemany(
                "INSERT INTO player_state_registry VALUES (?, 'claimed', ?, ?)",
                [("p1", "ours", 1), ("p2", "other", 9000), ("p3", "crashed", 1)],
            )

        def execute(self, query, params):
            query = query.replace("%s", "?").replace("interval '1 minute'", "60")
            query = query.replace("puuid = ANY(?::text[])", "puuid IN (SELECT value FROM json_each(?))")
            if isinstance(params[0], list):
                import json

                params = (json.dumps(params[0]), *params[1:])
            return self.conn.execute(query, params)

    registry = Connection()
    try:
        assert player_registry.heartbeat_claims("ours", conn=registry) == 1
        assert player_registry.release_expired_claims(30, conn=registry) == 1
        assert player_registry.release_claims(["p1", "p2"], "ours", conn=registry) == 1
        assert registry.conn.execute(
            "SELECT claimed_by, claimed_at FROM player_state_registry WHERE puuid = 'p2'"
        ).fetchone() == ("other", 9000)
    finally:
        registry.conn.close()
