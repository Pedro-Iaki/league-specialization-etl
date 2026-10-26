from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app_core.business import BUSINESS_PUBLIC_COLUMNS
from app_core.config import DATA_DIR, DATASET_FILES, MANIFEST_PATH, TIER_ORDER
from app_core.contracts import REQUIRED_COLUMNS
from app_core.i18n import t
from app_core.snapshot_hash import sha256_file


class DashboardDataError(RuntimeError):
    """Raised when a dashboard dataset is unavailable or violates its contract."""


def load_dataset(name: str, *, include_all_tiers: bool = False) -> pd.DataFrame:
    """Load and validate one local Parquet snapshot."""
    if name not in DATASET_FILES:
        raise DashboardDataError(f"Unknown dashboard dataset: {name}")
    snapshot_version = MANIFEST_PATH.stat().st_mtime_ns if MANIFEST_PATH.exists() else None
    frame = _load_dataset_cached(name, snapshot_version)
    if name == "business_players" or include_all_tiers:
        return frame.copy()  # preserve the full frozen denominator, including any apex tiers
    allowed_tiers = set(TIER_ORDER) | ({"ALL"} if name == "champion_tier_mastery" else set())
    for tier_column in ("tier", "starting_tier", "previous_tier"):
        if tier_column in frame:
            frame = frame.loc[frame[tier_column].isna() | frame[tier_column].isin(allowed_tiers)]
    return frame.copy()


def load_optional_dataset(name: str) -> pd.DataFrame | None:
    """Use new analytical extracts when available; keep older snapshots readable."""
    if not snapshot_paths()[name].exists():
        return None
    return load_dataset(name)


@st.cache_data(show_spinner=False)
def _load_dataset_cached(name: str, snapshot_version: int | None) -> pd.DataFrame:
    """Cache a local dataset until a manual export changes its manifest version."""
    frame = _read_snapshot(name)
    return _validate_dataset(name, frame)


def _read_snapshot(name: str) -> pd.DataFrame:
    path = DATA_DIR / DATASET_FILES[name]
    if not path.exists():
        raise DashboardDataError(
            f"Snapshot not found at {path}. Run scripts/export_data.py from the "
            "streamlit_app directory."
        )
    frame = pd.read_parquet(path)
    item = load_manifest().get('datasets', {}).get(name, {})
    if name in {'players', 'business_players'} and ('archetype_state' in frame or item.get('pool_archetypes')):
        from app_core.archetype_serving import load_model, model_metadata
        entry = load_manifest().get('pool_archetypes', {})
        model_path = DATA_DIR / entry.get('file', 'missing-archetype-model')
        if (not model_path.is_file() or sha256_file(model_path, normalize_newlines=True) != entry.get('file_sha256')
                or item.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest()
                or item.get('pool_archetypes') != model_metadata(load_model(model_path))):
            raise DashboardDataError('Archetype snapshot/model does not match its manifest.')
        frame.attrs['pool_archetypes'] = item['pool_archetypes']
    if name in {'players', 'business_players'} and ('family_affinity' in frame or item.get('family_affinity')):
        if (not item.get('family_affinity') or item.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest()
                or item.get('rows') != len(frame)):
            raise DashboardDataError('Family audience snapshot hash/metadata does not match its manifest.')
        frame.attrs['family_affinity'] = item['family_affinity']
        if name == 'business_players' and (
                'scenario_id' not in frame or set(frame.scenario_id) != {item.get('scenario', {}).get('scenario_id')}
                or item.get('scenario', {}).get('player_count') != len(frame)):
            raise DashboardDataError('Family business snapshot does not match its frozen scenario.')
    if name == "business_players":
        metadata = load_manifest().get("datasets", {}).get(name, {}).get("scenario", {})
        if metadata and set(frame["scenario_id"]) == {metadata.get("scenario_id")}:
            frame.attrs["business_scenario"] = metadata
    return frame


def _validate_dataset(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = REQUIRED_COLUMNS[name]
    missing = required.difference(frame.columns)
    if missing:
        missing_columns = ", ".join(sorted(missing))
        raise DashboardDataError(f"Dataset '{name}' is missing: {missing_columns}")
    if name in {'players', 'business_players'} and ('family_affinity' in frame or 'family_affinity' in frame.attrs):
        from app_core.family_exports import validate_family_frame
        try:
            validate_family_frame(frame, frame.attrs.get('family_affinity'), business=name == 'business_players')
        except (TypeError, ValueError) as error:
            raise DashboardDataError(str(error)) from error
    elif name == "business_players" and set(frame.columns) - set(BUSINESS_PUBLIC_COLUMNS):
        raise DashboardDataError("Business dataset violates the anonymous column allowlist")
    return frame


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def snapshot_paths() -> dict[str, Path]:
    return {name: DATA_DIR / filename for name, filename in DATASET_FILES.items()}


def data_freshness(frames: list[pd.DataFrame]) -> str:
    """Return the latest available analytical date across loaded frames."""
    dates: list[pd.Timestamp] = []
    for frame in frames:
        for column in ("as_of_date", "snapshot_date"):
            if column in frame.columns and frame[column].notna().any():
                dates.append(pd.to_datetime(frame[column]).max())
                break
    if not dates:
        return t("Unknown")
    latest = max(dates)
    return t("_formats.long_date", p0=f"{latest.day:02d}", p1=t(latest.strftime("%B")), p2=latest.year)
