import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger
from tqdm import tqdm

import extract.extraction_db_helper as db

BASE_DIR = Path(__file__).resolve().parents[2]
PLAYERS_INPUT_PATH = BASE_DIR / "data" / "raw" / "players"
MASTERIES_PATH = BASE_DIR / "data" / "raw" / "masteries"
LOGS_PATH = BASE_DIR / "data" / "logs"


def run_integrity_check(full: bool = False):
    """Check the ledger; full mode also scans raw files and current compaction outputs.

    The runner checks compacted outputs again after compaction in either mode.
    """
    results = {}
    logger.info(f"Checking collected data (raw-file scan: {'on' if full else 'off'}).")
    if full:
        files_log = verify_files_integrity()
        compaction_log = verify_compaction_integrity()
        results["compaction"] = compaction_log
        results["files"] = files_log
    database_log = verify_db_integrity()
    results["database"] = database_log
    logger.info(
        f"Integrity check completed: {database_log.get('total_player_records', 0)} player records, "
        f"{database_log.get('faulty_records_count', 0)} faulty or incomplete. Reports: data/logs."
    )
    return results


def is_compaction_ready(results: dict) -> bool:
    """Check the database and optional raw-file report before compaction."""
    database = results.get("database") or {}

    has_faulty_records_key = "faulty_records_count" in database
    faulty_count = database.get("faulty_records_count", 0)
    if not has_faulty_records_key or faulty_count > 0:
        logger.error(f"Database integrity check failed: faulty record count {database.get('faulty_records_count')}.")
        return False

    files = results.get("files")
    if files:
        total_errors = files.get("total_errors_or_missing", 0)
        if total_errors > 0:
            logger.error(f"Raw file integrity check failed: {total_errors} error(s).")
            return False
    return True


def is_load_ready(results: dict) -> bool:
    """Require valid inputs and a successful compacted-output check before upload."""
    if not is_compaction_ready(results):
        return False
    compaction = results.get("compaction") or {}
    issues = compaction.get("task_level_issues_count")
    pending = compaction.get("pending_compaction_records_count")
    if issues is None or pending is None or issues > 0 or any(pending.values()):
        logger.error(f"Compaction integrity check failed: issues {issues}, uncompacted records {pending}.")
        return False
    return True


