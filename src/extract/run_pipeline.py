"""Python script to run the local extraction pipeline.\n
Fetches players and their masteries from the Riot API and stores them in raw data folders.\n
The pipeline is designed to be run in a loop, fetching players snapshots of 200+ and then their masteries in batches.\n
Outputs orchestration metadata, as well as the records of each player and mastery fetched, to a local sqlite database for tracking and verification.\n
After running for the designated amount of loops, the pipeline will verify the integrity of the files and database, and log any issues found.
"""

import json
from math import e
import os
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv
from loguru import logger

import extract.api_client as client
import extract.compact_parquets as compact
import extract.extraction_db_helper as db
import extract.init_extraction_db as init_db
import extract.refresh_stale_players as refresh_stale
import extract.verify_integrity as verify
import pydantic_models as models
from extract.get_masteries import run as extract_masteries
from extract.get_players import run as extract_players
from load.load_champions_to_databricks import load_champions
from load.load_compacted_to_databricks import load_compacted
from extract.reset_extraction_state import reset_local_data

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "EXTRACTION_CONFIG.env"


def run_pipeline(config_path: Path = CONFIG_PATH) -> bool:
    config_manifest, success = get_configs(config_path)

    if not success:
        logger.error("Failed to load configuration. Exiting.")
        return False
    try:
        validated_manifest = models.ExtractionConfigManifest.model_validate(config_manifest).model_dump()
    except RuntimeError as e:
        logger.error(f"Invalid configuration: {e}")
        return False

    if not init_db.db_exists():
        init_db.reset_database()

    db.cleanup_stale_runs()
    if not db.is_active():
        logger.error(
            "Cannot connect to database. Ensure init_db has been run and the database is accessible in the correct folder."
        )
        return False

    api_client = client.RiotAPIClient(api_key=validated_manifest["api_key"])
    return extraction_loop(validated_manifest, api_client=api_client)


@dataclass
class run_result:
    run_number: int
    run_date: str
    job_date: str
    snapshot_result: bool
    refresh_result: dict
    integrity_result: dict
    load_result: dict


def extraction_loop(config_manifest: dict, api_client) -> bool:
    """Run the local pipeline."""

    pages_per_division = int(config_manifest["players_fetch_depth"])
    target_tier = config_manifest["tiers"]
    target_division = config_manifest["divisions"]
    runs_per_load = int(config_manifest["runs_per_load"])
    runs_remaining = pages_per_division * len(target_tier) * len(target_division)
    job_date = datetime.now(timezone.utc).isoformat()
    job_results: list[run_result] = []

    run_n = 0
    try:
        while runs_remaining > run_n:
            run_date = datetime.now(timezone.utc).isoformat()

            # Get new players and their missing masteries
            snapshot_result = run_snapshot_fetchers(config_manifest, run_n, run_date, api_client)

            # Fetch stale players and their masteries based on postgresql loaded database
            refresh_result = run_stale_refresh(config_manifest, run_n, run_date, api_client)

            # Compact and load data into the database
            load_result = {}
            integrity_result = {}
            if run_n % runs_per_load == 0 and run_n != 0:
                # Run integrity check before compacting and loading data, ensuring the database is in a consistent state
                integrity_result = verify.run_integrity_check(config_manifest["full_check"])
                # Compact all parquets then load
                compact.run()
                load_result = run_load()
                # Delete all local data and database after compact and load
                reset_local_data()

            job_results.append(
                run_result(
                    run_number=run_n,
                    run_date=run_date,
                    job_date=job_date,
                    snapshot_result=snapshot_result,
                    refresh_result=refresh_result,
                    integrity_result=integrity_result,
                    load_result=load_result,
                )
            )

            log_path = BASE_DIR / "data" / "logs" / "job_results.json"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_data = [r.__dict__ for r in job_results]
            log_path.write_text(json.dumps(log_data, indent=2), encoding="utf-8")

            run_n += 1

    except RuntimeError as e:
        logger.error(f"Pipeline encountered an error: {e}")
        return False

    return True


