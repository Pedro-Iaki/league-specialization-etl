from __future__ import annotations

import pandas as pd
from app_core.analysis import champion_ranked_share_by_tier, composition_vs_population, specialization_trend
from app_core.charts import champion_tier_outcome_heatmap, playstyle_outcome_chart


def test_over_under_includes_playstyles_missing_from_champion_players() -> None:
    champion = pd.DataFrame(
        {"tier": ["GOLD"], "playstyle": ["specialist"], "share": [1.0], "players": [8]}
    )
    population = pd.DataFrame(
        {
            "tier": ["GOLD", "GOLD"],
            "playstyle": ["specialist", "generalist"],
            "share": [0.25, 0.75],
        }
    )
    result = composition_vs_population(champion, population, "tier").set_index("playstyle")
    assert result.loc["specialist", "difference_pp"] == 75
    assert result.loc["generalist", "difference_pp"] == -75
    assert result.loc["generalist", "players"] == 0


def test_specialization_trend_keeps_direction_and_scale() -> None:
    players = pd.DataFrame(
        {
            "champion_commitment": [0.2, 0.4, 0.6],
            "climbing_efficiency": [4.0, 2.0, 0.0],
        }
    )
    trend = specialization_trend(players)
    assert trend["correlation"] == -1
    assert trend["slope_per_10pp"] == -1
    assert trend["r_squared"] == 1


def test_ranked_share_over_under_uses_all_players_in_same_tier() -> None:
    players = pd.DataFrame(
        {
            "starting_tier": ["GOLD", "GOLD", "SILVER"],
            "median_ranked_mastery_share": [0.8, 0.4, 0.2],
            "favoured_champions": [["Ahri"], ["Ezreal"], ["Ahri"]],
        }
    )
    result = champion_ranked_share_by_tier(players, "Ahri").set_index("starting_tier")
    assert result.loc["GOLD", "players"] == 1
    assert abs(result.loc["GOLD", "difference_pp"] - 20) < 1e-9
    assert result.loc["SILVER", "difference_pp"] == 0


def test_playstyle_tier_over_under_uses_champion_tier_average() -> None:
    playstyle = pd.DataFrame(
        {
            "starting_tier": ["GOLD"],
            "playstyle": ["specialist"],
            "observed_player_count": [8],
            "climbing_efficiency": [3.0],
            "observed_win_rate": [0.53],
        }
    )
    tier = pd.DataFrame(
        {"starting_tier": ["GOLD"], "climbing_efficiency": [1.0], "observed_win_rate": [0.50]}
    )
    lift = champion_tier_outcome_heatmap(playstyle, tier, "climbing_efficiency", True)
    win_rate = champion_tier_outcome_heatmap(playstyle, tier, "observed_win_rate", True)
    raw_win_rate = champion_tier_outcome_heatmap(playstyle, tier, "observed_win_rate", False)
    assert lift.data[0].z[0][0] == 2
    assert abs(win_rate.data[0].z[0][0] - 3) < 1e-9
    assert raw_win_rate.data[0].zmin == 0.45
    assert raw_win_rate.data[0].zmax == 0.55


def test_playstyle_win_rate_bars_keep_outcomes_outside_old_zoom_visible() -> None:
    summary = pd.DataFrame({
        "playstyle": ["specialist", "generalist"],
        "observed_win_rate": [0.3, 0.7],
        "observed_player_count": [12, 15],
        "observed_period_count": [20, 25],
    })
    figure = playstyle_outcome_chart(summary, "observed_win_rate", "Mean player win rate")
    lower, upper = figure.layout.yaxis.range
    assert lower == 0
    for trace in figure.data:
        assert all(lower <= value <= upper for value in trace.y)