def verify_files_integrity() -> dict:
    missing_masteries_puuids = {}
    missing_player_puuids = {}
    duplicated_player_puuids = []
    duplicated_masteries_puuids = {}
    broken_files = []
    all_puuids_players = defaultdict(list)
    all_puuids_masteries = {}

    db.cleanup_stale_runs()

    player_files = set(PLAYERS_INPUT_PATH.rglob("*.parquet"))
    for player_file in tqdm(player_files, desc="Verifying player files", unit="file"):
        try:
            table = pq.read_table(player_file)
            if table.num_rows == 0 or "puuid" not in table.column_names:
                broken_files.append(player_file)
                continue
            for puuid in table.column("puuid").to_pylist():
                if not puuid:
                    continue
                all_puuids_players[puuid].append(player_file)

        except (OSError, RuntimeError, pa.ArrowException) as e:
            logger.error(f"Failed to read player file {player_file}: {e}")
            broken_files.append(player_file)
            continue

    mastery_files = set(MASTERIES_PATH.rglob("*.parquet"))
    for mastery_file in tqdm(mastery_files, desc="Verifying mastery files", unit="file"):
        try:
            table = pq.read_table(mastery_file)
            if table.num_rows == 0 or "puuid" not in table.column_names:
                broken_files.append(mastery_file)
                continue
            for puuid in table.column("puuid").to_pylist():
                if not puuid:
                    continue
                all_puuids_masteries[puuid] = mastery_file

        except (OSError, RuntimeError, pa.ArrowException) as e:
            logger.error(f"Failed to read mastery file {mastery_file}: {e}")
            broken_files.append(mastery_file)
            continue

    for puuid, mastery_file in tqdm(all_puuids_masteries.items(), desc="Verifying mastery records", unit="record"):
        if puuid not in all_puuids_players:
            missing_player_puuids[puuid] = str(mastery_file)

        uniques = sum(1 for player, file in all_puuids_masteries.items() if player == puuid)
        if uniques > 1 and puuid not in duplicated_masteries_puuids:
            duplicated_masteries_puuids[puuid] = [
                str(file) for player, file in all_puuids_masteries.items() if player == puuid
            ]

    for puuid, paths in tqdm(all_puuids_players.items(), desc="Verifying player records", unit="record"):
        if puuid not in all_puuids_masteries:
            missing_masteries_puuids[puuid] = ", ".join(str(p) for p in paths)

        if len(paths) > 1:
            duplicated_player_puuids.append(puuid)

    total_evaluated = len(all_puuids_players) + len(all_puuids_masteries)
    total_errors = len(missing_masteries_puuids) + len(missing_player_puuids) + len(broken_files)
    error_rate = f"{(total_errors / total_evaluated if total_evaluated > 0 else 1) * 100:.2f}%"
    duplicated_mastery_rate = (
        f"{(len(duplicated_masteries_puuids) / len(all_puuids_masteries) if all_puuids_masteries else 0) * 100:.2f}%"
    )
    duplicated_player_rate = (
        f"{(len(duplicated_player_puuids) / len(all_puuids_players) if all_puuids_players else 0) * 100:.2f}%"
    )
    average_duplicity_per_player_file = (
        sum(len(v) for v in all_puuids_players.values()) / len(all_puuids_players) if len(all_puuids_players) else 0
    )  # Mean raw-file appearances per distinct player.

    conn = db.get_connection()
    db_players = [row["player_id"] for row in conn.execute("SELECT player_id FROM players_recorded")]
    conn.close()
    unregistered_players = [puuid for puuid in all_puuids_players if puuid not in db_players]
    wrongfully_registered_players = [puuid for puuid in db_players if puuid not in all_puuids_players]

    log_data = {
        "total_evaluated": total_evaluated,
        "total_player_files": len(all_puuids_players),
        "total_mastery_files": len(all_puuids_masteries),
        "total_errors_or_missing": total_errors,
        "error_rate": error_rate,
        "average_duplicity_per_player_file": f"{average_duplicity_per_player_file:.3f}",
        "duplicated_player_rate": duplicated_player_rate,
        "duplicated_players": duplicated_player_puuids,
        "duplicated_mastery_rate": duplicated_mastery_rate,
        "duplicated_masteries": duplicated_masteries_puuids,
        "players_missing_masteries_count": len(missing_masteries_puuids),
        "players_missing_masteries": [
            {"puuid": puuid, "source_file": source_file} for puuid, source_file in missing_masteries_puuids.items()
        ],
        "masteries_missing_players_count": len(missing_player_puuids),
        "masteries_missing_players": [
            {"puuid": puuid, "source_file": source_file} for puuid, source_file in missing_player_puuids.items()
        ],
        "unregistered_players_count": len(unregistered_players),
        "unregistered_players": unregistered_players,
        "wrongfully_registered_players_count": len(wrongfully_registered_players),
        "wrongfully_registered_players": wrongfully_registered_players,
        "faulty_files": [{"source_file": str(broken_file)} for broken_file in broken_files],
    }

    log_file = LOGS_PATH / "integrity_check.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")

    return log_data


