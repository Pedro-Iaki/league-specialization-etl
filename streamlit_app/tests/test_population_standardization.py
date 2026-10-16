from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from app_core.population import (
    WEIGHT,
    calibrate_population,
    direct_standardized_means,
    load_reference,
    weighted_mean,
)


def selected_profiles():
    # Retention differs by tier: one of four Bronze, all four Diamond.
    return pd.DataFrame({
        "tier": ["BRONZE"] * 4 + ["DIAMOND"] * 4,
        "region": "BR1", "queue": "SOLO",
        "recent_playstyle": ["specialist", None, None, None] + ["generalist"] * 4,
        "lifetime_playstyle": "generalist",
        "recent_hhi": [1.0] * 4 + [0.0] * 4,
        "lifetime_hhi": [0.5] * 8,
        "lifetime_mastery_points": 1000.0,
        "rank_score": 400.0,
        "latest_rank_period_lp_per_game": [10.0, None, None, None, 0.0, 0.0, None, None],
        "latest_rank_period_win_rate": [0.8, None, None, None, 0.5, 0.5, None, None],
    })


def test_conditional_and_standardized_estimates_answer_different_questions():
    weighted, _ = calibrate_population(selected_profiles())
    selected = weighted.loc[weighted.recent_playstyle.notna()]
    conditional = weighted_mean(selected.recent_hhi, selected[WEIGHT])
    summary, tiers = direct_standardized_means(selected, ["recent_hhi"], minimum_tier_players=1)
    assert conditional == pytest.approx(0.166 / (0.166 + 4 * 0.0368))
    assert summary.standardized_mean.iloc[0] == pytest.approx(0.166 / (0.166 + 0.0368))
    assert summary.covered_population_share.iloc[0] == pytest.approx(0.2028)
    assert summary.coverage_status.iloc[0] == "low_coverage"
    assert tiers.set_index("tier").loc["BRONZE", "metric_players"] == 1
    # Inherited or stale player weights must not influence a tier mean.
    selected = selected.copy()
    selected[WEIGHT] = [100, 1, 2, 3, 4]
    assert direct_standardized_means(selected, ["recent_hhi"], minimum_tier_players=1)[0].equals(summary)


def test_support_is_metric_specific_and_empty_tiers_are_explicit():
    frame = selected_profiles()
    summary, tiers = direct_standardized_means(frame, ["recent_hhi", "latest_rank_period_lp_per_game"], minimum_tier_players=2)
    recent = summary.set_index("metric").loc["latest_rank_period_lp_per_game"]
    assert recent.standardized_mean == 0
    assert recent.covered_population_share == pytest.approx(0.0368)
    assert recent.supported_players == 2
    assert recent.metric_players == 3
    assert len(tiers) == 20
    bronze = tiers.loc[(tiers.metric == "latest_rank_period_lp_per_game") & (tiers.tier == "BRONZE")].iloc[0]
    assert bronze.metric_players == 1
    assert not bronze.tier_supported
    assert pd.isna(bronze.supported_target_share)
    summary, tiers = direct_standardized_means(frame, ["recent_hhi"], minimum_tier_players=5)
    assert pd.isna(summary.standardized_mean.iloc[0])
    assert summary.coverage_status.iloc[0] == "no_supported_tiers"
    assert summary.covered_population_share.iloc[0] == 0
    assert tiers.supported_target_share.isna().all()


def test_standardization_separates_scopes_and_handles_invalid_and_unsupported_values():
    frame = selected_profiles()
    second = frame.iloc[:1].copy()
    second["region"] = None
    second["queue"] = None
    unknown = second.copy()
    unknown["tier"] = "UNRANKED"
    unknown["recent_hhi"] = 9000
    frame = pd.concat([frame, second, unknown])  # Duplicate indices are intentional.
    frame.iloc[0, frame.columns.get_loc("recent_hhi")] = np.inf
    summary, tiers = direct_standardized_means(frame, ["recent_hhi"], minimum_tier_players=1)
    assert len(summary) == 2
    assert len(tiers) == 20
    null_scope = summary.loc[summary.region.isna()].iloc[0]
    assert null_scope.standardized_mean == 1
    assert null_scope.unsupported_tier_players == 1
    assert tiers.loc[tiers.region.eq("BR1") & tiers.tier.eq("BRONZE"), "metric_players"].iloc[0] == 3
    empty, diagnostics = direct_standardized_means(frame.iloc[:0], ["recent_hhi"])
    assert empty.empty and diagnostics.empty
    assert "standardized_mean" in empty
    with pytest.raises(ValueError):
        direct_standardized_means(frame, ["recent_hhi"], minimum_tier_players=0)




def test_full_reference_recovers_full_standardized_mean():
    reference = load_reference()
    frame = pd.DataFrame({"tier": reference.tier, "outcome": range(10)})
    summary, _ = direct_standardized_means(frame, ["outcome"], minimum_tier_players=1)
    assert summary.standardized_mean.iloc[0] == pytest.approx((reference.population_share * frame.outcome).sum())
    assert summary.coverage_status.iloc[0] == "adequate_coverage"
