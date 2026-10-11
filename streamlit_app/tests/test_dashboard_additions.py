from __future__ import annotations

import numpy as np
import pandas as pd
from app_core.analysis import (
    champion_overlap_summary,
    climber_playstyle_composition,
    expert_share_vs_sample,
    mastery_normalized_composition,
    mastery_representation_by_tier,
    playstyle_composition,
    playstyle_mastery_bands,
    tier_population_comparison,
)


def mastery_players(tiers, mastery, styles):
    return pd.DataFrame({
        "tier": tiers, "total_mastery_points": mastery, "alltime_playstyle": styles,
        "alltime_hhi": 0.5, "alltime_top1_share": 0.6,
        "alltime_normalized_entropy": 0.4, "top_champion_name": "Ahri",
    })


def test_climber_composition_requires_positive_net_lp_and_observed_games():
    players = mastery_players(["GOLD"] * 6, [100] * 6,
                             ["specialist", "generalist", "specialist", "generalist", "generalist", "generalist"])
    players["lp_delta_recent"] = [20, 10, 0, -10, np.nan, 100]
    players["games_recent"] = [4, 2, 5, 3, 2, 0]
    players["lp_per_game_lift_vs_tier"] = [-5, -2, 10, 20, 10, 10]
    result = climber_playstyle_composition(players, "All-time")
    assert result["players"].sum() == 2
    assert np.allclose(result["share"], 0.5)


def test_active_and_observed_includes_all_available_delta_signs():
    players = mastery_players(["GOLD"] * 4, [300_000] * 4, ["generalist"] * 4)
    for suffix in ["playstyle", "hhi", "top1_share", "normalized_entropy"]:
        players[f"active_{suffix}"] = players[f"alltime_{suffix}"]
    players["active_playstyle"] = ["specialist"] * 3 + ["generalist"]
    players["active_primary_champion_name"] = "Riven"
    players["lp_delta_recent"] = [10, 0, -10, np.nan]
    raw = playstyle_composition(players, "Active and observed")
    assert raw["players"].sum() == 3
    assert raw["playstyle"].eq("specialist").all()
    normalized = mastery_normalized_composition(players, "Active and observed")
    assert normalized["players"].sum() == 3
    assert normalized.loc[normalized["playstyle"].eq("specialist"), "baseline_share"].eq(1).all()
    players["lp_delta_recent"] = np.nan
    assert playstyle_composition(players, "Active and observed").empty
    assert mastery_normalized_composition(players, "Active and observed").empty


def test_mastery_normalization_removes_expected_mastery_trend():
    players = mastery_players(
        ["GOLD"] * 4 + ["DIAMOND"] * 4, [100] * 4 + [1000] * 4,
        ["specialist"] * 3 + ["generalist"] + ["specialist"] + ["generalist"] * 3,
    )
    result = mastery_normalized_composition(players, "All-time", bins=2)
    supported = result.loc[result["baseline_share"].gt(0)]
    assert np.allclose(supported["relative_share"], 1)
    assert np.isclose(result.loc[(result["tier"] == "DIAMOND") & (result["playstyle"] == "generalist"), "share"].iloc[0], 0.75)
    assert result.loc[result["baseline_share"].eq(0), "relative_share"].isna().all()


def test_climber_normalization_uses_population_baseline():
    players = mastery_players(["GOLD"] * 6, [300_000] * 6,
                             ["specialist"] * 2 + ["generalist"] * 4)
    players["lp_delta_recent"] = [20, 10, 0, -10, np.nan, -20]
    players["games_recent"] = [4] * 6
    result = climber_playstyle_composition(players, "All-time", normalized=True).set_index("playstyle")
    assert result["players"].sum() == 2
    assert result.loc["specialist", "share"] == 1
    assert np.isclose(result.loc["specialist", "baseline_share"], 1 / 3)
    assert result.loc["specialist", "relative_share"] == 3
    assert result.loc["generalist", "relative_share"] == 0
    assert np.isnan(result.loc["versatile", "relative_share"])
    assert climber_playstyle_composition(players, "All-time", normalized=True, minimum_mastery=400_000).empty


def test_mastery_normalization_interpolates_at_group_median():
    players = mastery_players(
        ["GOLD", "GOLD", "DIAMOND", "DIAMOND"], [100, 400, 200, 300],
        ["specialist", "generalist", "specialist", "generalist"],
    )
    result = mastery_normalized_composition(players, "All-time", bins=2)
    assert result["median_mastery"].eq(250).all()
    assert result.loc[result["playstyle"].isin(["specialist", "generalist"]), "baseline_share"].eq(0.5).all()
    assert result.loc[result["baseline_share"].gt(0), "relative_share"].eq(1).all()


