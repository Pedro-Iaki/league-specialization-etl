import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pyarrow.parquet as pq
from loguru import logger
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

import extract.extraction_db_helper as db
from extract.config_helper import get_configs
from load import player_registry
from load.databricks_helper import run_job, upload_parquet
from pydantic_models import ExtractionConfigManifest

BASE_DIR = Path(__file__).resolve().parents[2]
COMPACTED_DIR = BASE_DIR / "data" / "compacted"
COMPACTED_FILENAMES = {
    "players": "players_compacted.parquet",
    "masteries": "masteries_compacted.parquet",
}
ID_COLUMN = "puuid"
MAX_UPLOAD_ATTEMPTS = 3


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(MAX_UPLOAD_ATTEMPTS),
    before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore
    reraise=True,
)
def _upload(dataset: str, compacted_path: Path) -> None:
    time = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    parquet_name = f"{dataset}_{time}_{uuid4().hex}.parquet"
    upload_parquet(str(compacted_path), f"/Volumes/league_pipeline/landing_zone/{dataset}/{parquet_name}")


def load_dataset(dataset: str) -> dict:
    compacted_path = COMPACTED_DIR / COMPACTED_FILENAMES[dataset]
    if not compacted_path.exists():
        logger.info(f"No compacted file found for {dataset}, nothing to load.")
        return {"dataset": dataset, "status": "skipped", "rows": 0, "players": 0}

    table = pq.read_table(compacted_path)
    if table.num_rows == 0:
        return {"dataset": dataset, "status": "skipped", "rows": 0, "players": 0}

    try:
        registry_columns = ["puuid", "region", "queueType"]
        if dataset == "players":
            registry_columns.extend(["wins", "losses"])
        rows = table.select(registry_columns).to_pylist()
        players = list({(row["puuid"], row["region"], row["queueType"]): row for row in rows}.values())
        if dataset == "players":
            observations = db.get_player_observations(players)
            for player in players:
                observation = observations.get((player["puuid"], player["region"], player["queueType"]))
                if observation:
                    player["observed_at"] = observation["finished_at"]
                    player["is_refresh"] = bool(observation["is_refresh"])
    except Exception as e:  # noqa: BLE001 - malformed Parquet must not be treated as loaded
        logger.error(f"Failed to extract players from {dataset}: {e}")
        return {"dataset": dataset, "status": "extract_failed", "rows": table.num_rows, "players": 0}

    try:
        _upload(dataset, compacted_path)
        status = "uploaded"
    except Exception as e:  # noqa: BLE001 - external upload clients raise several error types
        logger.error(f"Failed to load {dataset} after {MAX_UPLOAD_ATTEMPTS} attempts, will retry on next run: {e}")
        status = "load_failed"

    db.update_load_status(dataset, players, "pending_load" if status == "uploaded" else "load_failed")
    logger.info(f"{dataset}: {table.num_rows} row(s), {len(players)} player(s); upload {status}, ingestion not confirmed.")

    return {"dataset": dataset, "status": status, "rows": table.num_rows, "players": len(players), "records": players}


def complete_loaded_rank_pages() -> None:
    """Advance only discovery tasks whose players have confirmed SQLite load flags."""
    for task in db.get_loaded_rank_pages():
        claim = json.loads(task["rank_page_claim"])
        next_page = player_registry.complete_rank_page(claim["claim_token"], claim["player_count"])
        if not next_page:
            logger.debug(f"Page claim for task {task['task_id']} expired or was already completed; keeping ingested data.")
        db.set_rank_page_claim(task["task_id"], None)


def load_compacted(config_manifest: dict) -> bool:
    results = [load_dataset(dataset) for dataset in ("players", "masteries")]
    if not all(result["status"] in ("uploaded", "skipped") for result in results):
        db.mark_load_status(results, "load_failed")
        logger.error("Upload failed; ingestion was not started. Retaining local files.")
        return False
    if all(result["status"] == "skipped" for result in results):
        return True
    if not run_job(config_manifest["ingest_job_id"], config_manifest["ingestion_timeout_seconds"], "Ingestion"):
        db.mark_load_status(results, "load_failed")
        logger.error("Ingestion was not confirmed; retaining local files without applying the loader's Neon updates.")
        return False

    try:
        for result in results:
            if result["dataset"] == "players" and result.get("records"):
                discovered = [player for player in result["records"] if not player.get("is_refresh")]
                refreshed = [player for player in result["records"] if player.get("is_refresh")]
                if discovered:
                    player_registry.upsert_players(discovered)
                if refreshed:
                    player_registry.upsert_players(refreshed, is_refresh=True)
        db.mark_load_status(results, "load_success")
        complete_loaded_rank_pages()
    except Exception as error:  # noqa: BLE001 - registry/ledger failures must prevent local cleanup
        db.mark_load_status(results, "load_failed")
        logger.error(f"Ingestion succeeded but registry/ledger updates failed: {error}. Retaining local files.")
        return False
    logger.info("Ingestion confirmed; Neon freshness and SQLite load status updated.")
    return True


if __name__ == "__main__":
    config_manifest = ExtractionConfigManifest.model_validate(get_configs()).model_dump()
    sys.exit(0 if load_compacted(config_manifest) else 1)
