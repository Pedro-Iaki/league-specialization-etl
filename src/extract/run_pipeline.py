"""Python script to run the local extraction pipeline.\n 
Fetches players and their masteries from the Riot API and stores them in raw data folders.\n
The pipeline is designed to be run in a loop, fetching players snapshots of 200+ and then their masteries in batches.\n
Outputs orchestration metadata, as well as the records of each player and mastery fetched, to a local sqlite database for tracking and verification.\n
After running for the designated amount of loops, the pipeline will verify the integrity of the files and database, and log any issues found.
"""
from datetime import datetime

from get_players import run as extract_players
from get_masteries import run as extract_masteries
import pipeline_db as db
import os
import client
from loguru import logger
from dotenv.main import load_dotenv
from pathlib import Path
import verify_integrity as verify

BASE_DIR = Path(__file__).resolve().parents[2] 
DEFAULT_REGION = "na1"
DEFAULT_QUEUE = "RANKED_SOLO_5x5"


def run_pipeline():
	"""Run the local pipeline."""
	if not db.is_active():
		logger.error("Cannot connect to database. Ensure init_db has been run and the database is accessible in the correct folder.")
		return
	db.cleanup_stale_runs()

	load_dotenv(BASE_DIR / "config" / "RIOT_API_KEY.env")
	api_key = os.getenv("RIOT_API_KEY")
	if not api_key:
		logger.error("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
		return

	load_dotenv(BASE_DIR / "config" / "VERSION.env")
	version = os.getenv("VERSION")
	if not version:
		logger.error("No version provided. Please set the VERSION environment variable.")
		return

	api_client = client.RiotAPIClient(api_key=api_key)
	count = 1
	date = datetime.now().isoformat()
	try:
		while count > 0:
			run_id = db.start_run(f"local_{version}_{count}_{date}")
			logger.info(f"Starting new pipeline run with ID: {run_id}.")
			extract_players(run_id, api_client=api_client, region=DEFAULT_REGION, queue=DEFAULT_QUEUE)
			extract_masteries(run_id, api_client=api_client, limit=1) # a bit higher than the limit riot gives us but thats so we can find some extra masteries if we missed some players in the last run, while not freezing the application searching through potentially thousands of players for masteries
			db.finish_run(run_id, "success")
			count -= 1
	except Exception as e:
		logger.exception(f"An error occurred during the pipeline run: {e}")
		db.finish_run(run_id, "failed")
		db.cleanup_failed_run(run_id)

	integrity_log = verify.run_integrity_check(True)
	database_log = integrity_log.get("database", {})
	logger.info(f"\nIntegrity check completed. Results: \nTotal players in database: {database_log.get('total_player_records', 0)}\nFaulty or incomplete records: {database_log.get('faulty_records_count', 0)}\nDuplicated player rate: {database_log.get('duplicated_players', 0)}\nDiscarded duplicated snapshots: {database_log.get('discarded_player_tasks', 0)}\nPlayer task error rate: {database_log.get('player_task_error_rate', 0)}\nMastery task error rate: {database_log.get('mastery_task_error_rate', 0)}")

if __name__ == "__main__":
	run_pipeline()
