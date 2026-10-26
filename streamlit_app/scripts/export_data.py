from __future__ import annotations

import argparse
import hashlib
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

from app_core.business import BUSINESS_PUBLIC_COLUMNS
from app_core.config import DATASET_FILES
from app_core.contracts import ACTIVE_POOL_LIFETIME_COLUMNS, REQUIRED_COLUMNS
from app_core.family_affinity import affinity_metadata, load_family_definition
from app_core.family_exports import (
    FAMILY_BUSINESS_QUERY,
    FAMILY_PROFILE_QUERY,
    PROFILE_AUDIENCE_COLUMNS,
    attach_business_audience,
    prepare_private_profiles,
    validate_family_frame,
)
from app_core.population import load_reference, population_weights, reference_fingerprint
from app_core.queries import DATASET_QUERIES

from src.load.databricks_helper import get_connection
from src.sample.validation import warehouse_metadata

FORBIDDEN_PUBLIC_COLUMNS = {
    "player_id",
    "transaction_id",
    "product_id",
    "scenario_metadata",
    "puuid",
    "rank_delta_id",
    "champion_pair_id",
    "champion_playstyle_id",
}


def main() -> None:
    args = parse_args()
    manifest = export_snapshots(args.output_dir.resolve(), args.dataset, family_audience=args.family_audience,
                                pool_archetypes=args.pool_archetypes)
    total_bytes = sum(item["size_bytes"] for item in manifest["datasets"].values())
    print(f"Export complete: {total_bytes / 1_048_576:.2f} MiB", flush=True)


