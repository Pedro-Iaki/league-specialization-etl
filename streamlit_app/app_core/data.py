from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app_core.business import BUSINESS_PUBLIC_COLUMNS
from app_core.config import DATA_DIR, DATASET_FILES, MANIFEST_PATH, REPO_ROOT, TIER_ORDER
from app_core.i18n import t
from app_core.queries import DATASET_QUERIES, REQUIRED_COLUMNS


class DashboardDataError(RuntimeError):
    """Raised when a dashboard dataset is unavailable or violates its contract."""


def configured_data_mode() -> str:
    """Return the requested data mode, defaulting to deployment-safe snapshots."""
    mode = os.getenv("LEAGUE_DASHBOARD_DATA_MODE", "snapshot").strip().lower()
    if mode not in {"snapshot", "databricks"}:
        raise DashboardDataError("LEAGUE_DASHBOARD_DATA_MODE must be either 'snapshot' or 'databricks'.")
    return mode


def _validate_dataset(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    required = REQUIRED_COLUMNS[name]
    missing = required.difference(frame.columns)
    if missing:
        missing_columns = ", ".join(sorted(missing))
        raise DashboardDataError(f"Dataset '{name}' is missing: {missing_columns}")
    if name == "business_players" and set(frame.columns) - set(BUSINESS_PUBLIC_COLUMNS):
        raise DashboardDataError("Business dataset violates the anonymous column allowlist")
    return frame


def _read_snapshot(name: str) -> pd.DataFrame:
    path = DATA_DIR / DATASET_FILES[name]
    if not path.exists():
        raise DashboardDataError(
            f"Snapshot not found at {path}. Run scripts/export_data.py from the "
            "streamlit_app directory or switch to Databricks mode."
        )
    frame = pd.read_parquet(path)
    if name == "business_players":
        metadata = load_manifest().get("datasets", {}).get(name, {}).get("scenario", {})
        if metadata and set(frame["scenario_id"]) == {metadata.get("scenario_id")}:
            frame.attrs["business_scenario"] = metadata
    return frame


def _load_databricks_connection():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from src.load.databricks_helper import get_connection

    return get_connection()


def _read_databricks(name: str) -> pd.DataFrame:
    connection = _load_databricks_connection()
    cursor = connection.cursor()
    try:
        metadata = None
        if name == "business_players":
            from src.sample.validation import warehouse_metadata
            metadata = warehouse_metadata(cursor)
        cursor.execute(DATASET_QUERIES[name])
        try:
            frame = cursor.fetchall_arrow().to_pandas()
        except AttributeError:
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description]
            frame = pd.DataFrame(rows, columns=columns)
        if metadata is not None:
            if len(frame) != metadata["player_count"] or set(frame["scenario_id"]) != {metadata["scenario_id"]}:
                raise DashboardDataError("Business sample changed during reading; reload after the sample build finishes")
            frame.attrs["business_scenario"] = metadata
        return frame
    except Exception as error:
        if name == "business_players":
            raise DashboardDataError(str(error)) from error
        raise
    finally:
        cursor.close()
        connection.close()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_dataset_cached(name: str, selected_mode: str, snapshot_version: int | None) -> pd.DataFrame:
    """Cache a dataset by name, mode, and snapshot manifest version."""
    frame = _read_snapshot(name) if selected_mode == "snapshot" else _read_databricks(name)
    return _validate_dataset(name, frame)


def load_dataset(name: str, mode: str | None = None, *, include_all_tiers: bool = False) -> pd.DataFrame:
    """Load one contracted dataset from a local snapshot or Databricks."""
    if name not in DATASET_FILES:
        raise DashboardDataError(f"Unknown dashboard dataset: {name}")
    selected_mode = mode or configured_data_mode()
    snapshot_version = MANIFEST_PATH.stat().st_mtime_ns if selected_mode == "snapshot" and MANIFEST_PATH.exists() else None
    frame = _load_dataset_cached(name, selected_mode, snapshot_version)
    if name == "business_players" or include_all_tiers:
        return frame.copy()  # preserve the full frozen denominator, including any apex tiers
    allowed_tiers = set(TIER_ORDER) | ({"ALL"} if name == "champion_tier_mastery" else set())
    for tier_column in ("tier", "starting_tier", "previous_tier"):
        if tier_column in frame:
            frame = frame.loc[frame[tier_column].isna() | frame[tier_column].isin(allowed_tiers)]
    return frame.copy()


def load_optional_dataset(name: str) -> pd.DataFrame | None:
    """Use new analytical extracts when available; keep older snapshots readable."""
    if configured_data_mode() == "snapshot" and not snapshot_paths()[name].exists():
        return None
    try:
        return load_dataset(name)
    except Exception as error:
        if name == "business_players" and "TABLE_OR_VIEW_NOT_FOUND" in str(error):
            return None
        raise


@st.cache_data(ttl=3600, show_spinner=False)
def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


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


def snapshot_paths() -> dict[str, Path]:
    return {name: DATA_DIR / filename for name, filename in DATASET_FILES.items()}
