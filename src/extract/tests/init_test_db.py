from pathlib import Path
import sqlite3
import os
import shutil
from loguru import logger

DEFAULT_TEST_PATH = "src/extract/tests/mock_data"
TEST_DB_NAME = "test2_pipeline_meta"

def get_connection(db_path: Path):
	conn = sqlite3.connect(db_path)
	conn.execute("PRAGMA journal_mode=WAL;")
	conn.execute("PRAGMA foreign_keys=ON;")
	conn.row_factory = sqlite3.Row
	return conn


def get_next_db_name(test_path: str) -> str:
	"""Find the highest numbered test database and increment by 1."""
	test_dir = Path(test_path)
	if not test_dir.exists():
		logger.warning(f"Test directory {test_path} did not exist. Creating it.")
		test_dir.mkdir(parents=True, exist_ok=True)
		return f"{TEST_DB_NAME}_0.db"
	
	existing_dbs = list(test_dir.glob(f"{TEST_DB_NAME}_*.db"))
	if not existing_dbs:
		return f"{TEST_DB_NAME}_0.db"
	
	max_num = max(
		int(db.stem.split("_")[-1])
		for db in existing_dbs
		if db.stem.split("_")[-1].isdigit()
	)
	return f"{TEST_DB_NAME}_{max_num + 1}.db"


db_name = get_next_db_name(DEFAULT_TEST_PATH)

with open("src/extract/schemas.sql", "r") as f:
	SCHEMA = f.read()
	
conn = get_connection(Path(DEFAULT_TEST_PATH) / db_name)
conn.executescript(SCHEMA)
conn.commit()
conn.close()