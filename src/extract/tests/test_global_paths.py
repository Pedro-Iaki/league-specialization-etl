from pathlib import Path

import init_db
import get_players
import get_masteries
import pipeline_db
import run_pipeline
import verify_integrity
import t_utilities as util

util.set_path_for_extract_modules()

# tests/ -> extract/ -> src/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_repo_root_is_resolved_consistently_across_modules():
	assert get_players.BASE_DIR == REPO_ROOT
	assert get_masteries.BASE_DIR == REPO_ROOT
	assert verify_integrity.BASE_DIR == REPO_ROOT
	assert run_pipeline.BASE_DIR == REPO_ROOT


def test_output_paths_point_at_expected_raw_data_folders():
	assert get_players.OUTPUT_PATH == REPO_ROOT / "data" / "raw" / "players"
	assert get_masteries.OUTPUT_PATH == REPO_ROOT / "data" / "raw" / "masteries"
	assert verify_integrity.PLAYERS_INPUT_PATH == get_players.OUTPUT_PATH
	assert verify_integrity.MASTERIES_PATH == get_masteries.OUTPUT_PATH


def test_verify_integrity_logs_path():
	assert verify_integrity.LOGS_PATH == REPO_ROOT / "data" / "logs"


def test_run_pipeline_config_path():
	assert run_pipeline.CONFIG_PATH == REPO_ROOT / "config" / "EXTRACTION_CONFIG.env"


def test_pipeline_db_path_is_relative_to_repo_root():
	assert pipeline_db.DB_PATH == "data/database/pipeline_meta.db"
	assert (REPO_ROOT / pipeline_db.DB_PATH).parent == REPO_ROOT / "data" / "database"


def test_expected_directories_exist_on_disk():
	assert (REPO_ROOT / "data" / "raw" / "players").is_dir()
	assert (REPO_ROOT / "data" / "raw" / "masteries").is_dir()
	assert (REPO_ROOT / "data" / "logs").is_dir()
	assert (REPO_ROOT / "data" / "database").is_dir()
	assert (REPO_ROOT / "config").is_dir()


def test_config_and_schema_files_exist_on_disk():
	assert run_pipeline.CONFIG_PATH.is_file()
	schema_path = REPO_ROOT / "src" / "extract" / "schemas.sql"
	assert schema_path.is_file()


def test_init_db_paths_match_expected_targets():
	assert init_db.DB_PATH == "data/database/pipeline_meta.db"
	assert init_db.PLAYERS_DIR == "data/raw/players"
	assert init_db.MASTERIES_DIR == "data/raw/masteries"
	assert init_db.SCHEMA_PATH == "src/extract/schemas.sql"