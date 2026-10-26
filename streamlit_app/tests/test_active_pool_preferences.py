import json
import sqlite3

import pandas as pd
import pytest
from app_core.config import DATA_DIR, DATASET_FILES
from app_core.contracts import ACTIVE_POOL_LIFETIME_COLUMNS
from app_core.data import _validate_dataset
from app_core.queries import DATASET_QUERIES
from scripts.export_data import validate_public_frame


@pytest.fixture
def preference_profiles():
    # Supply the established mart columns without maintaining a second schema.
    players = pd.read_parquet(DATA_DIR / DATASET_FILES["players"]).head(6).copy()
    players["player_id"] = [f"p{i}" for i in range(6)]
    players["region"] = players["player_id"]
    players["recent_champion_names"] = [
        json.dumps(names) if names is not None else None
        for names in (["A", "B", "C"], ["B", "A"], ["C"], [], ["A", "B"], None)
    ]
    masteries = pd.DataFrame(
        [
            ("p0", 1, 90_000), ("p0", 2, 10_000), ("p0", 3, 1_000), ("p0", 99, 1_000_000),
            ("p1", 1, 5_000), ("p1", 2, 5_000),
            ("p2", 3, 400), ("p3", 99, 1_000_000),
            ("p4", 1, 0), ("p4", 2, 0), ("p5", 1, 90_000),
        ],
        columns=["puuid", "champion_key", "champion_points"],
    )
    champions = pd.DataFrame({"key": [1, 2, 3, 99], "name": ["A", "B", "C", "Abandoned"]})
    query = DATASET_QUERIES["players"].replace("league_pipeline.gold.", "").replace("league_pipeline.silver.", "")
    with sqlite3.connect(":memory:") as connection:
        connection.create_function("array_contains", 2, lambda names, name: name in json.loads(names or "[]"))
        players.to_sql("mart_player_profile", connection, index=False)
        masteries.to_sql("fct_masteries_current", connection, index=False)
        champions.to_sql("dim_champions", connection, index=False)
        result = pd.read_sql_query(query, connection)
        old_columns = [column for column in result if column not in ACTIVE_POOL_LIFETIME_COLUMNS]
        original = pd.read_sql_query(f"select {', '.join(old_columns)} from mart_player_profile", connection)
    return original, result


def test_active_pool_preferences_use_all_members_lifetime_mastery(preference_profiles):
    _, result = preference_profiles
    profiles = result.set_index("region")
    mixed = profiles.loc["p0"]
    assert mixed.active_pool_lifetime_champion_count == 3
    assert mixed.active_pool_lifetime_mastery_points == 101_000
    assert mixed.active_pool_lifetime_primary_champion_name == "A"
    assert mixed.active_pool_lifetime_primary_champion_points == 90_000
    assert mixed.active_pool_lifetime_top1_share == pytest.approx(90 / 101)
    assert mixed.active_pool_lifetime_hhi == pytest.approx((90**2 + 10**2 + 1) / 101**2)
    tied = profiles.loc["p1"]
    assert tied.active_pool_lifetime_primary_champion_key == 1
    assert tied.active_pool_lifetime_primary_champion_points == 5_000
    assert tied.active_pool_lifetime_top1_share == 0.5
    assert tied.active_pool_lifetime_hhi == 0.5
    single = profiles.loc["p2"]
    assert single.active_pool_lifetime_primary_champion_name == "C"
    assert single.active_pool_lifetime_top1_share == 1
    assert single.active_pool_lifetime_hhi == 1
    # A reporting cutoff affects eligibility, without inflating the full-pool share.
    eligible = result.loc[result.active_pool_lifetime_primary_champion_points.ge(15_000)]
    assert eligible.region.tolist() == ["p0"]
    assert eligible.iloc[0].active_pool_lifetime_top1_share == pytest.approx(90 / 101)


def test_empty_and_zero_total_pools_do_not_invent_preferences(preference_profiles):
    _, result = preference_profiles
    profiles = result.set_index("region")
    missing = profiles.loc[["p3", "p4", "p5"]]
    assert missing.active_pool_lifetime_champion_count.tolist() == [0, 2, 0]
    assert missing.active_pool_lifetime_mastery_points.eq(0).all()
    preference_columns = ACTIVE_POOL_LIFETIME_COLUMNS - {
        "active_pool_lifetime_champion_count", "active_pool_lifetime_mastery_points",
    }
    assert missing[list(preference_columns)].isna().all().all()


def test_export_preserves_old_fields_grain_and_privacy(preference_profiles):
    original, result = preference_profiles
    pd.testing.assert_frame_equal(result[original.columns], original)
    assert len(result) == 6
    assert not {"player_id", "puuid", "recent_champion_names"}.intersection(result.columns)
    validate_public_frame("players", result)
    with pytest.raises(ValueError, match="missing required columns"):
        validate_public_frame("players", original)
    with pytest.raises(ValueError, match="forbidden public columns"):
        validate_public_frame("players", result.assign(player_id="private"))
    # New export fields do not make a refresh mandatory just to start the app.
    _validate_dataset("players", original)