def run_snapshot_fetchers(config_manifest: dict, run_n, date, api_client) -> bool:
    try:
        run_id = db.start_run(f"fetch_{config_manifest['version']}_{run_n}_{date}")
        logger.info(f"Starting new pipeline run with ID: {run_id}.")
        extract_players(
            run_id,
            api_client=api_client,
            region=config_manifest["region"],
            queue=config_manifest["queue"],
        )
        extract_masteries(
            run_id,
            api_client=api_client,
            limit=int(config_manifest["mastery_task_limit"]),
            run_n=run_n,
        )  # set a higher than the limit riot gives us (205 at the time of writing) but thats so we can find some extra masteries if we missed some players in the last run, while not freezing the application searching through potentially thousands of players for masteries
        db.finish_run(run_id, "success")
        return True
    except RuntimeError:
        logger.exception(f"An error occurred during the pipeline run: {e}")
        db.finish_run(run_id, "failed")
        db.cleanup_failed_run(run_id)
        return False


def run_stale_refresh(config_manifest: dict, run_n, date, api_client) -> dict:
    run_id = db.start_run(f"refresh_{config_manifest['version']}_{run_n}_{date}")
    logger.info(f"Starting stale-player refresh run with ID: {run_id}.")
    try:
        summary = refresh_stale.run(
            run_id,
            api_client=api_client,
            limit=int(config_manifest["stale_refresh_limit"]),
            freshness_minutes=int(config_manifest["freshness_threshold_minutes"]),
            claim_timeout_minutes=int(config_manifest["stale_claim_timeout_minutes"]),
        )
        db.finish_run(run_id, "success")
        return summary
    except RuntimeError as e:
        logger.exception(f"Stale-player refresh run failed: {e}")
        db.finish_run(run_id, "failed")
        db.cleanup_failed_run(run_id)
        return {"status": False, "claimed": 0, "players_refreshed": 0, "masteries_refreshed": 0}


def run_load() -> dict:
    try:
        champion_load_result = load_champions()
        logger.info(f"Champion load result: {champion_load_result}")
        compacted_load_result = load_compacted()
        logger.info(f"Compacted load result: {compacted_load_result}")
        return {
            "status": True,
            "champion_load_result": champion_load_result,
            "compacted_load_result": compacted_load_result,
        }
    except RuntimeError as e:
        logger.exception(f"Compaction and load failed: {e}")
        return {
            "status": False,
            "champion_load_result": None,
            "compacted_load_result": None,
        }


def get_configs(config_path: Path) -> tuple[dict, bool]:
    load_dotenv(config_path)
    api_key = os.getenv("RIOT_API_KEY")
    version = os.getenv("VERSION")
    players_fetch_depth = os.getenv("PLAYERS_FETCH_DEPTH")
    mastery_task_limit = os.getenv("MASTERY_TASK_LIMIT")
    full_check = os.getenv("FULL_VERIFICATION_POST", "false").lower() == "true"
    region = os.getenv("REGION")
    queue = os.getenv("QUEUE")
    tiers = os.getenv("TIERS", "DIAMOND,EMERALD,PLATINUM,GOLD,SILVER,BRONZE,IRON").split(",")
    divisions = os.getenv("DIVISIONS", "I,II,III,IV").split(",")
    freshness_threshold_minutes = os.getenv("FRESHNESS_THRESHOLD_MINUTES", "10080")
    stale_claim_timeout_minutes = os.getenv("STALE_CLAIM_TIMEOUT_MINUTES", "30")
    stale_refresh_limit = os.getenv("STALE_REFRESH_LIMIT", "50")
    runs_per_load = os.getenv("RUNS_PER_LOAD", "10")
    if not api_key or not version or not players_fetch_depth or not mastery_task_limit or not region or not queue:
        logger.error("Missing required environment variables.")
        return {}, False
    return {
        "api_key": api_key,
        "version": version,
        "players_fetch_depth": players_fetch_depth,
        "mastery_task_limit": mastery_task_limit,
        "full_check": full_check,
        "region": region,
        "queue": queue,
        "tiers": tiers,
        "divisions": divisions,
        "freshness_threshold_minutes": freshness_threshold_minutes,
        "stale_claim_timeout_minutes": stale_claim_timeout_minutes,
        "stale_refresh_limit": stale_refresh_limit,
        "runs_per_load": runs_per_load,
    }, True


if __name__ == "__main__":
    run_pipeline()
