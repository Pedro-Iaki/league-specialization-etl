from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_core.config import DATASET_FILES
from app_core.queries import DATASET_QUERIES, REQUIRED_COLUMNS

from src.load.databricks_helper import get_connection

FORBIDDEN_PUBLIC_COLUMNS = {
    "player_id",
    "puuid",
    "rank_delta_id",
    "champion_pair_id",
    "champion_playstyle_id",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export anonymized Streamlit datasets from Databricks gold marts.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=APP_ROOT / "data",
        help="Destination directory for Parquet snapshots and manifest.json.",
    )
    parser.add_argument("--dataset", choices=sorted(DATASET_QUERIES), action="append", help="Export only the named dataset; can be repeated.")
    return parser.parse_args()


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def fetch_frame(cursor: Any, query: str) -> pd.DataFrame:
    cursor.execute(query)
    try:
        return cursor.fetchall_arrow().to_pandas()
    except AttributeError:
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        return pd.DataFrame(rows, columns=columns)


def validate_public_frame(name: str, frame: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS[name].difference(frame.columns)
    forbidden = FORBIDDEN_PUBLIC_COLUMNS.intersection(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing required columns: {sorted(missing)}")
    if forbidden:
        raise ValueError(f"{name} contains forbidden public columns: {sorted(forbidden)}")
    if frame.empty:
        raise ValueError(f"{name} returned no rows")


def dataset_metadata(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "file": path.name,
        "rows": len(frame),
        "columns": len(frame.columns),
        "size_bytes": path.stat().st_size,
    }
    for column in ("as_of_date", "snapshot_date", "previous_snapshot_date"):
        if column in frame and frame[column].notna().any():
            values = pd.to_datetime(frame[column])
            metadata[f"min_{column}"] = json_value(values.min())
            metadata[f"max_{column}"] = json_value(values.max())
    return metadata


def export_snapshots(output_dir: Path, datasets: list[str] | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = get_connection()
    cursor = connection.cursor()
    manifest_path = output_dir / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if datasets and manifest_path.exists() else {}
    manifest: dict[str, Any] = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "league_pipeline.gold",
        "privacy": "Player and interval identifiers excluded from public extracts.",
        "datasets": existing.get("datasets", {}),
    }
    try:
        for name in (datasets or DATASET_QUERIES):
            query = DATASET_QUERIES[name]
            print(f"Exporting {name}...", flush=True)
            frame = fetch_frame(cursor, query)
            validate_public_frame(name, frame)

            destination = output_dir / DATASET_FILES[name]
            temporary = output_dir / f".{destination.name}.tmp"
            frame.to_parquet(temporary, index=False, compression="zstd")
            os.replace(temporary, destination)
            manifest["datasets"][name] = dataset_metadata(destination, frame)
            print(f"  {len(frame):,} rows -> {destination.name}", flush=True)
    finally:
        cursor.close()
        connection.close()

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    args = parse_args()
    manifest = export_snapshots(args.output_dir.resolve(), args.dataset)
    total_bytes = sum(item["size_bytes"] for item in manifest["datasets"].values())
    print(f"Export complete: {total_bytes / 1_048_576:.2f} MiB", flush=True)


if __name__ == "__main__":
    main()
