from __future__ import annotations

import json

import pandas as pd
from app_core.config import DATA_DIR, DATASET_FILES, MANIFEST_PATH
from app_core.queries import REQUIRED_COLUMNS

FORBIDDEN_PUBLIC_COLUMNS = {
    "player_id",
    "puuid",
    "rank_delta_id",
    "champion_pair_id",
    "champion_playstyle_id",
}
OPTIONAL_DATASETS = {
    "growth_players", "growth_player_styles", "champion_growth_players",
    "champion_tier_growth", "champion_tier_mastery", "champion_player_mastery_share",
}


def test_all_snapshot_files_follow_public_contract() -> None:
    for name, filename in DATASET_FILES.items():
        path = DATA_DIR / filename
        if name in OPTIONAL_DATASETS and not path.exists():
            continue
        assert path.exists(), f"Missing snapshot: {path}"
        frame = pd.read_parquet(path)
        assert not frame.empty
        assert REQUIRED_COLUMNS[name].issubset(frame.columns)
        assert not FORBIDDEN_PUBLIC_COLUMNS.intersection(frame.columns)


def test_manifest_matches_snapshot_row_counts() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for name, filename in DATASET_FILES.items():
        if name in OPTIONAL_DATASETS and not (DATA_DIR / filename).exists():
            continue
        frame = pd.read_parquet(DATA_DIR / filename)
        assert manifest["datasets"][name]["rows"] == len(frame)


def test_champion_mastery_snapshot_has_dashboard_thresholds() -> None:
    path = DATA_DIR / DATASET_FILES["champion_tier_mastery"]
    if not path.exists():
        return
    frame = pd.read_parquet(path)
    assert {"ALL", "IRON", "MASTER"}.issubset(set(frame["tier"]))
    assert {15_000, *range(0, 100_000, 10_000)}.issubset(set(frame["minimum_mastery"]))