def test_mastery_normalization_handles_constant_mastery_and_filters():
    players = mastery_players(["GOLD"] * 4, [100, 100, 0, np.nan],
                             ["specialist", "generalist", "generalist", "generalist"])
    result = mastery_normalized_composition(players, "All-time")
    assert result["players"].sum() == 2
    assert result.loc[result["baseline_share"].gt(0), "relative_share"].eq(1).all()
    assert mastery_normalized_composition(players, "All-time", minimum_mastery=200).empty


def test_conditional_overlap_uses_selected_champion_direction() -> None:
    pairs = pd.DataFrame({
        "champion_name_a": ["Ahri", "Teemo"],
        "champion_name_b": ["Riven", "Ahri"],
        "pair_player_count": [10, 30],
        "prob_b_given_a": [0.2, 0.6],
        "prob_a_given_b": [0.4, 0.3],
    })
    result = champion_overlap_summary(pairs, "Ahri")
    assert result["pairs"] == 2
    assert np.isclose(result["conditional"], 0.275)


def test_tier_representation_uses_population_share_as_baseline() -> None:
    players = pd.DataFrame({
        "tier": ["IRON", "IRON", "GOLD", "GOLD"],
        "active_primary_champion_name": ["Ahri", "Teemo", "Ahri", "Teemo"],
        "active_playstyle": ["specialist"] * 4,
        "active_hhi": [0.5] * 4,
        "active_top1_share": [0.6] * 4,
        "active_normalized_entropy": [0.4] * 4,
    })
    result = tier_population_comparison(players, "Ahri", "Active (60 days)")
    assert result.loc[result["tier"] == "IRON", "representation_ratio"].iloc[0] == 1
    assert result.loc[result["tier"] == "GOLD", "champion_players"].iloc[0] == 1


def test_mastery_threshold_removes_low_mastery_players() -> None:
    players = pd.DataFrame({
        "total_mastery_points": [100, 200, 300, 400],
        "alltime_playstyle": ["specialist", "specialist", "generalist", "generalist"],
        "alltime_hhi": [0.5] * 4,
        "alltime_top1_share": [0.6] * 4,
        "alltime_normalized_entropy": [0.4] * 4,
        "top_champion_name": ["Ahri"] * 4,
    })
    result = playstyle_mastery_bands(players, "All-time", 250, bins=2)
    assert result["players"].sum() == 2
    assert result["playstyle"].eq("generalist").all()


def test_mastery_representation_removes_champion_level_difference() -> None:
    tiers = pd.DataFrame({
        "champion_name": ["Caitlyn", "Caitlyn", "Riven", "Riven"],
        "tier": ["GOLD", "DIAMOND", "GOLD", "DIAMOND"],
        "minimum_mastery": [0] * 4,
        "player_count": [100] * 4,
        "mean_mastery": [1000, 4000, 100, 400],
        "mean_rank_score": [1400, 2600, 1400, 2600],
    })
    result = mastery_representation_by_tier(tiers, 0)
    assert np.allclose(result["representation_ratio"], 1)
    assert np.allclose(result["log2_representation"], 0)
    assert result.groupby("tier")["tier_rank_score"].nunique().eq(1).all()


def test_mastery_representation_orders_each_champion_by_ladder_tier() -> None:
    tiers = pd.DataFrame({
        "champion_name": ["Riven", "Ahri", "Riven", "Ahri", "Riven", "Ahri"],
        "tier": ["DIAMOND", "GOLD", "BRONZE", "DIAMOND", "GOLD", "BRONZE"],
        "minimum_mastery": [0] * 6,
        "player_count": [10] * 6,
        "mean_mastery": [100] * 6,
        "mean_rank_score": [2500, 1500, 500, 2500, 1500, 500],
    })
    result = mastery_representation_by_tier(tiers, 0)
    assert result.loc[result["champion_name"] == "Ahri", "tier"].tolist() == ["BRONZE", "GOLD", "DIAMOND"]
    assert result.loc[result["champion_name"] == "Riven", "tier"].tolist() == ["BRONZE", "GOLD", "DIAMOND"]


def test_expert_share_comparison_uses_pooled_tier_reference_at_threshold() -> None:
    tiers = pd.DataFrame({
        "champion_name": ["Ahri", "Riven", "Ahri", "Riven"],
        "tier": ["GOLD"] * 4,
        "minimum_mastery": [20_000, 20_000, 0, 0],
        "player_count": [100, 300, 100, 300],
        "expert_player_count": [20, 30, 80, 30],
    })
    result = expert_share_vs_sample(tiers, "Ahri", 20_000).iloc[0]
    assert np.isclose(result["expert_share"], 0.2)
    assert np.isclose(result["sample_expert_share"], 0.125)
    assert np.isclose(result["expert_share_difference_pct"], 60)
