"""Collect snapshots and masteries, verify and compact files, then ingest and build.

SQLite records collection tasks and file/load status throughout the pipeline.
"""

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path

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
from extract.reset_extraction_state import reset_local_data
from load import player_registry
from load.build_dbt import run_dbt
from load.load_champions_to_databricks import load_champions
from load.load_compacted_to_databricks import load_compacted

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "EXTRACTION_CONFIG.env"
# Give stale-player work three times its observed share of the registry.
STALENESS_INTENSITY = 3
# Estimated full page, used when discovery is skipped or returns no players.
FALLBACK_SNAPSHOT_SIZE = 205


@dataclass
class run_result:
    run_number: int
    run_date: str
    job_date: str
    snapshot_result: dict
    refresh_result: dict
    integrity_result: dict
    load_result: dict
    status: bool = False
    stage: str = "staleness"
    error: str | None = None


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


def extraction_loop(config_manifest: dict, api_client) -> bool:
    """Run collection rounds and load at the configured cadence and final round."""
    pages_per_division = int(config_manifest["players_fetch_depth"])
    target_tier = config_manifest["tiers"]
    target_division = config_manifest["divisions"]
    runs_per_load = int(config_manifest["runs_per_load"])
    max_refresh_scale = float(config_manifest["max_refresh_scale"])
    runs_remaining = pages_per_division * len(target_tier) * len(target_division)
    job_date = datetime.now(timezone.utc).isoformat()
    job_results: list[run_result] = []

    for run_n in range(runs_remaining):
        run_date = datetime.now(timezone.utc).isoformat()
        result = run_result(run_n, run_date, job_date, {"status": "not_started"}, {}, {}, {})
        job_results.append(result)
        # Attach raised errors to the result of the stage currently executing.
        stage_result = result.refresh_result
        logger.info(f"Starting round {run_n + 1}/{runs_remaining}.")
        try:
            staleness = player_registry.get_staleness_fraction(
                config_manifest["region"], config_manifest["queue"],
                int(config_manifest["freshness_threshold_minutes"]),
                int(config_manifest["stale_claim_timeout_minutes"]),
            )
            refresh_scale = get_refresh_scale(staleness, max_refresh_scale)
            result.refresh_result.update({"staleness_fraction": staleness, "refresh_scale": refresh_scale})
            should_fetch_snapshot = refresh_scale < max_refresh_scale
            snapshot_size = FALLBACK_SNAPSHOT_SIZE

            result.stage = "snapshot"
            stage_result = result.snapshot_result
            if should_fetch_snapshot:
                result.snapshot_result.update(run_snapshot_fetchers(config_manifest, run_n, run_date, api_client))
                if result.snapshot_result["status"] == "failed":
                    result.error = "Player or mastery collection failed; local files retained."
                    return False
                observed_size = result.snapshot_result["snapshot_size"]
                if observed_size:
                    snapshot_size = observed_size
                else:
                    logger.debug(f"Using fallback snapshot size {snapshot_size} for refresh allocation.")
            else:
                result.snapshot_result.update({
                    "status": "skipped", "snapshot_size": None,
                    "reason": "Refresh scale reached MAX_REFRESH_SCALE; both snapshot fetchers skipped.",
                })
                logger.info("Skipping new-player collection to refresh previously collected players.")

            result.stage = "refresh"
            stage_result = result.refresh_result
            result.refresh_result["refresh_snapshot_size"] = snapshot_size
            refresh_limit = get_refresh_limit(snapshot_size, refresh_scale)
            result.refresh_result.update(run_stale_refresh(config_manifest, run_n, run_date, api_client, refresh_limit))
            if not result.refresh_result.get("status", True):
                result.error = "Previously collected players could not be refreshed; local files retained."
                return False

            if (run_n + 1) % runs_per_load == 0 or run_n + 1 == runs_remaining:
                result.stage = "integrity"
                stage_result = result.integrity_result
                result.integrity_result.update(verify.run_integrity_check(config_manifest["full_check"]))
                if not verify.is_compaction_ready(result.integrity_result):
                    result.error = "Collected data failed integrity checks; local files retained."
                    return False

                result.stage = "compaction"
                stage_result = result.integrity_result.setdefault("compaction", {})
                compact.run()
                result.stage = "compaction_integrity"
                stage_result.update(verify.verify_compaction_integrity())
                if not verify.is_load_ready(result.integrity_result):
                    result.error = "Compacted files failed verification; upload stopped and local files retained."
                    return False

                result.stage = "load"
                stage_result = result.load_result
                result.load_result.update(run_load())
                if not result.load_result["status"] or db.count_incomplete_loads():
                    if result.load_result.get("compacted_load_result") and not result.load_result.get("dbt_build_result"):
                        result.stage = "dbt_build"
                        result.error = "The warehouse build did not complete; local files retained."
                    else:
                        result.error = "Loading did not complete; local files retained."
                    return False

                result.stage = "cleanup"
                reset_local_data()
            result.status = True
            result.stage = "complete"
        except KeyboardInterrupt:
            stage_result["error"] = "Interrupted by operator."
            if result.stage == "snapshot":
                stage_result["status"] = "interrupted"
            result.error = "Interrupted by operator; local files retained."
            return False
        except Exception as error:  # noqa: BLE001 - finalize stage details and stop the round
            stage_result["error"] = str(error)
            if result.stage == "snapshot":
                stage_result["status"] = "failed"
            result.error = "An unexpected error stopped this round; local files retained."
            logger.exception(f"Round {run_n + 1} failed at {result.stage}.")
            return False
        finally:
            if not result.status:
                logger.error(f"Round {run_n + 1} stopped at {result.stage}: {result.error}")
            else:
                logger.info(f"Round {run_n + 1} completed.")
            log_path = BASE_DIR / "data" / "logs" / "job_results.json"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_data = [r.__dict__ for r in job_results]
            log_path.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    return True


