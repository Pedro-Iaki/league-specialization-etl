import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import faker
import pytest
from faker import Faker


def set_path_for_extract_modules():
	"""Ensure that the src/extract directory is in sys.path for imports."""
	extract_dir = Path(__file__).resolve().parents[1]
	if str(extract_dir) not in sys.path:
		sys.path.insert(0, str(extract_dir))

set_path_for_extract_modules()
import run_pipeline as pl


class EnvFactory:
	"""Build temporary .env files for run_pipeline input tests."""

	BASE_VALID = {
		"RIOT_API_KEY": "test-api-key",
		"VERSION": "vtest",
		"PLAYERS_FETCH_DEPTH": "1",
		"FULL_VERIFICATION_POST": "false",
		"REGION": "na1",
		"QUEUE": "RANKED_SOLO_5x5",
		"TIERS": "GOLD",
		"DIVISIONS": "I",
	}

	@classmethod
	def create(
		cls,
		tmp_path: Path,
		name: str,
		overrides: dict[str, str] | None = None,
		remove: set[str] | None = None,
		duplicates: list[tuple[str, str]] | None = None,
	) -> Path:
		data = dict(cls.BASE_VALID)
		if remove:
			for key in remove:
				data.pop(key, None)
		if overrides:
			data.update(overrides)

		lines = [f"{key}={value}" for key, value in data.items()]
		if duplicates:
			for key, value in duplicates:
				lines.append(f"{key}={value}")

		env_path = tmp_path / f"{name}.env"
		env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
		return env_path


def _clear_pipeline_env(monkeypatch: pytest.MonkeyPatch):
	keys = [
		"RIOT_API_KEY",
		"VERSION",
		"PLAYERS_FETCH_DEPTH",
		"FULL_VERIFICATION_POST",
		"REGION",
		"QUEUE",
		"TIERS",
		"DIVISIONS",
	]
	for key in keys:
		monkeypatch.delenv(key, raising=False)


