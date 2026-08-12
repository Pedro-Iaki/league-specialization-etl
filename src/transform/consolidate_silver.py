from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger
from pydantic import ValidationError

from pathlib import Path

from src.pydantic_models import ChampionMasteryEntry, RiotPlayerEntry


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "data" / "database" / "extraction.db"
DEFAULT_BRONZE_PLAYERS_DIR = ROOT / "data" / "raw" / "players"
DEFAULT_BRONZE_MASTERIES_DIR = ROOT / "data" / "raw" / "masteries"
DEFAULT_SILVER_BASE = ROOT / "data" / "cleaned"
DEFAULT_QUARANTINE_DIR = ROOT / "data" / "quarantine"
DEFAULT_ASSURANCE_DIR = DEFAULT_SILVER_BASE / "assurance"
DEFAULT_QUEUE = "RANKED_SOLO_5x5"
DEFAULT_REGION = "na1"
DEFAULT_PATCH = "16.14.1"


def normalize_path(raw_path: str | Path | None, root: Path | None = None) -> Path | None:
    if raw_path in (None, ""):
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute() and root is not None:
        candidate = root / candidate
    return candidate.resolve(strict=False)


def ensure_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


def get_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def read_json_file(path: Path) -> Any | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Unable to read JSON file {path}: {exc}")
        return None


def iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_newer(candidate_ts: str | None, current_ts: str | None) -> bool:
    if candidate_ts is None:
        return False
    if current_ts is None:
        return True
    left = iso_to_datetime(candidate_ts)
    right = iso_to_datetime(current_ts)
    if left is None or right is None:
        return str(candidate_ts) > str(current_ts)
    return left > right


def append_quarantine_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    ensure_directory(path.parent)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    else:
        combined = pd.DataFrame(rows)
    combined.to_parquet(path, index=False, compression="snappy")


def write_partitioned_dataset(frame: pd.DataFrame, output_dir: Path, partition_cols: list[str]) -> None:
    if frame.empty:
        logger.info(f"No records to write for {output_dir}")
        return
    ensure_directory(output_dir)
    frame.to_parquet(output_dir, partition_cols=partition_cols, index=False, compression="snappy")


