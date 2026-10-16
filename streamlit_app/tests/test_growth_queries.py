import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest
from app_core.config import REPO_ROOT
from app_core.queries import DATASET_QUERIES
from jinja2 import Environment


@pytest.fixture
def growth_database():
    connection = sqlite3.connect(":memory:")
    rows = []
    for player, tier, style, share, lift, rank, games, wins in [
        ("p1", "GOLD", "specialist", 0.8, 10, 500, 80, 64),
        ("p1", "GOLD", "versatile", 0.2, 100, 700, 20, 4),
        ("p1", "DIAMOND", "specialist", 1.0, 50, 900, 20, 10),
        ("p2", "GOLD", "versatile", 1.0, 30, 400, 10, 5),
    ]:
        rows.append(
            {
                "rank_period_id": str(len(rows)),
                "region": "na1",
                "queue": "solo",
                "player_id": player,
                "champion_key": 1,
                "previous_tier": tier,
                "rank_period_playstyle": style,
                "attribution_share": share,
                "lp_per_game_lift_vs_tier": lift,
                "rank_period_hhi": 0.5,
                "rank_period_top1_share": 0.7,
                "attributed_games": float(games),
                "attributed_wins": float(wins),
                "attributed_lp_delta": float(games * lift),
                "period_in_days": 7,
                "end_rank_score": rank,
            }
        )
    pd.DataFrame(rows).to_sql("fct_players_period_champion_growth", connection, index=False)
    pd.DataFrame({"key": [1], "name": ["Ahri"]}).to_sql("dim_champions", connection, index=False)
    yield connection
    connection.close()


def execute_analysis(connection, name):
    query = DATASET_QUERIES[name].replace("league_pipeline.gold.", "").replace("league_pipeline.silver.", "")
    return pd.read_sql(query.replace("<=>", "is"), connection)


def test_player_growth_uses_weighted_period_medians_and_keeps_starting_tiers(growth_database):
    frame = execute_analysis(growth_database, "champion_growth_players")
    assert len(frame) == 3
    gold = frame.loc[frame.starting_tier.eq("GOLD") & frame.period_count.eq(2)].iloc[0]
    assert gold.climbing_efficiency == 10
    assert gold.win_rate == pytest.approx(0.68)
    assert gold.end_rank_score == 600
    assert not {"player_id", "puuid", "rank_period_id"}.intersection(frame.columns)


def test_tier_growth_recomputes_each_style_instead_of_merging_subgroup_medians(growth_database):
    frame = execute_analysis(growth_database, "champion_tier_growth")
    gold = frame.loc[frame.starting_tier.eq("GOLD")]
    overall = gold.loc[gold.cohort_scope.eq("champion_tier")].iloc[0]
    assert overall.observed_player_tier_count == 2
    assert overall.climbing_efficiency == 20
    styles = gold.loc[gold.cohort_scope.eq("champion_tier_playstyle")].set_index("rank_period_playstyle")
    assert styles.loc["specialist", "climbing_efficiency"] == 10
    assert styles.loc["versatile", "climbing_efficiency"] == 65
    assert overall.climbing_efficiency != styles.climbing_efficiency.mean()


def test_invalid_lp_does_not_remove_recent_games_or_win_rate():
    source = (REPO_ROOT / "league_pipeline/models/gold/mart_player_profile.sql").read_text()
    recent = "with latest_period as (" + source.split("latest_period as (", 1)[1].split("\nselect\n    p.puuid", 1)[0]
    environment = Environment()
    environment.globals.update(
        ref=lambda name: name,
        var=lambda name, default=None: default,
        dbt_utils=SimpleNamespace(
            safe_divide=lambda numerator, denominator: f"1.0 * {numerator} / nullif({denominator}, 0)"
        ),
    )
    eligibility = (REPO_ROOT / "league_pipeline/macros/lp_growth_eligible.sql").read_text()
    environment.globals["lp_growth_eligible"] = environment.from_string(eligibility).module.lp_growth_eligible
    query = environment.from_string(recent + "select * from latest_rank_period").render()
    with sqlite3.connect(":memory:") as connection:
        pd.DataFrame(
            [
                {
                    "player_id": "invalid_lp",
                    "queue": "solo",
                    "period_bucket_start": "2026-09-28",
                    "period_bucket_days": 7,
                    "period_in_days": 7,
                    "games_delta": 10,
                    "wins_delta": 6,
                    "lp_delta": 1000,
                },
                {
                    "player_id": "valid",
                    "queue": "solo",
                    "period_bucket_start": "2026-09-28",
                    "period_bucket_days": 7,
                    "period_in_days": 7,
                    "games_delta": 10,
                    "wins_delta": 5,
                    "lp_delta": 20,
                },
            ]
        ).to_sql("fct_players_rank_periods", connection, index=False)
        result = pd.read_sql(query, connection).set_index("player_id")
    assert result.loc["invalid_lp", "games"] == 10
    assert result.loc["invalid_lp", "win_rate"] == pytest.approx(0.6)
    assert pd.isna(result.loc["invalid_lp", "lp_delta"])
    assert pd.isna(result.loc["invalid_lp", "lp_per_game"])
    assert result.loc["valid", "lp_per_game"] == 2
