import logging
import sqlite3

from loguru import logger
import pytest
import t_utilities as util
from pathlib import Path
util.set_path_for_extract_modules()
import run_pipeline as pl

@pytest.fixture
def pipeline_stub(monkeypatch: pytest.MonkeyPatch):
    """Stub side-effectful runtime parts so tests focus on env/config handling."""

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
def mock_db(tmp_path):
	"""Create a temporary database file for testing."""
	db_path = tmp_path / "test_pipeline.db"
	conn = sqlite3.connect(db_path)
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA foreign_keys=ON;")
	conn.row_factory = sqlite3.Row

	schema_path = Path(__file__).resolve().parents[1] / "schemas.sql"
	SCHEMA = schema_path.read_text(encoding="utf-8")
	conn.executescript(SCHEMA)
	conn.commit()

	yield conn
	conn.close()
 
@pytest.fixture
def db_factory(request):
	"""Provide a DBFactory instance for creating test data."""
	def _create_factory(mock_db):
		return util.DBFactory(mock_db)
	return _create_factory


#make loguru work with pytest, so we can capture loguru logs in pytest by redirecting them to the standard logging
@pytest.fixture(autouse=True)
def _loguru_to_caplog():
    logger.remove()  # strip loguru's default stderr sink
    handler_id = logger.add(PropagateHandler(), format="{message}")
    yield
    logger.remove(handler_id)

class PropagateHandler(logging.Handler):
    def emit(self, record):
        logging.getLogger(record.name).handle(record)