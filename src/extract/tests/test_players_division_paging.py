import get_players
import t_utilities as util

util.set_path_for_extract_modules()


def test_pick_least_populated_division_returns_given_tier_and_division_immediately(monkeypatch):
	def fail_if_called(**kwargs):
		raise AssertionError("get_page_info should not be called when tier and division are both given")

	monkeypatch.setattr(get_players.db, "get_page_info", fail_if_called)

	tier, division = get_players.pick_least_populated_division("na1", "RANKED_SOLO_5x5", "15.1", tier="GOLD", division="I")

	assert (tier, division) == ("GOLD", "I")


def test_pick_least_populated_division_prefers_lowest_loop_then_lowest_count(monkeypatch):
	stats = {
		("GOLD", "I"): (2, 5),
		("GOLD", "II"): (1, 100),
		("SILVER", "I"): (1, 3),
		("SILVER", "II"): (0, 999),  # lowest loop count wins, regardless of player count
	}
	captured = {}

	def fake_get_page_info(**kwargs):
		captured.update(kwargs)
		return stats

	monkeypatch.setattr(get_players.db, "get_page_info", fake_get_page_info)

	tier, division = get_players.pick_least_populated_division("na1", "RANKED_SOLO_5x5", "15.1")

	assert (tier, division) == ("SILVER", "II")
	assert captured["region"] == "na1"
	assert captured["queue"] == "RANKED_SOLO_5x5"
	assert captured["patch"] == "15.1"


def test_pick_least_populated_division_picks_lowest_count_when_loops_tie(monkeypatch):
	stats = {
		("GOLD", "I"): (0, 50),
		("GOLD", "II"): (0, 4),
		("GOLD", "III"): (0, 200),
	}
	monkeypatch.setattr(get_players.db, "get_page_info", lambda **kwargs: stats)

	tier, division = get_players.pick_least_populated_division("na1", "RANKED_SOLO_5x5", "15.1")

	assert (tier, division) == ("GOLD", "II")


def test_pick_least_populated_division_restricts_search_when_only_tier_given(monkeypatch):
	captured = {}

	def fake_get_page_info(**kwargs):
		captured.update(kwargs)
		return {(t, d): (0, 0) for t in kwargs["tiers"] for d in kwargs["divisions"]}

	monkeypatch.setattr(get_players.db, "get_page_info", fake_get_page_info)

	tier, division = get_players.pick_least_populated_division("na1", "RANKED_SOLO_5x5", "15.1", tier="GOLD")

	assert captured["tiers"] == ["GOLD"]
	assert captured["divisions"] == ["I", "II", "III", "IV"]
	assert tier == "GOLD"


def test_fetch_players_advances_page_and_re_fetches_on_empty_page(mock_db):
	run_id = mock_db.start_run("paging_advance_test")
	task_id = mock_db.add_player_task(run_id)

	class PagedClient:
		def get_patch(self):
			return "15.1"

		def get(self, url, **kwargs):
			page = kwargs["params"]["page"]
			if page == 1:
				return util.FakeResponse([])  # forces fetch_players to advance and retry
			return util.FakeResponse([util.create_player_payload("p2a"), util.create_player_payload("p2b")])

	result = get_players.fetch_players(task_id, PagedClient(), region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I", patch="15.1")

	assert result is not None
	assert {p["puuid"] for p in result} == {"p2a", "p2b"}

	page, loop = mock_db.get_page_and_loop("na1", "RANKED_SOLO_5x5", "GOLD", "I", "15.1")
	assert page == 3  # page 1 (count 0) -> advance to 2; page 2 (count 2) -> advance to 3
	assert loop == 0

	conn = mock_db.get_connection()
	task = conn.execute("SELECT attempts FROM player_tasks WHERE task_id = ?", (task_id,)).fetchone()
	conn.close()
	assert task["attempts"] == 2  # in_progress marked once per fetch_players invocation


def test_fetch_players_resets_page_and_bumps_loop_when_count_drops(mock_db, db_factory):
	conn = mock_db.get_connection()
	factory = db_factory(conn)
	factory.create_individual_tier_division_page({
		"region": "na1", "queue": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "I", "patch": "15.1",
		"current_page": 5, "last_player_count": 10, "loop_count": 2,
	})
	conn.close()

	run_id = mock_db.start_run("paging_reset_test")
	task_id = mock_db.add_player_task(run_id)
	requested_pages = []

	class SmallPageClient:
		def get_patch(self):
			return "15.1"

		def get(self, url, **kwargs):
			requested_pages.append(kwargs["params"]["page"])
			return util.FakeResponse([util.create_player_payload("q1"), util.create_player_payload("q2"), util.create_player_payload("q3")])

	result = get_players.fetch_players(task_id, SmallPageClient(), region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I", patch="15.1")
	assert result is not None
	assert len(result) == 3
	assert requested_pages == [5]  # used the previously stored page

	page, loop = mock_db.get_page_and_loop("na1", "RANKED_SOLO_5x5", "GOLD", "I", "15.1")
	assert page == 1  # 3 < previous last_player_count of 10, so resets
	assert loop == 3


def test_fetch_players_marks_task_failed_on_error_response(mock_db):
	run_id = mock_db.start_run("paging_error_test")
	task_id = mock_db.add_player_task(run_id)

	class ErrorClient:
		def get_patch(self):
			return "15.1"

		def get(self, url, **kwargs):
			return util.FakeResponse([], status_code=500)

	result = get_players.fetch_players(task_id, ErrorClient(), region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I", patch="15.1")

	assert result is None
	conn = mock_db.get_connection()
	task = conn.execute("SELECT status FROM player_tasks WHERE task_id = ?", (task_id,)).fetchone()
	conn.close()
	assert task["status"] == "failed"


def test_fetch_players_returns_none_without_an_api_client(mock_db):
	run_id = mock_db.start_run("paging_no_client_test")
	task_id = mock_db.add_player_task(run_id)

	result = get_players.fetch_players(task_id, None, region="na1", queue="RANKED_SOLO_5x5", tier="GOLD", division="I", patch="15.1") # type: ignore

	assert result is None