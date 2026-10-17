from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from app_core import data
from app_core.contracts import REQUIRED_COLUMNS


@pytest.fixture
def snapshot_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(data, "MANIFEST_PATH", tmp_path / "manifest.json")
    data._load_dataset_cached.clear()
    yield tmp_path
    data._load_dataset_cached.clear()


def test_manual_snapshot_replacement_updates_data_and_scenario_metadata(snapshot_directory):
    def export(scenario):
        frame = pd.DataFrame({column: [None] for column in REQUIRED_COLUMNS["business_players"]})
        frame["scenario_id"] = scenario
        frame.to_parquet(snapshot_directory / data.DATASET_FILES["business_players"], index=False)
        metadata = {"scenario_id": scenario, "player_count": 1}
        data.MANIFEST_PATH.write_text(json.dumps({"datasets": {"business_players": {"scenario": metadata}}}))
        return metadata

    first_metadata = export("first")
    version = data.MANIFEST_PATH.stat().st_mtime_ns
    first = data.load_dataset("business_players")
    assert first["scenario_id"].tolist() == ["first"]
    assert first.attrs["business_scenario"] == first_metadata

    second_metadata = export("second")
    os.utime(data.MANIFEST_PATH, ns=(version + 1_000_000, version + 1_000_000))
    second = data.load_dataset("business_players")
    assert second["scenario_id"].tolist() == ["second"]
    assert second.attrs["business_scenario"] == second_metadata


def test_optional_missing_snapshot_is_skipped_but_invalid_snapshot_fails(snapshot_directory):
    assert data.load_optional_dataset("business_players") is None
    with pytest.raises(data.DashboardDataError, match="Snapshot not found"):
        data.load_dataset("business_players")

    pd.DataFrame({"scenario_id": ["incomplete"]}).to_parquet(
        snapshot_directory / data.DATASET_FILES["business_players"], index=False,
    )
    with pytest.raises(data.DashboardDataError, match="missing:"):
        data.load_optional_dataset("business_players")


def test_app_starts_without_warehouse_modules_or_export_queries():
    app_root = Path(__file__).resolve().parents[1]
    script = """
import builtins
import sys
from pathlib import Path
from streamlit.testing.v1 import AppTest

sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
def offline_import(name, *args, **kwargs):
    if name.split('.')[0] in {'databricks', 'src'} or name == 'app_core.queries':
        raise AssertionError(f'Dashboard attempted to import warehouse/export module: {name}')
    return original_import(name, *args, **kwargs)
builtins.__import__ = offline_import
app = AppTest.from_file(str(Path(sys.argv[1]) / 'app.py'), default_timeout=60).run()
assert not app.exception, [error.value for error in app.exception]
assert len(app.get('plotly_chart')) == 2
for page in ('story/03_tiers.py', 'story/04_growth.py', 'story/05_champions.py', 'business.py'):
    app.switch_page(page).run()
    assert not app.exception, [error.value for error in app.exception]
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(app_root)], capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
