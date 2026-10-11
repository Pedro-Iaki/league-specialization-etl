import json

import get_players

import extract.tests.t_utilities as util
from load import player_registry

util.set_path_for_extract_modules()


def test_fresh_lookup_filters_in_postgres_by_fetched_ids():
    class Connection:
        def execute(self, query, params):
            assert "puuid = ANY(%s::text[])" in query
            assert params[-1] == ["p1", "p2"]
            return self

        def fetchall(self):
            return [("p1", None, None)]

    fresh = player_registry.get_fresh_players(10080, conn=Connection(), region="na1", queue="RANKED_SOLO_5x5", puuids=["p1", "p2"])
    assert [player["puuid"] for player in fresh] == ["p1"]


def test_page_lookup_passes_only_fetched_ids(mock_db, monkeypatch, tmp_path):
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    requested_ids = []

    def fresh_players(*args, **kwargs):
        requested_ids.extend(kwargs["puuids"])
        return []

    monkeypatch.setattr(get_players, "get_fresh_players", fresh_players)

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            return util.FakeResponse([util.create_player_payload("p1"), util.create_player_payload("p2")])

    get_players.run(mock_db.start_run("scoped_fresh_lookup"), Client(), "na1", "RANKED_SOLO_5x5")

    assert set(requested_ids) == {"p1", "p2"}


def test_explicit_pair_uses_shared_page_claim(mock_db, monkeypatch, tmp_path):
    run_id = mock_db.start_run("explicit_shared_page")
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    claims = []
    completed = []

    def claim(region, queue, patch, tiers, divisions):
        claims.append((region, queue, patch, tiers, divisions))
        return {"tier": "GOLD", "division": "II", "page": 4, "claim_token": "claim-1"}

    monkeypatch.setattr(get_players.player_registry, "claim_rank_page", claim)
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda token, count: completed.append((token, count)))

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            assert url.endswith("/GOLD/II")
            assert kwargs["params"] == {"page": 4}
            return util.FakeResponse([util.create_player_payload("p1")])

    get_players.run(run_id, Client(), "na1", "RANKED_SOLO_5x5", tier="GOLD", division="II")

    assert claims == [("na1", "RANKED_SOLO_5x5", "15.1", ["GOLD"], ["II"])]
    assert completed == []
    with mock_db.get_connection() as conn:
        claim = conn.execute("SELECT rank_page_claim FROM player_tasks WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert json.loads(claim) == {"claim_token": "claim-1", "player_count": 1}
    assert len(list(tmp_path.rglob("*.parquet"))) == 1


def test_failed_page_releases_shared_claim(mock_db, monkeypatch):
    run_id = mock_db.start_run("shared_page_failure")
    task_id = mock_db.add_player_task(run_id)
    completed = []
    released = []
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda token, count: completed.append((token, count)))
    monkeypatch.setattr(get_players.player_registry, "release_rank_page", lambda token: released.append(token))

    class Client:
        def get(self, url, **kwargs):
            return util.FakeResponse([], status_code=500)

    result = get_players.fetch_players(
        task_id, Client(), "na1", "RANKED_SOLO_5x5", "GOLD", "I",
        page_claim={"page": 4, "claim_token": "claim-1"},
    )

    assert result is None
    assert completed == []
    assert released == ["claim-1"]
    conn = mock_db.get_connection()
    assert conn.execute("SELECT status FROM player_tasks WHERE task_id = ?", (task_id,)).fetchone()[0] == "failed"
    conn.close()


def test_empty_page_ends_pass_without_more_requests(mock_db, monkeypatch):
    run_id = mock_db.start_run("shared_empty_page")
    task_id = mock_db.add_player_task(run_id)
    completed = []
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda token, count: completed.append((token, count)))

    class Client:
        def __init__(self):
            self.requests = 0

        def get(self, url, **kwargs):
            self.requests += 1
            return util.FakeResponse([])

    client = Client()
    result = get_players.fetch_players(
        task_id, client, "na1", "RANKED_SOLO_5x5", "GOLD", "I",
        page_claim={"page": 4, "claim_token": "claim-1"},
    )

    assert result == []
    assert client.requests == 1
    assert completed == [("claim-1", 0)]


def test_missing_api_client_releases_shared_claim(mock_db, monkeypatch):
    run_id = mock_db.start_run("shared_no_client")
    task_id = mock_db.add_player_task(run_id)
    released = []
    monkeypatch.setattr(get_players.player_registry, "release_rank_page", lambda token: released.append(token))

    result = get_players.fetch_players(
        task_id, None, "na1", "RANKED_SOLO_5x5", "GOLD", "I",
        page_claim={"page": 1, "claim_token": "claim-1"},
    )

    assert result is None
    assert released == ["claim-1"]


def test_general_crawl_claims_configured_tiers_and_divisions(mock_db, tmp_path, monkeypatch):
    run_id = mock_db.start_run("shared_crawl")
    monkeypatch.setattr(get_players, "OUTPUT_PATH", tmp_path)
    claims = []
    completed = []

    def claim(region, queue, patch, tiers, divisions):
        claims.append((region, queue, patch, tiers, divisions))
        return {"tier": "DIAMOND", "division": "I", "page": 2, "claim_token": "claim-1"}

    monkeypatch.setattr(get_players.player_registry, "claim_rank_page", claim)
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda token, count: completed.append((token, count)))

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            assert url.endswith("/DIAMOND/I")
            assert kwargs["params"] == {"page": 2}
            return util.FakeResponse([util.create_player_payload("p1")])

    get_players.run(
        run_id, Client(), "na1", "RANKED_SOLO_5x5",
        tiers=["DIAMOND", "EMERALD", "PLATINUM"], divisions=["I", "II"],
    )

    assert claims == [
        ("na1", "RANKED_SOLO_5x5", "15.1", ["DIAMOND", "EMERALD", "PLATINUM"], ["I", "II"])
    ]
    assert completed == []
    assert len(list(tmp_path.rglob("*.parquet"))) == 1


def test_failed_file_write_releases_claim_without_advancing(mock_db, tmp_path, monkeypatch):
    import pytest

    run_id = mock_db.start_run("save_failure")
    released = []
    completed = []
    monkeypatch.setattr(get_players.player_registry, "release_rank_page", lambda token: released.append(token))
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda *args: completed.append(args))

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            return util.FakeResponse([util.create_player_payload("p1")])

    def failed_save(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(get_players, "save_players", failed_save)
    with pytest.raises(OSError, match="disk full"):
        get_players.run(run_id, Client(), "na1", "RANKED_SOLO_5x5")
    assert released == ["test-claim"]
    assert completed == []


def test_already_ingested_page_advances_without_writing(mock_db, monkeypatch):
    completed = []
    monkeypatch.setattr(get_players.player_registry, "complete_rank_page", lambda *args: completed.append(args))
    monkeypatch.setattr(get_players, "get_fresh_players", lambda *args, **kwargs: [{"puuid": "p1"}])

    class Client:
        def get_patch(self):
            return "15.1"

        def get(self, url, **kwargs):
            return util.FakeResponse([util.create_player_payload("p1")])

    def unexpected_save(*args, **kwargs):
        raise AssertionError("Fresh players need no file")

    monkeypatch.setattr(get_players, "save_players", unexpected_save)
    get_players.run(mock_db.start_run("fresh_page"), Client(), "na1", "RANKED_SOLO_5x5")
    assert completed == [("test-claim", 1)]
