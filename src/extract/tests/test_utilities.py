import json
from datetime import datetime
from pathlib import Path
import sys
import pytest


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

	def create_run(self, values: dict | None = None) -> int:
		now = datetime.now().isoformat()
		defaults = {
			"pipeline_name": f"mock_{now}",
			"started_at": now,
			"last_heartbeat": None,
			"finished_at": None,
			"status": "running",
			"error_message": None,
		}
		data = {**defaults, **(values or {})}
		cur = self.conn.execute(
			f"INSERT INTO runs ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
			tuple(data.values()),
		)
		self.conn.commit()
		return cur.lastrowid

	def create_player_task(self, values: dict | None = None, run_id: int | None = None) -> int:
		run_id = run_id if run_id is not None else self.create_run()
		defaults = {
			"run_id": run_id,
			"file_path": None,
			"status": "pending",
			"attempts": 0,
			"started_at": None,
			"finished_at": None,
			"error_message": None,
		}
		data = {**defaults, **(values or {})}
		cur = self.conn.execute(
			f"INSERT INTO player_tasks ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
			tuple(data.values()),
		)
		self.conn.commit()
		return cur.lastrowid

	def create_mastery_task(self, values: dict | None = None, run_id: int | None = None) -> int:
		run_id = run_id if run_id is not None else self.create_run()
		now = datetime.now().isoformat()
		defaults = {
			"run_id": run_id,
			"file_path": None,
			"player_id": f"mock_player_{now}",
			"status": "pending",
			"attempts": 0,
			"started_at": None,
			"finished_at": None,
			"error_message": None,
		}
		data = {**defaults, **(values or {})}
		cur = self.conn.execute(
			f"INSERT INTO mastery_tasks ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
			tuple(data.values()),
		)
		self.conn.commit()
		return cur.lastrowid

	def create_players_recorded(self, values: dict | None = None) -> str:
		player_id = (values or {}).get("player_id") or f"mock_player_{datetime.now().timestamp()}"
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
		data = {**defaults, **(values or {})}
		self.conn.execute(
			f"INSERT INTO players_recorded ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
			tuple(data.values()),
		)
		self.conn.commit()
		return data["player_id"]

	def create_tier_division_page(self, values: dict | None = None):
		defaults = {
			"region": "na1",
			"queue": "RANKED_SOLO_5x5",
			"tier": "GOLD",
			"division": "I",
			"patch": "vtest",
			"current_page": 1,
			"last_player_count": 0,
			"last_updated_at": datetime.now().isoformat(),
			"loop_count": 0,
		}
		data = {**defaults, **(values or {})}
		self.conn.execute(
			f"INSERT INTO tier_division_pages ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",
			tuple(data.values()),
		)
		self.conn.commit()
		return (
			data["region"],
			data["queue"],
			data["tier"],
			data["division"],
			data["patch"],
		)