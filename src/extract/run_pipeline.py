from datetime import datetime

from get_players import run as extract_players
from get_masteries import run as extract_masteries
import pipeline_db as db
import os
import client
from loguru import logger
from dotenv.main import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] 
DEFAULT_REGION = "na1"
DEFAULT_QUEUE = "RANKED_SOLO_5x5"


def run_pipeline():
	"""Run the local pipeline."""
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
	count = 1000
	date = datetime.now().isoformat()
	try:
		while count > 0:
			run_id = db.start_run(f"local_{version}_{count}_{date}")
			logger.info(f"Starting new pipeline run with ID: {run_id}.")
			extract_players(run_id, api_client=api_client, region=DEFAULT_REGION, queue=DEFAULT_QUEUE)
			extract_masteries(run_id, api_client=api_client, limit=220)
			db.finish_run(run_id, "success")
			count -= 1
	except Exception as e:
		logger.exception(f"An error occurred during the pipeline run: {e}")
		db.finish_run(run_id, "failed")
		db.cleanup_failed_run(run_id)


if __name__ == "__main__":
	run_pipeline()