def verify_db_integrity(conn: sqlite3.Connection | None = None) -> dict[any]:  # type: ignore #
    own_conn = conn is not None
    if not own_conn:
        conn = db.get_connection()

    player_tasks = conn.execute("SELECT * FROM player_tasks").fetchall()
    player_tasks = {row["task_id"]: dict(row) for row in player_tasks}

    mastery_tasks = conn.execute("SELECT * FROM mastery_tasks").fetchall()
    mastery_tasks = {row["task_id"]: dict(row) for row in mastery_tasks}

    player_records = conn.execute("SELECT * FROM players_recorded").fetchall()
    player_records = {row["player_id"]: dict(row) for row in player_records}

    if not own_conn:
        conn.close()

    player_task_errors = [t for t in player_tasks.values() if t["status"] == "failed"]
    mastery_task_errors = [t for t in mastery_tasks.values() if t["status"] == "failed"]
    player_task_error_rate = f"{(len(player_task_errors) / len(player_tasks) if player_tasks else 0) * 100:.2f}%"
    mastery_task_error_rate = f"{(len(mastery_task_errors) / len(mastery_tasks) if mastery_tasks else 0) * 100:.2f}%"
    no_path_tasks = len([t for t in player_tasks.values() if not t["file_path"] or t["file_path"].strip() == ""])

    player_error_messages = {}
    for task in player_task_errors:
        msg = task.get("error_message", "none")
        player_error_messages[msg] = player_error_messages.get(msg, 0) + 1

    mastery_error_messages = {}
    for task in mastery_task_errors:
        msg = task.get("error_message", "none")
        mastery_error_messages[msg] = mastery_error_messages.get(msg, 0) + 1

    faulty_records = []
    paths_counts = []

    for record in tqdm(player_records.values(), desc="Verifying database records", unit="record"):
        issues = []

        mastery_status = record.get("mastery_status")

        if mastery_status != "success":
            issues.append(f"mastery_status: {mastery_status}")

        paths = record.get("paths")
        if not paths:
            issues.append("no_paths")
        else:
            try:
                paths_list = json.loads(paths) if isinstance(paths, str) else paths
                if not paths_list or len(paths_list) == 0:
                    issues.append("empty_paths")
                else:
                    paths_counts.append(len(paths_list))
            except RuntimeError:
                issues.append("invalid_paths")

        player_task_ids = record.get("player_task_ids")
        if not player_task_ids:
            issues.append("no_player_task_ids")
        else:
            try:
                task_ids = json.loads(player_task_ids) if isinstance(player_task_ids, str) else player_task_ids
                if not task_ids:
                    issues.append("empty_player_task_ids")
                else:
                    for task_id in task_ids:
                        if task_id in player_tasks and player_tasks[task_id]["status"] != "success":
                            issues.append(f"player_task_{task_id}_not_success")
            except RuntimeError:
                issues.append("invalid_player_task_ids")

        mastery_task_id = record.get("mastery_task_id")
        if not mastery_task_id:
            issues.append("no_mastery_task_id")
        else:
            if mastery_status == "success" and not mastery_task_id:
                issues.append("success_but_no_mastery_task_id")
            elif mastery_task_id and (
                mastery_task_id in mastery_tasks and mastery_tasks[mastery_task_id]["status"] != "success"
            ):
                issues.append(f"mastery_task_{mastery_task_id}_not_success")

        if not record.get("region") or not record.get("queue") or not record.get("tier") or not record.get("division"):
            issues.append("missing_rank_info")

        if issues:
            faulty_records.append({"player_id": record["player_id"], "issues": issues})

    log_data = {
        "total_player_tasks": len(player_tasks),
        "total_mastery_tasks": len(mastery_tasks),
        "total_player_records": len(player_records),
        "discarded_player_tasks": no_path_tasks,
        "player_task_error_rate": player_task_error_rate,
        "mastery_task_error_rate": mastery_task_error_rate,
        "player_task_errors_by_message": player_error_messages,
        "mastery_task_errors_by_message": mastery_error_messages,
        "faulty_records_count": len(faulty_records),
        "faulty_records": faulty_records,
        "duplicated_players": f"{(sum(paths_counts) / len(paths_counts) if paths_counts else 0) * 100 - 100:.2f}%",
        "duplicated_players_total": len([p for p in paths_counts if p > 1]),
    }

    log_file = LOGS_PATH / "db_integrity_check.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")

    return log_data


def _read_puuid_set(path: Path) -> set[str]:
    table = pq.read_table(path, columns=["puuid"])
    return {p for p in table.column("puuid").to_pylist() if p}


