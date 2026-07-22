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

	load_dotenv(BASE_DIR / "config" / "EXTRACTION_CONFIG.env")
	api_key = os.getenv("RIOT_API_KEY")
	version = os.getenv("VERSION")
	players_fetch_depth = os.getenv("PLAYERS_FETCH_DEPTH")
	full_check = os.getenv("FULL_VERIFICATION_POST", "false").lower() == "true"
	if not api_key or not version or not players_fetch_depth or not full_check:
		logger.error("Missing required environment variables.")
		return

	api_client = client.RiotAPIClient(api_key=api_key)
	pages_per_division = int(players_fetch_depth) # this is the number you'll likely want to configure, it controls how many pages we fetch per division-tier combination.
	runs_remaining = pages_per_division*28 # a bit of a "magic number", 28 is the total division-tier combinations
	date = datetime.now().isoformat()
	try:
		while runs_remaining > 0:
			run_id = db.start_run(f"local_{version}_{runs_remaining}_{date}")
			logger.info(f"Starting new pipeline run with ID: {run_id}.")
			extract_players(run_id, api_client=api_client, region=DEFAULT_REGION, queue=DEFAULT_QUEUE)
			extract_masteries(run_id, api_client=api_client, limit=225, runs_remaining=runs_remaining) # set a bit higher than the limit riot gives us (205 at the time of writing) but thats so we can find some extra masteries if we missed some players in the last run, while not freezing the application searching through potentially thousands of players for masteries
			db.finish_run(run_id, "success")
			runs_remaining -= 1
	except Exception as e:
		logger.exception(f"An error occurred during the pipeline run: {e}")
		db.finish_run(run_id, "failed")
		db.cleanup_failed_run(run_id)

	verify.run_integrity_check(full_check)	

if __name__ == "__main__":
	run_pipeline()