def run_snapshot_fetchers(config_manifest: dict, run_n, date, api_client) -> dict:
    try:
        run_id = db.start_run(f"fetch_{config_manifest['version']}_{run_n}_{date}")
        logger.debug(f"Starting snapshot run {run_id}.")
        snapshot_size = extract_players(
            run_id,
            api_client=api_client,
            region=config_manifest["region"],
            queue=config_manifest["queue"],
            freshness_minutes=int(config_manifest["freshness_threshold_minutes"]),
            tiers=[str(getattr(tier, "value", tier)) for tier in config_manifest["tiers"]],
            divisions=[str(getattr(division, "value", division)) for division in config_manifest["divisions"]],
        )
        if snapshot_size is None:
            raise RuntimeError("Player snapshot fetch failed.")
        extract_masteries(
            run_id,
            api_client=api_client,
            limit=int(config_manifest["mastery_task_limit"]),
            run_n=run_n,
        )
        db.finish_run(run_id, "success")
        return {"status": "success", "snapshot_size": snapshot_size}
    except RuntimeError as err:
        logger.exception(f"An error occurred during the pipeline run: {err}")
        db.finish_run(run_id, "failed")
        db.cleanup_failed_run(run_id)
        return {"status": "failed", "snapshot_size": None, "error": str(err)}


def run_stale_refresh(config_manifest: dict, run_n, date, api_client, limit: int) -> dict:
    if not limit:
        logger.info("Refresh skipped: the calculated player limit is zero.")
        return {"status": True, "claimed": 0, "players_refreshed": 0, "masteries_refreshed": 0}
    run_id = db.start_run(f"refresh_{config_manifest['version']}_{run_n}_{date}")
    logger.debug(f"Starting refresh run {run_id} with a limit of {limit} players.")
    try:
        summary = refresh_stale.run(
            run_id,
            api_client=api_client,
            limit=limit,
            freshness_minutes=int(config_manifest["freshness_threshold_minutes"]),
            claim_timeout_minutes=int(config_manifest["stale_claim_timeout_minutes"]),
            region=config_manifest["region"],
            queue=config_manifest["queue"],
        )
        db.finish_run(run_id, "success")
        return summary
    except RuntimeError as e:
        logger.exception(f"Stale-player refresh run failed: {e}")
        db.finish_run(run_id, "failed")
        db.cleanup_failed_run(run_id)
        return {"status": False, "claimed": 0, "players_refreshed": 0, "masteries_refreshed": 0, "error": str(e)}


def run_load() -> dict:
    result = {
        "status": False,
        "champion_load_result": None,
        "compacted_load_result": None,
        "dbt_build_result": None,
    }
    try:
        logger.info("Loading champion reference data...")
        result["champion_load_result"] = load_champions()
        logger.info("Uploading and loading collected player files...")
        result["compacted_load_result"] = load_compacted()
        if result["compacted_load_result"]:
            logger.info("Building analytical tables...")
            result["dbt_build_result"] = run_dbt()
            result["status"] = result["dbt_build_result"]
            if result["status"]:
                logger.info("Player files loaded and analytical tables built.")
    except Exception as e:  # noqa: BLE001 - preserve local files after any load-stage failure
        result["error"] = str(e)
        logger.exception(f"Load or dbt build failed: {e}")
    return result


def get_refresh_scale(staleness_fraction: float, max_refresh_scale: float) -> float:
    """Convert weighted staleness into a capped refresh-to-snapshot scale."""
    staleness_proportion = STALENESS_INTENSITY * staleness_fraction
    if staleness_proportion >= 1:
        return max_refresh_scale
    refresh_scale = staleness_proportion / (1 - staleness_proportion)
    return min(max_refresh_scale, refresh_scale)


def get_refresh_limit(snapshot_size: int, refresh_scale: float) -> int:
    """Round the snapshot-relative allocation up to a whole number of players."""
    return ceil(snapshot_size * refresh_scale)


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
    max_refresh_scale = os.getenv("MAX_REFRESH_SCALE", "4")
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
        "max_refresh_scale": max_refresh_scale,
        "runs_per_load": runs_per_load,
    }, True


if __name__ == "__main__":
    sys.exit(0 if run_pipeline() else 1)
