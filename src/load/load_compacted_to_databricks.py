from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from loguru import logger
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

import extract.extraction_db_helper as db
from extract import reset_extraction_state
from load import player_registry
from load.databricks_helper import upload_parquet

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
)
def _upload(dataset: str, compacted_path: Path) -> None:
    time = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    parquet_name = f"{dataset}_{time}.parquet"
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
        players = table.select(["puuid", "region", "queueType"]).to_pylist()
    except RuntimeError as e:
        logger.error(f"Failed to extract players from {dataset}: {e}")
        return {"dataset": dataset, "status": "extract_failed", "rows": table.num_rows, "players": 0}

    try:
        _upload(dataset, compacted_path)
        status = "load_success"
    except ConnectionError as e:
        logger.error(f"Failed to load {dataset} after {MAX_UPLOAD_ATTEMPTS} attempts, will retry on next run: {e}")
        status = "load_failed"

    db.update_load_status(dataset, players, status)
    logger.info(f"{dataset}: {table.num_rows} row(s), {len(players)} player(s) marked {status}.")

    if status == "load_success" and dataset == "players":
        try:
            player_registry.upsert_players(players)
        except ConnectionError as e:
            logger.error("Failed to update Neon player registry")

    return {"dataset": dataset, "status": status, "rows": table.num_rows, "players": len(players)}


def load_compacted() -> bool:
    results = [load_dataset(dataset) for dataset in ("players", "masteries")]
    success = all(r["status"] in ("load_success", "skipped") for r in results)

    if success:
        logger.info("Load succeeded for all datasets, resetting extraction state.")
    else:
        logger.error("Load failed for one or more datasets, leaving extraction state untouched.")

    return success


if __name__ == "__main__":
    load_compacted()