def export_snapshots(output_dir: Path, datasets: list[str] | None = None, *, family_audience: bool = False,
                     pool_archetypes: bool = False) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    from app_core.archetype_serving import COLUMNS, MODEL_PATH, load_model, model_metadata
    archetype_model = load_model() if pool_archetypes else None
    family_audience = family_audience or pool_archetypes
    definition = load_family_definition() if family_audience else None
    reference = load_reference() if family_audience else None
    connection = get_connection()
    cursor = connection.cursor()
    manifest_path = output_dir / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if datasets and manifest_path.exists() else {}
    manifest: dict[str, Any] = {
        **existing,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "league_pipeline.gold",
        "privacy": "Player and interval identifiers excluded from public extracts.",
        "datasets": existing.get("datasets", {}),
    }
    private_profiles = None
    try:
        for name in (datasets or DATASET_QUERIES):
            query = DATASET_QUERIES[name]
            print(f"Exporting {name}...", flush=True)
            business_metadata = None
            if name == "business_players":
                try:
                    business_metadata = warehouse_metadata(cursor)
                except Exception as error:
                    if not datasets and "TABLE_OR_VIEW_NOT_FOUND" in str(error):
                        print("  Optional business sample is not built; skipping.", flush=True)
                        continue
                    raise
            if definition is not None and name in {'players', 'business_players'}:
                if private_profiles is None:
                    private_profiles = prepare_private_profiles(fetch_frame(cursor, FAMILY_PROFILE_QUERY), definition,
                                                                archetype_model)
                if name == 'players':
                    frame = private_profiles.drop(columns='player_id').copy()
                else:
                    frame = attach_business_audience(fetch_frame(cursor, FAMILY_BUSINESS_QUERY), private_profiles, definition)
                frame.attrs['family_affinity'] = affinity_metadata(definition)
            else:
                frame = fetch_frame(cursor, query)
            if name == "players":
                frame, _ = population_weights(frame, reference)
                if definition is not None:
                    frame = frame.loc[:, [*PROFILE_AUDIENCE_COLUMNS, *(COLUMNS if pool_archetypes else ())]].copy()
            validate_public_frame(name, frame)
            if business_metadata is not None and (
                len(frame) != business_metadata["player_count"] or set(frame["scenario_id"]) != {business_metadata["scenario_id"]}
            ):
                raise ValueError("Business sample changed during export; retry after the load/build completes")

            destination = output_dir / DATASET_FILES[name]
            temporary = output_dir / f".{destination.name}.tmp"
            frame.to_parquet(temporary, index=False, compression="zstd")
            os.replace(temporary, destination)
            manifest["datasets"][name] = dataset_metadata(destination, frame)
            if 'pool_archetypes' in frame.attrs:
                manifest['datasets'][name]['pool_archetypes'] = model_metadata(archetype_model)
            if 'family_affinity' in frame.attrs:
                item = manifest['datasets'][name]
                item['sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
                item['family_affinity'] = frame.attrs['family_affinity']
                if name == 'players':
                    item['population_reference'] = {
                        'sha256': reference_fingerprint(reference),
                        'versions': sorted(reference.reference_version.unique().tolist()),
                        'weighting': 'Individual-tier calibration on the unfiltered profile scope',
                    }
                item['private_association'] = {
                    'method': 'Actual player key; family fields calculated before anonymous projection',
                    'profile_rows_validated_unique': len(private_profiles),
                    'business_join': 'player_id + queue; frozen traits retained, current traits prefixed audience_',
                }
                for column in ['audience_as_of_date', 'audience_snapshot_date', 'mastery_source_min_snapshot_date',
                               'mastery_source_max_snapshot_date']:
                    if column in frame and frame[column].notna().any():
                        values = pd.to_datetime(frame[column])
                        item[f'min_{column}'], item[f'max_{column}'] = json_value(values.min()), json_value(values.max())
                if name == 'business_players':
                    item['current_audience_matched_rows'] = int(frame.audience_as_of_date.notna().sum())
                    item['date_interpretation'] = 'Current audience traits attached to older frozen synthetic purchases; not historical preferences.'
            if business_metadata is not None:
                manifest["datasets"][name]["scenario"] = business_metadata
            print(f"  {len(frame):,} rows -> {destination.name}", flush=True)
    finally:
        cursor.close()
        connection.close()

    if pool_archetypes:
        model_file = output_dir / MODEL_PATH.name
        model_file.write_bytes(MODEL_PATH.read_bytes())
        manifest['pool_archetypes'] = {'file': model_file.name,
            'file_sha256': hashlib.sha256(model_file.read_bytes()).hexdigest(), **model_metadata(archetype_model)}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def fetch_frame(cursor: Any, query: str) -> pd.DataFrame:
    cursor.execute(query)
    try:
        return cursor.fetchall_arrow().to_pandas()
    except AttributeError:
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        return pd.DataFrame(rows, columns=columns)


def validate_public_frame(name: str, frame: pd.DataFrame) -> None:
    required = REQUIRED_COLUMNS[name]
    if name == "players":
        required = required | ACTIVE_POOL_LIFETIME_COLUMNS
    missing = required.difference(frame.columns)
    forbidden = FORBIDDEN_PUBLIC_COLUMNS.intersection(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing required columns: {sorted(missing)}")
    if forbidden:
        raise ValueError(f"{name} contains forbidden public columns: {sorted(forbidden)}")
    if frame.empty:
        raise ValueError(f"{name} returned no rows")
    if name in {'players', 'business_players'} and ('family_affinity' in frame.columns or 'family_affinity' in frame.attrs):
        validate_family_frame(frame, frame.attrs.get('family_affinity'), business=name == 'business_players')
    elif name == "business_players" and set(frame.columns) != set(BUSINESS_PUBLIC_COLUMNS):
        raise ValueError("Business export must use the explicit anonymous column allowlist")


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


def json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export anonymized Streamlit datasets from Databricks gold marts.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=APP_ROOT / "data",
        help="Destination directory for Parquet snapshots and manifest.json.",
    )
    parser.add_argument("--dataset", choices=sorted(DATASET_QUERIES), action="append", help="Export only the named dataset; can be repeated.")
    parser.add_argument('--family-audience', action='store_true',
                        help='Jointly associate frozen family affinity with profile and business rows before anonymization.')
    parser.add_argument('--pool-archetypes', action='store_true',
                        help='Apply the frozen eight-archetype model before anonymization; implies --family-audience.')
    return parser.parse_args()


if __name__ == "__main__":
    main()
