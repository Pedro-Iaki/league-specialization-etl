"""Python script to run the local extraction pipeline.\n 
Fetches players and their masteries from the Riot API and stores them in raw data folders.\n
The pipeline is designed to be run in a loop, fetching players snapshots of 200+ and then their masteries in batches.\n
Outputs orchestration metadata, as well as the records of each player and mastery fetched, to a local sqlite database for tracking and verification.\n
After running for the designated amount of loops, the pipeline will verify the integrity of the files and database, and log any issues found.
"""
from datetime import datetime
from get_players import run as extract_players
from get_masteries import run as extract_masteries
import extraction_db_helper as db
import os
import api_client as client
from loguru import logger
from dotenv import load_dotenv
from pathlib import Path
import verify_integrity as verify
import src.pydantic_models as models

BASE_DIR = Path(__file__).resolve().parents[2] 
CONFIG_PATH = BASE_DIR / "config" / "EXTRACTION_CONFIG.env"

def run_pipeline(config_path: Path = CONFIG_PATH) -> bool:
	config_manifest, success = get_configs(config_path)
	
	if not success:
		logger.error("Failed to load configuration. Exiting.")
		return False
	try:
		validated_manifest = models.ExtractionConfigManifest.model_validate(config_manifest).model_dump()
	except Exception as e:
		logger.error(f"Invalid configuration: {e}")
		return False
	
	db.cleanup_stale_runs()
	if not db.is_active():
		logger.error("Cannot connect to database. Ensure init_db has been run and the database is accessible in the correct folder.")
		return False
  
	api_client = client.RiotAPIClient(api_key=validated_manifest["api_key"])
	return extraction_loop(validated_manifest, api_client=api_client)

def extraction_loop(config_manifest: dict, api_client) -> bool:
	"""Run the local pipeline."""
	pages_per_division = int(config_manifest["players_fetch_depth"])
	target_tier = config_manifest["tiers"]
	target_division = config_manifest["divisions"]
	runs_remaining = pages_per_division * len(target_tier) * len(target_division)
	date = datetime.now().isoformat()
	try:
		while runs_remaining > 0:
			run_id = db.start_run(f"local_{config_manifest['version']}_{runs_remaining}_{date}")
			logger.info(f"Starting new pipeline run with ID: {run_id}.")
			extract_players(run_id, api_client=api_client, region=config_manifest["region"], queue=config_manifest["queue"])
			extract_masteries(run_id, api_client=api_client, limit=400, runs_remaining=runs_remaining) # set a higher than the limit riot gives us (205 at the time of writing) but thats so we can find some extra masteries if we missed some players in the last run, while not freezing the application searching through potentially thousands of players for masteries
			db.finish_run(run_id, "success")
			runs_remaining -= 1
	except Exception as e:
		logger.exception(f"An error occurred during the pipeline run: {e}")
		db.finish_run(run_id, "failed")
		db.cleanup_failed_run(run_id)	
		return False
	
	verify.run_integrity_check(config_manifest["full_check"])
	return True
 
def get_configs(config_path: Path) -> tuple[dict, bool]:
	load_dotenv(config_path)
	api_key = os.getenv("RIOT_API_KEY")
	version = os.getenv("VERSION")
	players_fetch_depth = os.getenv("PLAYERS_FETCH_DEPTH")
	full_check = os.getenv("FULL_VERIFICATION_POST", "false").lower() == "true"
	region = os.getenv("REGION")
	queue = os.getenv("QUEUE")
	tiers = os.getenv("TIERS", "DIAMOND,EMERALD,PLATINUM,GOLD,SILVER,BRONZE,IRON").split(",")
	divisions = os.getenv("DIVISIONS", "I,II,III,IV").split(",")
	if not api_key or not version or not players_fetch_depth or not region or not queue:
		logger.error("Missing required environment variables.")
		return {}, False
	return {
		"api_key": api_key,
		"version": version,
		"players_fetch_depth": players_fetch_depth,
		"full_check": full_check,
		"region": region,
		"queue": queue,
		"tiers": tiers,
		"divisions": divisions,
	}, True

if __name__ == "__main__":
	run_pipeline()