class DBFactory:
	"""Provide utility methods for creating mock database rows for testing."""
 
	def __init__(self, conn):
		self.conn = conn
		self.faker = Faker()
 
	def _vary_int(self, variation: tuple[int, int] | None, default: int) -> int:
		if variation is None:
			return default
		low, high = variation
		return self.faker.random_int(low, high)
 
	def _vary_datetime_range(self, basetime: datetime, hours_range: float | None = None) -> str:
		if hours_range is None:
			return basetime.isoformat()
		seconds_range = hours_range * 3600
		offset_seconds = self.faker.random_int(int(-seconds_range), 0)
		return (basetime + timedelta(seconds=offset_seconds)).isoformat()
 
	def _vary_choice(self, variation: list | None, default):
		if not variation:
			return default
		return self.faker.random_element(variation)
 
	def _override_dict(self, base: dict, overrides: dict) -> dict:
		unknown = overrides.keys() - base.keys()
		assert not unknown, f"Unknown override keys: {unknown}"
		return {**base, **overrides}
 
	def _insert(self, table_name: str, data: dict, *, commit: bool, or_replace: bool = False):
		verb = "INSERT OR REPLACE" if or_replace else "INSERT"
		cur = self.conn.execute(
			f"{verb} INTO {table_name} ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
			tuple(data.values()),
		)
		if commit:
			self.conn.commit()
		return cur
 
	def get_uuid(self) -> str:
		return self.faker.uuid4()
 
	def create_individual_run(self, overrides: dict | None = None, commit: bool = True) -> int:
		now = datetime.now(timezone.utc).isoformat()
		defaults = {
			"pipeline_name": f"mock_{now}",
			"started_at": now,
			"last_heartbeat": None,
			"finished_at": None,
			"status": "running",
			"error_message": None,
		}
		data = self._override_dict(defaults, overrides or {})
		cur = self._insert("runs", data, commit=commit)
		return cur.lastrowid
 
	def create_individual_player_task(self, overrides: dict | None = None, commit: bool = True) -> int:
		now = datetime.now(timezone.utc).isoformat()
		defaults = {
			"run_id": None,
			"file_path": f"/tmp/player_mock_{now}.json",
			"status": "pending",
			"attempts": 0,
			"started_at": None,
			"finished_at": None,
			"error_message": None,
		}
		data = self._override_dict(defaults, overrides or {})
		assert data["run_id"] is not None, "player_tasks.run_id is required"
		cur = self._insert("player_tasks", data, commit=commit)
		return cur.lastrowid
 
	def create_individual_mastery_task(self, overrides: dict | None = None, commit: bool = True) -> int:
		player_id = self.faker.uuid4()
		defaults = {
			"run_id": None,
			"file_path": f"/tmp/mastery_{player_id}.json",
			"player_id": player_id,
			"status": "pending",
			"attempts": 0,
			"started_at": None,
			"finished_at": None,
			"error_message": None,
		}
		data = self._override_dict(defaults, overrides or {})
		assert data["run_id"] is not None, "mastery_tasks.run_id is required"
		cur = self._insert("mastery_tasks", data, commit=commit)
		return cur.lastrowid
 
	def create_individual_players_recorded(self, overrides: dict | None = None, commit: bool = True) -> str:
		player_id = (overrides or {}).get("player_id") or self.faker.uuid4()
		defaults = {
			"player_id": player_id,
			"region": "na1",
			"queue": "RANKED_SOLO_5x5",
			"tier": "GOLD",
			"division": "I",
			"player_task_ids": json.dumps([]),
			"paths": json.dumps([]),
			"paths_logged_at": json.dumps([]),
			"patches_logged": json.dumps([]),
			"mastery_task_id": None,
			"mastery_status": "pending",
			"mastery_path": None,
			"mastery_logged_at": None,
			"mastery_patch": None,
		}
		data = self._override_dict(defaults, overrides or {})
		self._insert("players_recorded", data, commit=commit)
		return data["player_id"]
 
	def create_individual_tier_division_page(self, overrides: dict | None = None, commit: bool = True) -> tuple:
		defaults = {
			"region": "na1",
			"queue": "RANKED_SOLO_5x5",
			"tier": "GOLD",
			"division": "I",
			"patch": "vtest",
			"current_page": 1,
			"last_player_count": 0,
			"last_updated_at": datetime.now(timezone.utc).isoformat(),
			"loop_count": 0,
		}
		data = self._override_dict(defaults, overrides or {})
		self._insert("tier_division_pages", data, commit=commit, or_replace=True)
		return (data["region"], data["queue"], data["tier"], data["division"], data["patch"])
 
	def create_mock_run(
		self,
		run_override: dict | None = None,
		player_task_override: dict | None = None,
		mastery_task_override: dict | None = None,
		record_override: dict | None = None,
		players_per_task: int = 205,
		region: str = "na1",
		queue: str = "RANKED_SOLO_5x5",
		patch: str = "vtest",
		tier_variation: list[str] = ["DIAMOND", "EMERALD", "PLATINUM", "GOLD", "SILVER", "BRONZE", "IRON"],
		division_variation: list[str] = ["I", "II", "III", "IV"],
		run_status_variation: list[str] = ["failed", "success", "running"],
		last_heartbeat_variation: float = 1.5,  # Hours
		run_started_at_variation: int = 2,
		player_task_status_variation: list[str] = ["success", "failed", "pending", "in_progress"],
		mastery_task_status_variation: list[str] = ["success", "failed", "pending", "in_progress"],
		attempts_variation: tuple[int, int] = (1, 3),
		started_at_variation: int = 2,
		tasks_per_player_recorded_variation: tuple[int, int] = (1, 3),
	) -> dict:
		"""Simulate a full run, its tasks, and records."""
		run_override = run_override or {}
		player_task_override = player_task_override or {}
		mastery_task_override = mastery_task_override or {}
		record_override = record_override or {}
 
		# run
		run_status = self._vary_choice(run_status_variation, "success")
		started = self._vary_datetime_range(datetime.now(timezone.utc), run_started_at_variation)
		run_values = {
			"pipeline_name": "mock_run",
			"started_at": started,
			"last_heartbeat": self._vary_datetime_range(datetime.now(timezone.utc), last_heartbeat_variation),
			"finished_at": (
				(datetime.fromisoformat(started) + timedelta(seconds=self.faker.random.uniform(240, 600))).isoformat()
				if run_status == "success" else None
			),
			"status": run_status,
			"error_message": None,
		}
		run_id = self.create_individual_run({**run_values, **run_override}, commit=False)
 
		player_task_ids = []
		mastery_task_ids = []
		player_ids = []
 
		# player task
		pt_status = self._vary_choice(player_task_status_variation, "success")
		pt_started = self._vary_datetime_range(datetime.now(timezone.utc), started_at_variation)
		player_task_values = {
			"run_id": run_id,
			"file_path": f"/tmp/player_mock_{run_id}.json",
			"status": pt_status,
			"attempts": self._vary_int(attempts_variation, 0),
			"started_at": pt_started,
			"finished_at": (
				(datetime.fromisoformat(pt_started) + timedelta(milliseconds=self.faker.random.uniform(10, 1500))).isoformat()
				if pt_status == "success" else None
			),
			"error_message": None,
		}
		player_task_id = self.create_individual_player_task(
			{**player_task_values, **player_task_override}, commit=False
		)
		player_task_ids.append(player_task_id)
 
		for _ in range(players_per_task):
			# mastery task
			mt_status = self._vary_choice(mastery_task_status_variation, "success")
			mt_started = self._vary_datetime_range(datetime.now(timezone.utc), started_at_variation)
			player_id = self.faker.uuid4()
			mastery_values = {
				"run_id": run_id,
				"file_path": f"/tmp/mastery_{player_id}.json",
				"player_id": player_id,
				"status": mt_status,
				"attempts": self._vary_int(attempts_variation, 0),
				"started_at": mt_started,
				"finished_at": (
					(datetime.fromisoformat(mt_started) + timedelta(milliseconds=self.faker.random.uniform(10, 1500))).isoformat()
					if mt_status == "success" else None
				),
				"error_message": None,
			}
			mastery_task_id = self.create_individual_mastery_task(
				{**mastery_values, **mastery_task_override}, commit=False
			)
			mastery_task_ids.append(mastery_task_id)
 
			# player recorded
			recorded_player_task_ids = [player_task_id]
			paths = [f"/tmp/player_{player_id}.json"]
			paths_logged_at = [datetime.now(timezone.utc).isoformat()]
			for fake in range(self._vary_int(tasks_per_player_recorded_variation, 1)):
				recorded_player_task_ids.insert(0, -(fake + 1))  # negative: never collides with real autoincrement ids
				paths.insert(0, f"/tmp/player_{player_id}_{fake}.json")
				paths_logged_at.insert(0, datetime.now(timezone.utc).isoformat())
 
			record_values = {
				"player_id": player_id,
				"region": region,
				"queue": queue,
				"tier": self._vary_choice(tier_variation, "GOLD"),
				"division": self._vary_choice(division_variation, "I"),
				"player_task_ids": json.dumps(recorded_player_task_ids),
				"paths": json.dumps(paths),
				"paths_logged_at": json.dumps(paths_logged_at),
				"patches_logged": json.dumps([patch]),
				"mastery_task_id": mastery_task_id,
				"mastery_status": mastery_values["status"],
				"mastery_path": mastery_values["file_path"],
				"mastery_logged_at": datetime.now(timezone.utc).isoformat(),
				"mastery_patch": patch,
			}
			self.create_individual_players_recorded(
				{**record_values, **record_override}, commit=False
			)
			player_ids.append(player_id)
 
		# page
		page_values = {
			"region": region,
			"queue": queue,
			"tier": self._vary_choice(tier_variation, "GOLD"),
			"division": self._vary_choice(division_variation, "I"),
			"patch": patch,
			"current_page": 1,
			"last_player_count": len(player_ids),
			"last_updated_at": datetime.now(timezone.utc).isoformat(),
			"loop_count": 0,
		}
		self.create_individual_tier_division_page(page_values, commit=False)
 
		self.conn.commit()
 
		return {
			"run_id": run_id,
			"player_task_ids": player_task_ids,
			"mastery_task_ids": mastery_task_ids,
			"player_ids": player_ids,
		}


