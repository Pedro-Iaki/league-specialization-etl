import os
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from loguru import logger

import extract.extraction_db_helper as db

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
COMPACTED_DIR = BASE_DIR / "data" / "compacted"
COMPACTED_FILENAMES = {
    "players": "players_compacted.parquet",
    "masteries": "masteries_compacted.parquet",
}
COMPRESSION = "zstd"
DEDUP_KEYS = {
    "players": ["puuid"],
    "masteries": ["puuid", "championId"],
}

PARTITION_SCHEMA = pa.schema(
    [
        ("region", pa.string()),
        ("queueType", pa.string()),
        ("tier", pa.string()),
        ("rank", pa.string()),
        ("patch", pa.string()),
        ("date", pa.string()),
    ]
)
PARTITIONING = ds.HivePartitioning(PARTITION_SCHEMA)


def _read_partitioned_source(file_path: Path, base_dir: Path) -> pa.Table:
    fragment_dataset = ds.dataset(
        file_path,
        format="parquet",
        partitioning=PARTITIONING,
        partition_base_dir=str(base_dir),
    )
    return fragment_dataset.to_table()


def compact_files(compacted_path: Path, source_files: list[Path], dataset: str) -> dict | None:
    existing_files = [f for f in source_files if f.exists()]
    missing_files = [f for f in source_files if f not in existing_files]
    for missing in missing_files:
        logger.warning(f"Skipping compaction source, file not found on disk: {missing}")

    if not existing_files:
        return None

    base_dir = RAW_DIR / dataset

    tables = []
    if compacted_path.exists():
        tables.append(pq.read_table(compacted_path))
    for file in existing_files:
        tables.append(_read_partitioned_source(file, base_dir))

    merged = pa.concat_tables(tables, promote_options="permissive")
    os.makedirs(compacted_path.parent, exist_ok=True)
    merged = _dedup_merged_table(merged, dataset)
    pq.write_table(merged, compacted_path, compression=COMPRESSION)

    check_table = pq.read_table(compacted_path)
    if check_table.num_rows != merged.num_rows:
        compacted_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Compacted file verification failed for {compacted_path} "
            f"(expected {merged.num_rows} rows, got {check_table.num_rows})."
        )

    return {
        "output_path": compacted_path,
        "compacted_files": existing_files,
        "rows_written": merged.num_rows,
    }


def compact_dataset(dataset: str) -> dict:
    rows = db.get_uncompacted_players() if dataset == "players" else db.get_uncompacted_masteries()
    logger.info(f"Found {len(rows)} pending_compaction record(s) for dataset {dataset}.")

    path_to_player_ids: dict[Path, list[str]] = {}
    for row in rows:
        latest_path = row["latest_path"]
        if not latest_path:
            logger.warning(f"Skipping player {row['player_id']}: no logged path for dataset {dataset}.")
            continue
        path_to_player_ids.setdefault(Path(latest_path), []).append(row["player_id"])

    summary = {
        "records_scanned": len(rows),
        "records_compacted": 0,
        "files_merged": 0,
        "rows_written": 0,
    }
    if not path_to_player_ids:
        return summary

    compacted_path = COMPACTED_DIR / COMPACTED_FILENAMES[dataset]
    task_id = db.add_compaction_task(dataset, str(compacted_path))
    db.update_compaction_task(task_id, "in_progress")

    try:
        result = compact_files(compacted_path, list(path_to_player_ids), dataset)
    except RuntimeError as e:
        logger.error(f"Failed to compact dataset {dataset}: {e}")
        db.update_compaction_task(task_id, "failed", error_message=str(e))
        return summary

    if result is None:
        error_message = "No source files existed on disk for the pending_compaction records."
        logger.error(f"Compaction produced nothing for dataset {dataset}: {error_message}")
        db.update_compaction_task(task_id, "failed", error_message=error_message)
        return summary

    player_ids = sorted({pid for f in result["compacted_files"] for pid in path_to_player_ids[f]})

    try:
        db.update_compaction_records(task_id, dataset, player_ids, str(result["output_path"]))
    except ConnectionError as e:
        db.update_compaction_task(task_id, "failed", error_message=str(e))
        logger.error(f"Failed to update database for dataset {dataset}, leaving records pending_compaction: {e}")
        return summary

    db.update_compaction_task(
        task_id,
        "success",
        paths_compressed=[str(f) for f in result["compacted_files"]],
        source_file_count=len(result["compacted_files"]),
        rows_written=result["rows_written"],
    )

    summary["records_compacted"] = len(player_ids)
    summary["files_merged"] = len(result["compacted_files"])
    summary["rows_written"] = result["rows_written"]

    logger.info(
        f"Compacted {len(result['compacted_files'])} file(s) ({result['rows_written']} rows) for "
        f"{len(player_ids)} player(s) -> {result['output_path']}"
    )

    return summary


def _dedup_merged_table(merged: pa.Table, dataset: str) -> pa.Table:
    if merged.num_rows == 0:
        return merged

    keys = DEDUP_KEYS.get(dataset)
    if not keys or not all(k in merged.column_names for k in keys):
        logger.warning(f"Skipping dedup for {dataset}: dedup keys not found in schema.")
        return merged

    df = merged.to_pandas()

    if dataset == "masteries" and "lastPlayTime" in df.columns:
        df = df.sort_values("lastPlayTime")  # sort by lastPlayTime to ensure recency

    before = len(df)
    df = df.drop_duplicates(subset=keys, keep="last")
    dropped = before - len(df)
    if dropped:
        logger.info(f"Dropped {dropped} duplicate row(s) for {dataset} during compaction.")

    return pa.Table.from_pandas(df, preserve_index=False)


def run():
    try:
        players_summary = compact_dataset("players")
        masteries_summary = compact_dataset("masteries")
    except Exception as e:
        logger.exception(f"Compaction run failed: {e}")
        raise
    logger.info(f"Players compaction summary: {players_summary}")
    logger.info(f"Masteries compaction summary: {masteries_summary}")


if __name__ == "__main__":
    run()