def verify_compaction_integrity() -> dict:
    """Check outputs still awaiting ingestion; retain raw-file diagnostics separately."""
    conn = db.get_connection()
    try:
        records = conn.execute(
            """
            SELECT player_id, 'players' AS dataset, player_load_status AS status,
                latest_player_compacted_task_id AS task_id, latest_player_compacted_path AS output_path
            FROM players_recorded WHERE player_load_status != 'load_success'
            UNION ALL
            SELECT player_id, 'masteries', mastery_load_status,
                mastery_compacted_task_id, mastery_compacted_path
            FROM players_recorded WHERE mastery_load_status != 'load_success'
            """
        ).fetchall()
        tasks = conn.execute(
            """
            SELECT task_id, dataset, output_path, paths_compressed, rows_written, status
            FROM compaction_tasks
            WHERE task_id IN (
                SELECT latest_player_compacted_task_id FROM players_recorded
                WHERE player_load_status IN ('pending_load', 'load_failed')
                UNION
                SELECT mastery_compacted_task_id FROM players_recorded
                WHERE mastery_load_status IN ('pending_load', 'load_failed')
            ) ORDER BY task_id
            """
        ).fetchall()
    finally:
        conn.close()

    task_level_issues = []
    accounted_raw_paths: set[str] = set()
    pending = {"players": 0, "masteries": 0}
    tasks_by_id = {task["task_id"]: task for task in tasks}
    latest_tasks = {task["output_path"]: task["task_id"] for task in tasks}
    output_tables = {}

    for record in records:
        if record["status"] == "pending_compaction":
            pending[record["dataset"]] += 1
            continue
        task = tasks_by_id.get(record["task_id"])
        if not task or task["dataset"] != record["dataset"] or task["output_path"] != record["output_path"]:
            task_level_issues.append(
                {
                    "player_id": record["player_id"],
                    "dataset": record["dataset"],
                    "issue": "compaction_reference_missing_or_invalid",
                }
            )

    for task in tqdm(tasks, desc="Verifying compaction tasks", unit="task"):
        dataset = task["dataset"]
        output_path = Path(task["output_path"])
        if task["status"] != "success":
            task_level_issues.append({"task_id": task["task_id"], "issue": "compaction_task_not_success"})
            continue
        paths_compressed = json.loads(task["paths_compressed"] or "[]")
        accounted_raw_paths.update(paths_compressed)

        if not output_path.exists():
            task_level_issues.append(
                {
                    "task_id": task["task_id"],
                    "issue": "compacted_output_missing",
                    "output_path": str(output_path),
                }
            )
            continue

        try:
            if output_path not in output_tables:
                output_tables[output_path] = pq.read_table(output_path)
            table = output_tables[output_path]
            required = ["puuid", "region", "queueType"] + (
                ["wins", "losses"] if dataset == "players" else ["championId"]
            )
            missing_columns = sorted(set(required) - set(table.column_names))
            if missing_columns:
                raise ValueError(f"Missing load columns: {missing_columns}")
            compacted_puuids = {p for p in table.column("puuid").to_pylist() if p}
        except (OSError, RuntimeError, ValueError, pa.ArrowException) as e:
            task_level_issues.append(
                {
                    "task_id": task["task_id"],
                    "issue": "compacted_file_unreadable",
                    "output_path": str(output_path),
                    "error": str(e),
                }
            )
            continue

        if task["task_id"] == latest_tasks[task["output_path"]] and table.num_rows != task["rows_written"]:
            task_level_issues.append(
                {
                    "task_id": task["task_id"],
                    "issue": "compacted_row_count_mismatch",
                    "expected_rows": task["rows_written"],
                    "actual_rows": table.num_rows,
                }
            )

        source_puuids = {record["player_id"] for record in records if record["task_id"] == task["task_id"]}
        for raw_path_str in paths_compressed:
            raw_path = Path(raw_path_str)
            if not raw_path.exists():
                # The compacted output remains checkable after source cleanup.
                continue
            try:
                source_puuids |= _read_puuid_set(raw_path)
            except (OSError, RuntimeError, ValueError, pa.ArrowException) as e:
                task_level_issues.append(
                    {
                        "task_id": task["task_id"],
                        "issue": "source_file_unreadable",
                        "source_path": raw_path_str,
                        "error": str(e),
                    }
                )

        lost = source_puuids - compacted_puuids
        if lost:
            task_level_issues.append(
                {
                    "task_id": task["task_id"],
                    "issue": "puuids_lost_in_compaction",
                    "output_path": str(output_path),
                    "lost_puuids": sorted(lost),
                    "lost_count": len(lost),
                }
            )

    # Raw files not referenced by the compaction tasks awaiting ingestion.
    unaccounted_files = {"players": [], "masteries": []}
    for dataset, raw_root in (
        ("players", PLAYERS_INPUT_PATH),
        ("masteries", MASTERIES_PATH),
    ):
        for raw_file in raw_root.rglob("*.parquet"):
            if str(raw_file) not in accounted_raw_paths:
                unaccounted_files[dataset].append(str(raw_file))

    log_data = {
        "tasks_checked": len(tasks),
        "task_level_issues": task_level_issues,
        "task_level_issues_count": len(task_level_issues),
        "pending_compaction_records_count": pending,
        "unaccounted_raw_files": unaccounted_files,
        "unaccounted_raw_files_count": {k: len(v) for k, v in unaccounted_files.items()},
    }

    log_file = LOGS_PATH / "compaction_integrity_check.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(json.dumps(log_data, indent=2), encoding="utf-8")
    logger.info(
        f"Compaction check completed: {len(task_level_issues)} issues, "
        f"{sum(pending.values())} player records awaiting compaction."
    )
    logger.debug(f"Compaction check pending records by dataset: {pending}")
    return log_data


if __name__ == "__main__":
    run_integrity_check(True)