def create_player_payload(puuid: str, **overrides) -> dict:
	data = {
		"queueType": "RANKED_SOLO_5x5",
		"tier": "GOLD",
		"rank": "I",
		"puuid": puuid,
		"leaguePoints": 50,
		"wins": 10,
		"losses": 5,
		"veteran": False,
		"inactive": False,
		"freshBlood": False,
		"hotStreak": False,
	}
	data.update(overrides)
	return data


def create_mastery_payload(puuid: str, champion_id: int = 1, **overrides) -> dict:
	data = {
		"puuid": puuid,
		"championId": champion_id,
		"championLevel": 5,
		"championPoints": 1000,
		"lastPlayTime": 1234567890,
		"championPointsSinceLastLevel": 100,
		"championPointsUntilNextLevel": 200,
		"milestoneGrades": [],
	}
	data.update(overrides)
	return data

class FakeResponse:
	"""Stand-in for requests.Response, no real HTTP involved."""

	def __init__(self, payload, status_code: int = 200):
		self._payload = payload
		self.status_code = status_code
		self.ok = status_code == 200
		self.text = "" if self.ok else "simulated error"

	def json(self):
		return self._payload

class FakeAPIClient:
	"""Minimal stand-in for the APIClient protocol (get_patch/get), with no real network calls."""

	def __init__(self, players_payload=None, masteries_payload=None, patch: str = "15.1", status_code: int = 200):
		self.players_payload = players_payload if players_payload is not None else []
		self.masteries_payload = masteries_payload if masteries_payload is not None else []
		self.patch = patch
		self.status_code = status_code
		self.calls: list[tuple[str, dict]] = []

	def get_patch(self) -> str:
		return self.patch

	def get(self, url: str, **kwargs):
		self.calls.append((url, kwargs))
		if "champion-mastery" in url:
			return FakeResponse(self.masteries_payload, self.status_code)
		return FakeResponse(self.players_payload, self.status_code)

def assert_valid_player_file(path: Path, *, region: str, queue: str, tier: str, division: str, patch: str, expected_puuids) -> dict:
	assert path.is_file()
	payload = json.loads(path.read_text(encoding="utf-8"))
	assert payload["region"] == region
	assert payload["queue"] == queue
	assert payload["tier"] == tier
	assert payload["division"] == division
	assert payload["patch"] == patch
	actual_puuids = {player["puuid"] for player in payload["players"]}
	assert actual_puuids == set(expected_puuids)
	return payload