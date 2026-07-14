from get_players import run as extract_players
from get_masteries import run as extract_masteries
import pipeline_db as db
import os
import client
from loguru import logger
from dotenv.main import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] 

def run_pipeline():
	"""Run the local pipeline."""
	db.cleanup_stale_runs()
	try:
		load_dotenv(BASE_DIR / "config" / "RIOT_API_KEY.env")
		api_key = os.getenv("RIOT_API_KEY")
		if not api_key:
			logger.error("No Riot API key provided. Please set the RIOT_API_KEY environment variable.")
			return

		api_client = client.RiotAPIClient(api_key=api_key)
		load_dotenv(BASE_DIR / "config" / "VERSION.env")
		version = os.getenv("VERSION")
		count = 1000
		while count > 0:
			run_id = db.start_run(f"local_{count}_{version}")
			logger.info(f"Starting new pipeline run with ID: {run_id}. Remaining runs: {count}")
			players_manifest = extract_players(run_id, api_key=api_key, api_client=api_client)
			if players_manifest:
				extract_masteries(players_manifest, run_id, api_key=api_key, api_client=api_client)
				db.finish_run(run_id, "success")
			else:
				db.finish_run(run_id, "failed", error_message="No players manifest returned.")
			count -= 1
	except:
		db.cleanup_failed_run(run_id)
		logger.exception("An error occurred during the pipeline run.")



if __name__ == "__main__":
	run_pipeline()