def collect_latest_player_records(player_snapshot_records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest_by_player: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []

    if isinstance(player_snapshot_records, dict):
        candidates = [{"payload": snapshot, "path": key} for key, snapshot in player_snapshot_records.items()]
    else:
        candidates = list(player_snapshot_records)

    for record in candidates:
        if not isinstance(record, dict):
            continue
        payload = record.get("payload", record)
        if not isinstance(payload, dict):
            continue
        raw_players = payload.get("players", [])
        if not isinstance(raw_players, list):
            continue
        for raw_player in raw_players:
            if not isinstance(raw_player, dict):
                continue
            try:
                validated = RiotPlayerEntry.model_validate(raw_player)
            except ValidationError as exc:
                logger.warning(f"Player validation failed for {raw_player.get('puuid')}: {exc}")
                continue
            puuid = validated.puuid
            row = {
                "player_id": puuid,
                "region": payload.get("region"),
                "queue": payload.get("queue"),
                "patch": payload.get("patch"),
                "tier": payload.get("tier"),
                "division": payload.get("division"),
                "fetched_at": payload.get("fetched_at"),
                "source_path": record.get("path"),
                **validated.model_dump(),
            }
            existing = latest_by_player.get(puuid)
            if existing is None or is_newer(row["fetched_at"], existing["fetched_at"]):
                latest_by_player[puuid] = row
    return latest_by_player


def mark_quarantined_players_for_invalid_records(
    snapshot_path: Path,
    payload: dict[str, Any],
    candidate_lookup: dict[str, dict[str, Any]],
    clean_players: dict[str, dict[str, Any]],
    quarantine_players: list[dict[str, Any]],
) -> None:
    snapshot_players = payload.get("players", [])
    if not isinstance(snapshot_players, list):
        return
    for raw_player in snapshot_players:
        if not isinstance(raw_player, dict):
            quarantine_players.append(
                {
                    "player_id": None,
                    "region": payload.get("region"),
                    "queue": payload.get("queue"),
                    "patch": payload.get("patch"),
                    "reason": "invalid_player_payload",
                    "source_path": str(snapshot_path),
                    "detail": "Player object is not a JSON object.",
                    "fetched_at": payload.get("fetched_at"),
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue
        puuid = raw_player.get("puuid")
        try:
            validated = RiotPlayerEntry.model_validate(raw_player)
        except ValidationError as exc:
            quarantine_players.append(
                {
                    "player_id": puuid,
                    "region": payload.get("region"),
                    "queue": payload.get("queue"),
                    "patch": payload.get("patch"),
                    "reason": "validation_error",
                    "source_path": str(snapshot_path),
                    "detail": str(exc),
                    "fetched_at": payload.get("fetched_at"),
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue
        puuid = validated.puuid
        if puuid not in candidate_lookup:
            quarantine_players.append(
                {
                    "player_id": puuid,
                    "region": payload.get("region"),
                    "queue": payload.get("queue"),
                    "patch": payload.get("patch"),
                    "reason": "unregistered_player_in_snapshot",
                    "source_path": str(snapshot_path),
                    "detail": "Player exists in raw snapshot but is not registered in players_recorded.",
                    "fetched_at": payload.get("fetched_at"),
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue
        candidate_lookup[puuid]["found"] = True
        row = {
            "player_id": puuid,
            "region": payload.get("region"),
            "queue": payload.get("queue"),
            "patch": payload.get("patch"),
            "tier": payload.get("tier"),
            "division": payload.get("division"),
            "fetched_at": payload.get("fetched_at"),
            "source_path": str(snapshot_path),
            **validated.model_dump(),
        }
        existing = clean_players.get(puuid)
        if existing is None or is_newer(row["fetched_at"], existing.get("fetched_at")):
            clean_players[puuid] = row


def process_partition(target_patch: str, target_region: str, target_queue: str, db_path: Path, silver_base: Path, quarantine_dir: Path) -> dict[str, Any]:
    ensure_directory(silver_base)
    ensure_directory(quarantine_dir)

    candidate_rows: list[dict[str, Any]] = []
    candidate_lookup: dict[str, dict[str, Any]] = {}
    processed_player_paths: set[str] = set()
    processed_mastery_paths: set[str] = set()

    logger.info(f"Scanning extraction database {db_path} for patch={target_patch}, region={target_region}, queue={target_queue}")
    with get_connection(db_path) as conn:
        statement = """
            SELECT player_id, paths, mastery_path, region, queue, tier, division, mastery_patch
            FROM players_recorded
            WHERE mastery_status = 'success'
              AND mastery_patch = ?
              AND region = ?
              AND queue = ?
        """
        rows = conn.execute(statement, (target_patch, target_region, target_queue)).fetchall()
        for row in rows:
            raw_paths = json.loads(row["paths"] or "[]") if row["paths"] else []
            if not isinstance(raw_paths, list):
                raw_paths = [raw_paths]
            candidate = {
                "player_id": row["player_id"],
                "paths": [str(normalize_path(path, ROOT) or path) for path in raw_paths],
                "mastery_path": str(normalize_path(row["mastery_path"], ROOT)) if row["mastery_path"] else None,
                "region": row["region"],
                "queue": row["queue"],
                "tier": row["tier"],
                "division": row["division"],
                "patch": target_patch,
                "found": False,
            }
            candidate_rows.append(candidate)
            candidate_lookup[candidate["player_id"]] = candidate
            processed_player_paths.update(candidate["paths"])
            if candidate["mastery_path"]:
                processed_mastery_paths.add(candidate["mastery_path"])

    clean_players: dict[str, dict[str, Any]] = {}
    quarantine_players: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        for raw_path in candidate["paths"]:
            snapshot_file = Path(raw_path)
            if not snapshot_file.exists():
                quarantine_players.append(
                    {
                        "player_id": candidate["player_id"],
                        "region": candidate["region"],
                        "queue": candidate["queue"],
                        "patch": candidate["patch"],
                        "reason": "file_missing",
                        "source_path": str(snapshot_file),
                        "detail": "Snapshot path referenced in database is missing from disk.",
                        "fetched_at": None,
                        "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    }
                )
                continue
            payload = read_json_file(snapshot_file)
            if not isinstance(payload, dict):
                quarantine_players.append(
                    {
                        "player_id": candidate["player_id"],
                        "region": candidate["region"],
                        "queue": candidate["queue"],
                        "patch": candidate["patch"],
                        "reason": "malformed_json",
                        "source_path": str(snapshot_file),
                        "detail": "Player snapshot JSON could not be parsed.",
                        "fetched_at": None,
                        "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    }
                )
                continue
            mark_quarantined_players_for_invalid_records(snapshot_file, payload, candidate_lookup, clean_players, quarantine_players)

    for candidate in candidate_rows:
        if not candidate["found"]:
            quarantine_players.append(
                {
                    "player_id": candidate["player_id"],
                    "region": candidate["region"],
                    "queue": candidate["queue"],
                    "patch": candidate["patch"],
                    "reason": "candidate_not_found_in_snapshot",
                    "source_path": None,
                    "detail": "No valid snapshot entry was found for this registered player.",
                    "fetched_at": None,
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )

    clean_masteries: dict[str, dict[str, Any]] = {}
    quarantine_masteries: list[dict[str, Any]] = []
    for candidate in candidate_rows:
        mastery_path = candidate.get("mastery_path")
        if not mastery_path:
            continue
        mastery_file = Path(mastery_path)
        if not mastery_file.exists():
            quarantine_masteries.append(
                {
                    "player_id": candidate["player_id"],
                    "region": candidate["region"],
                    "queue": candidate["queue"],
                    "patch": candidate["patch"],
                    "reason": "file_missing",
                    "source_path": str(mastery_file),
                    "detail": "Mastery file referenced in players_recorded does not exist on disk.",
                    "fetched_at": None,
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue
        payload = read_json_file(mastery_file)
        if not isinstance(payload, dict):
            quarantine_masteries.append(
                {
                    "player_id": candidate["player_id"],
                    "region": candidate["region"],
                    "queue": candidate["queue"],
                    "patch": candidate["patch"],
                    "reason": "malformed_json",
                    "source_path": str(mastery_file),
                    "detail": "Mastery file JSON could not be parsed.",
                    "fetched_at": None,
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue

        mastery_items = payload.get("masteries", [])
        if not isinstance(mastery_items, list):
            quarantine_masteries.append(
                {
                    "player_id": candidate["player_id"],
                    "region": candidate["region"],
                    "queue": candidate["queue"],
                    "patch": candidate["patch"],
                    "reason": "invalid_mastery_payload",
                    "source_path": str(mastery_file),
                    "detail": "Mastery payload must contain a list under 'masteries'.",
                    "fetched_at": payload.get("fetched_at"),
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue

        validated_records: list[dict[str, Any]] = []
        for entry in mastery_items:
            if not isinstance(entry, dict):
                quarantine_masteries.append(
                    {
                        "player_id": candidate["player_id"],
                        "region": candidate["region"],
                        "queue": candidate["queue"],
                        "patch": candidate["patch"],
                        "reason": "validation_error",
                        "source_path": str(mastery_file),
                        "detail": "One mastery entry is not a JSON object.",
                        "fetched_at": payload.get("fetched_at"),
                        "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    }
                )
                continue
            try:
                validated = ChampionMasteryEntry.model_validate(entry)
            except ValidationError as exc:
                quarantine_masteries.append(
                    {
                        "player_id": candidate["player_id"],
                        "region": candidate["region"],
                        "queue": candidate["queue"],
                        "patch": candidate["patch"],
                        "reason": "validation_error",
                        "source_path": str(mastery_file),
                        "detail": str(exc),
                        "fetched_at": payload.get("fetched_at"),
                        "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    }
                )
                continue
            if payload.get("puuid") and validated.puuid != payload["puuid"]:
                quarantine_masteries.append(
                    {
                        "player_id": candidate["player_id"],
                        "region": candidate["region"],
                        "queue": candidate["queue"],
                        "patch": candidate["patch"],
                        "reason": "puuid_mismatch",
                        "source_path": str(mastery_file),
                        "detail": f"Mastery entry puuid {validated.puuid} mismatches payload puuid {payload.get('puuid')}",
                        "fetched_at": payload.get("fetched_at"),
                        "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    }
                )
                continue
            validated_records.append({**validated.model_dump(), "source_path": str(mastery_file)})

        if not validated_records:
            quarantine_masteries.append(
                {
                    "player_id": candidate["player_id"],
                    "region": candidate["region"],
                    "queue": candidate["queue"],
                    "patch": candidate["patch"],
                    "reason": "no_valid_mastery_entries",
                    "source_path": str(mastery_file),
                    "detail": "No valid mastery entries remained after validation.",
                    "fetched_at": payload.get("fetched_at"),
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue

        file_puuid = payload.get("puuid") or candidate["player_id"]
        if file_puuid not in clean_players:
            quarantine_masteries.append(
                {
                    "player_id": file_puuid,
                    "region": candidate["region"],
                    "queue": candidate["queue"],
                    "patch": candidate["patch"],
                    "reason": "puuid_not_in_clean_players",
                    "source_path": str(mastery_file),
                    "detail": "Mastery file puuid is not in the clean player set for this partition.",
                    "fetched_at": payload.get("fetched_at"),
                    "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }
            )
            continue

        cleaned_record = {
            "player_id": file_puuid,
            "region": candidate["region"],
            "queue": candidate["queue"],
            "patch": candidate["patch"],
            "tier": candidate["tier"],
            "division": candidate["division"],
            "fetched_at": payload.get("fetched_at"),
            "source_path": str(mastery_file),
            "mastery_entries": validated_records,
        }

        current = clean_masteries.get(file_puuid)
        if current is None or is_newer(cleaned_record["fetched_at"], current.get("fetched_at")):
            if current is not None:
                quarantine_masteries.append(
                    {
                        "player_id": file_puuid,
                        "region": candidate["region"],
                        "queue": candidate["queue"],
                        "patch": candidate["patch"],
                        "reason": "duplicate_mastery_puuid_latest_wins",
                        "source_path": str(mastery_file),
                        "detail": f"Superseded older mastery record for {file_puuid}.",
                        "fetched_at": cleaned_record["fetched_at"],
                        "quarantined_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    }
                )
            clean_masteries[file_puuid] = cleaned_record

    player_output = pd.DataFrame(list(clean_players.values()))
    if not player_output.empty:
        player_output = player_output[[
            "player_id", "region", "queue", "patch", "tier", "division",
            "queueType", "rank", "leaguePoints", "wins", "losses",
            "veteran", "inactive", "freshBlood", "hotStreak",
            "fetched_at", "source_path"
        ]]
    else:
        player_output = pd.DataFrame(columns=[
            "player_id", "region", "queue", "patch", "tier", "division",
            "queueType", "rank", "leaguePoints", "wins", "losses",
            "veteran", "inactive", "freshBlood", "hotStreak",
            "fetched_at", "source_path"
        ])

    mastery_rows: list[dict[str, Any]] = []
    for item in clean_masteries.values():
        for mastery in item["mastery_entries"]:
            row = {
                "player_id": item["player_id"],
                "region": item["region"],
                "queue": item["queue"],
                "patch": item["patch"],
                "tier": item["tier"],
                "division": item["division"],
                "fetched_at": item["fetched_at"],
                "source_path": item["source_path"],
                **{key: value for key, value in mastery.items() if key != "source_path"},
            }
            mastery_rows.append(row)

    mastery_output = pd.DataFrame(mastery_rows)
    if not mastery_output.empty:
        mastery_output = mastery_output[[
            "player_id", "region", "queue", "patch", "tier", "division",
            "championId", "championLevel", "championPoints", "lastPlayTime",
            "championPointsSinceLastLevel", "championPointsUntilNextLevel",
            "milestoneGrades", "fetched_at", "source_path"
        ]]
    else:
        mastery_output = pd.DataFrame(columns=[
            "player_id", "region", "queue", "patch", "tier", "division",
            "championId", "championLevel", "championPoints", "lastPlayTime",
            "championPointsSinceLastLevel", "championPointsUntilNextLevel",
            "milestoneGrades", "fetched_at", "source_path"
        ])

    players_output_dir = silver_base / "players"
    masteries_output_dir = silver_base / "masteries"
    write_partitioned_dataset(player_output, players_output_dir, ["region", "queue", "patch"])
    write_partitioned_dataset(mastery_output, masteries_output_dir, ["region", "queue", "patch"])

    players_invalid_path = quarantine_dir / "players_invalid.parquet"
    masteries_invalid_path = quarantine_dir / "masteries_invalid.parquet"
    append_quarantine_rows(players_invalid_path, quarantine_players)
    append_quarantine_rows(masteries_invalid_path, quarantine_masteries)

    assurance_dir = silver_base / "assurance"
    ensure_directory(assurance_dir)
    assurance_records: list[dict[str, Any]] = []
    candidate_paths = set(processed_player_paths)
    candidate_paths.update(processed_mastery_paths)

    player_partition_root = DEFAULT_BRONZE_PLAYERS_DIR / f"region={target_region}" / f"queue={target_queue}"
    if player_partition_root.exists():
        for file_path in sorted(player_partition_root.rglob("*.json")):
            if str(file_path) not in candidate_paths:
                assurance_records.append(
                    {
                        "dataset": "players",
                        "region": target_region,
                        "queue": target_queue,
                        "patch": target_patch,
                        "path": str(file_path),
                        "reason": "not_registered_in_extraction_db",
                    }
                )

    mastery_partition_root = DEFAULT_BRONZE_MASTERIES_DIR / f"region={target_region}" / f"queue={target_queue}"
    if mastery_partition_root.exists():
        for file_path in sorted(mastery_partition_root.rglob("*.json")):
            if str(file_path) not in candidate_paths:
                assurance_records.append(
                    {
                        "dataset": "masteries",
                        "region": target_region,
                        "queue": target_queue,
                        "patch": target_patch,
                        "path": str(file_path),
                        "reason": "not_registered_in_extraction_db",
                    }
                )

    if assurance_records:
        pd.DataFrame(assurance_records).to_parquet(assurance_dir / "unregistered_raw_files.parquet", index=False, compression="snappy")

    summary = {
        "players_processed": len(candidate_rows),
        "clean_players_written": int(len(player_output)),
        "quarantined_players": len(quarantine_players),
        "clean_masteries_written": int(len(mastery_output)),
        "quarantined_masteries": len(quarantine_masteries),
    }
    logger.info(f"Silver consolidator summary: {summary}")
    return summary


def main() -> None:
    logger.remove()
    logger.add("data/logs/transform.log", rotation="20 MB")
    logger.info("Starting silver data consolidation pipeline")
    process_partition(
        target_patch=DEFAULT_PATCH,
        target_region=DEFAULT_REGION,
        target_queue=DEFAULT_QUEUE,
        db_path=DEFAULT_DB_PATH,
        silver_base=DEFAULT_SILVER_BASE,
        quarantine_dir=DEFAULT_QUARANTINE_DIR,
    )


if __name__ == "__main__":
    main()
