import logging
import random
import sqlite3

from loguru import logger
import pytest
import t_utilities as util
from pathlib import Path
util.set_path_for_extract_modules()
import run_pipeline as pl

@pytest.fixture
def pipeline_stub(monkeypatch: pytest.MonkeyPatch):
	class DummyClient:
		def __init__(self, api_key: str):
			self.api_key = api_key

	captured: dict[str, object] = {}

	def fake_extraction_loop(config_manifest: dict, api_client) -> bool:
		captured["config_manifest"] = config_manifest
		captured["api_key"] = api_client.api_key
		return True

	monkeypatch.setattr(pl.db, "cleanup_stale_runs", lambda: None)
	monkeypatch.setattr(pl.db, "is_active", lambda: True)
	monkeypatch.setattr(pl.client, "RiotAPIClient", DummyClient)
	monkeypatch.setattr(pl, "extraction_loop", fake_extraction_loop)
	return captured

@pytest.fixture
def mock_conn(tmp_path):
	"""Create a temporary database file for testing."""
	db_path = tmp_path / "test_pipeline.db"
	conn = sqlite3.connect(db_path)
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA foreign_keys=ON;")
	conn.row_factory = sqlite3.Row

	schema_path = Path(__file__).resolve().parents[1] / "extraction_schemas.sql"
	SCHEMA = schema_path.read_text(encoding="utf-8")
	conn.executescript(SCHEMA)
	conn.commit()

	yield conn
	conn.close()
 
@pytest.fixture
def db_factory():
	"""Provide a DBFactory instance for creating test data."""
	def _create_factory(_mock_conn):
		return util.DBFactory(_mock_conn)
	return _create_factory

@pytest.fixture
def mock_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
	"""Patch pipeline_db.get_connection so any module using it reads/writes an isolated test database file."""
	db_path = tmp_path / "test_pipeline.db"

	conn = sqlite3.connect(db_path)
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA foreign_keys=ON;")
	schema_path = Path(__file__).resolve().parents[1] / "extraction_schemas.sql"
	conn.executescript(schema_path.read_text(encoding="utf-8"))
	conn.commit()
	conn.close()

	def _get_connection(_: str = pl.db.DB_PATH) -> sqlite3.Connection:
		c = sqlite3.connect(db_path)
		c.execute("PRAGMA journal_mode=WAL;")
		c.execute("PRAGMA foreign_keys=ON;")
		c.row_factory = sqlite3.Row
		return c

	monkeypatch.setattr(pl.db, "get_connection", _get_connection)
	return pl.db


@pytest.fixture(autouse=True)
def _loguru_to_caplog():
	logger.remove()  # strip loguru's default stderr sink
	handler_id = logger.add(PropagateHandler(), format="{message}")
	yield
	logger.remove(handler_id)

class PropagateHandler(logging.Handler):
	def emit(self, record):
		logging.getLogger(record.name).handle(record)

#seeds for the random and faker modules, and a way to log it
SUITE_SEED = random.randint(0, 2**32 - 1)
logger.info(f"Seed: {SUITE_SEED}")

@pytest.fixture(scope="session", autouse=True)
def faker_seed():
    return SUITE_SEED

@pytest.fixture(scope="session", autouse=True)
def global_runtime_seed():
    random.seed(SUITE_SEED)