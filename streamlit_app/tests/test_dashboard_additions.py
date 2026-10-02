from __future__ import annotations

import numpy as np
import pandas as pd
from app_core.analysis import (
    champion_overlap_summary,
    expert_share_vs_sample,
    mastery_representation_by_tier,
    playstyle_mastery_bands,
    tier_population_comparison,
)


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
