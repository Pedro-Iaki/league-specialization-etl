from __future__ import annotations

import pandas as pd
from app_core.analysis import (
    champion_ranked_share_by_tier,
    composition_vs_population,
    one_trick_tier_distribution,
    specialization_trend,
)
from app_core.charts import champion_tier_outcome_heatmap, playstyle_outcome_chart


def test_one_trick_distribution_uses_recent_main_or_hhi_and_player_baseline():
    players = pd.DataFrame({
        "recent_primary_champion_name": ["Riven", "Riven", "Riven", "Riven", None, "Riven"],
        "tier": ["GOLD", "DIAMOND", "GOLD", "GOLD", "GOLD", "GOLD"],
        "lifetime_mastery_points": [300_000, 400_000, 200_000, 500_000, 500_000, 500_000],
        "recent_top1_share": [0.8, 0.5, 1.0, 0.3, 1.0, float("nan")],
        "recent_hhi": [0.5, 0.7, 1.0, 0.4, 1.0, float("nan")],
        "recent_mastery_points": [1000, 1000, 1000, 1000, 0, 1000],
    })
    baseline = pd.DataFrame({
        "champion_name": ["Riven"] * 4, "tier": ["GOLD", "DIAMOND", "ALL", "GOLD"],
        "minimum_mastery": [0, 0, 0, 10_000], "player_count": [30, 10, 40, 1],
        "mean_mastery": [100, 1_000_000, 100, 100],
    })
    result = one_trick_tier_distribution(players, baseline).set_index("tier")
    assert result["one_trick_players"].sum() == 2
    assert result.loc["GOLD", "one_trick_share"] == 0.5
    assert result.loc["DIAMOND", "champion_share"] == 0.25
    assert result.loc["DIAMOND", "representation_ratio"] == 2
    assert result.loc["DIAMOND", "difference_pp"] == 25
    assert pd.isna(result.loc["IRON", "representation_ratio"])
    assert one_trick_tier_distribution(players, baseline, criterion="Main share")["one_trick_players"].sum() == 1
    assert one_trick_tier_distribution(players, baseline, criterion="HHI")["one_trick_players"].sum() == 1
    assert one_trick_tier_distribution(players, baseline, minimum_mastery=600_000).empty


def test_one_trick_baseline_agreement_and_measured_zero():
    players = pd.DataFrame({
        "recent_primary_champion_name": ["Teemo", "Teemo", "Riven"],
        "tier": ["GOLD", "DIAMOND", "GOLD"], "lifetime_mastery_points": [300_000] * 3,
        "recent_top1_share": [0.9] * 3, "recent_hhi": [0.8] * 3, "recent_mastery_points": [1000] * 3,
    })
    baseline = pd.DataFrame({
        "champion_name": ["Teemo", "Teemo", "Riven", "Riven"],
        "tier": ["GOLD", "DIAMOND", "GOLD", "DIAMOND"],
        "minimum_mastery": [0] * 4, "player_count": [10] * 4,
    })
    result = one_trick_tier_distribution(players, baseline)
    assert result.loc[result["champion_name"].eq("Teemo") & result["champion_players"].gt(0), "representation_ratio"].eq(1).all()
    zero = result.loc[result["champion_name"].eq("Riven") & result["tier"].eq("DIAMOND")].iloc[0]
    assert zero["one_trick_share"] == 0
    assert zero["representation_ratio"] == 0


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
            "rank_period_playstyle": ["specialist"],
            "observed_player_tier_count": [8],
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
        "rank_period_playstyle": ["specialist", "generalist"],
        "observed_win_rate": [0.3, 0.7],
        "observed_player_tier_count": [12, 15],
        "observed_period_count": [20, 25],
    })
    figure = playstyle_outcome_chart(summary, "observed_win_rate", "Mean player win rate")
    lower, upper = figure.layout.yaxis.range
    assert lower == 0
    for trace in figure.data:
        assert all(lower <= value <= upper for value in trace.y)
