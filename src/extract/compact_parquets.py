import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
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


@dataclass
class CompactionResult:
    output_path: Path
    compacted_files: list[Path]
    rows_written: int


def discover_leaf_partitions(base_dir: Path) -> list[Path]:
    """Find every directory under base_dir that directly holds parquet files."""
    if not base_dir.exists():
        return []
    partitions = []
    for dirpath, _dirnames, filenames in os.walk(base_dir):
        if any(name.endswith(".parquet") for name in filenames):
            partitions.append(Path(dirpath))
    return list(set(partitions))


def compact_partition(
    compacted_dir: Path, partition_dir: Path, dataset: str
) -> CompactionResult | None:
    """Merge every non-canonical parquet file in partition_dir into the canonical
    compacted file. Returns None if there is nothing new to merge."""
    compacted_file_name = COMPACTED_FILENAMES[dataset]
    compacted_path = compacted_dir / compacted_file_name
    source_files = list(partition_dir.glob("*.parquet"))

    if not source_files:
        return None

    tables = []
    if compacted_path.exists():
        tables.append(pq.read_table(compacted_path))
    for file in source_files:
        tables.append(pq.read_table(file))

    merged = pa.concat_tables(tables, promote_options="default")
    os.makedirs(compacted_dir, exist_ok=True)
    merged = _dedup_merged_table(merged, dataset)
    pq.write_table(merged, compacted_path, compression=COMPRESSION)

    # Verify the write to ensure data integrity.
    check_table = pq.read_table(compacted_path)
    if check_table.num_rows != merged.num_rows:
        compacted_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Compacted file verification failed for {compacted_dir} "
            f"(expected {merged.num_rows} rows, got {check_table.num_rows})."
        )

    return CompactionResult(
        output_path=compacted_path,
        compacted_files=source_files,
        rows_written=merged.num_rows,
    )


def get_compacted_dir_path(partition_dir: Path, dataset: str) -> Path:
    return Path(str(partition_dir).replace(str(RAW_DIR), str(COMPACTED_DIR)))


def compact_dataset(dataset: str) -> dict:
    partitions = discover_leaf_partitions(RAW_DIR / dataset)
    logger.info(f"Discovered {len(partitions)} leaf partitions for dataset {dataset}.")
    summary = {
        "partitions_scanned": len(partitions),
        "partitions_compacted": 0,
        "files_compacted": 0,
        "rows_written": 0,
    }
    compaction_tasks = {}
    for partition_dir in partitions:
        compacted_dir_path = get_compacted_dir_path(partition_dir, dataset)
        compaction_tasks[partition_dir] = db.add_compaction_task(
            dataset, str(compacted_dir_path)
        )

    for partition_dir in partitions:
        compacted_dir_path = get_compacted_dir_path(partition_dir, dataset)
        task_id = compaction_tasks[partition_dir]
        db.update_compaction_task(task_id, "in_progress")
        try:
            result = compact_partition(compacted_dir_path, partition_dir, dataset)
        except RuntimeError as e:
            logger.error(f"Failed to compact partition {compacted_dir_path}: {e}")
            db.update_compaction_task(task_id, "failed", error_message=str(e))
            continue
        if result is None:
            continue

        old_paths = [str(f) for f in result.compacted_files]
        try:
            # go through the compacted files and make sure that any record that points to an old path as their mastery or latest player path, has the correct compacted path parameter
            db.update_compaction_records(
                task_id, dataset, old_paths, str(result.output_path)
            )
            db.update_compaction_task(
                task_id,
                "success",
                paths_compressed=old_paths,
                source_file_count=len(old_paths),
                rows_written=result.rows_written,
            )
        except ConnectionError as e:
            db.update_compaction_task(task_id, "failed", error_message=str(e))
            logger.error(
                f"Failed to update database for partition {compacted_dir_path}, leaving "
                f"source files intact: {e}"
            )
            continue

        # Only delete the originals now that the compacted file is written and the
        # database has been committed to point at it.
        summary["partitions_compacted"] += 1
        summary["files_compacted"] += len(old_paths)
        summary["rows_written"] += result.rows_written

        logger.info(
            f"Compacted {len(old_paths)} file(s) ({result.rows_written} rows) in "
            f"{compacted_dir_path} -> {result.output_path}"
        )

    return summary


def _dedup_merged_table(merged: pa.Table, dataset: str) -> pa.Table:
    """Drop duplicate rows within a merged table, keeping the most recent record per key.

    - players: no per-row timestamp exists, so recency is inferred from file order
      (filenames encode HHMMSS, so sorting by name approximates chronological order).
    - masteries: lastPlayTime is a real per-row timestamp and is used directly.
    """
    if merged.num_rows == 0:
        return merged

    keys = DEDUP_KEYS.get(dataset)
    if not keys or not all(k in merged.column_names for k in keys):
        logger.warning(f"Skipping dedup for {dataset}: dedup keys not found in schema.")
        return merged

    df = merged.to_pandas()

    if dataset == "masteries" and "lastPlayTime" in df.columns:
        df = df.sort_values("lastPlayTime")  # sort by lastPlayTime to ensure recency
    else:
        # The way we add players to the the table ensures later files are more recent, nothing needs to be done here
        pass

    before = len(df)
    df = df.drop_duplicates(subset=keys, keep="last")
    dropped = before - len(df)
    if dropped:
        logger.info(
            f"Dropped {dropped} duplicate row(s) for {dataset} during compaction."
        )

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
