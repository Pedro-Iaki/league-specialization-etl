from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from app_core.analysis import binned_relationship, one_trick_tier_distribution, tier_population_comparison
from app_core.population import (
    WEIGHT,
    apply_tier_weights,
    calibrate_population,
    population_weights,
    weighted_summary,
)
from app_core.population_champions import champion_estimates, mastery_summary, population_pairs
from app_core.queries import DATASET_QUERIES
from streamlit.testing.v1 import AppTest


def test_cached_weights_are_recalculated_from_the_local_reference():
    raw = pd.DataFrame({"tier": ["IRON", "GOLD", "GOLD"], "region": "BR1", "queue": "solo"})
    exported, _ = calibrate_population(raw)
    checked, _ = population_weights(exported)
    np.testing.assert_allclose(checked[WEIGHT], exported[WEIGHT])
    exported.loc[0, WEIGHT] = 1
    recalculated, _ = population_weights(exported)
    np.testing.assert_allclose(recalculated[WEIGHT], checked[WEIGHT])


def test_champion_subset_keeps_full_cohort_weights_and_raw_counts():
    raw = pd.DataFrame({"tier": ["BRONZE"] * 4 + ["DIAMOND"] * 4})
    _, report = calibrate_population(raw)
    subset = raw.iloc[[0, 4, 5, 6, 7]].assign(champion_name="Ahri", outcome=[1, 0, 0, 0, 0])
    weighted = apply_tier_weights(subset, report)
    summary = weighted_summary(weighted, "champion_name", {"outcome": "outcome"}).iloc[0]
    assert summary["players"] == 5
    assert summary["outcome"] == pytest.approx(0.166 / (0.166 + 4 * 0.0368))
    assert summary["outcome"] != pytest.approx(0.166 / (0.166 + 0.0368))


def test_legacy_tier_export_cannot_guess_multiple_region_weights():
    raw = pd.DataFrame({"tier": ["IRON", "GOLD", "IRON", "GOLD"], "region": ["BR1", "BR1", "EUW1", "EUW1"]})
    _, report = calibrate_population(raw)
    with pytest.raises(ValueError, match="region and queue"):
        apply_tier_weights(pd.DataFrame({"tier": ["IRON"]}), report)
    result = apply_tier_weights(raw.iloc[:1], report)
    assert len(result) == 1


def test_pooled_trend_and_mastery_use_weights_not_average_of_tier_medians():
    frame = pd.DataFrame({"x": [0, 0, 1, 1], "outcome": [1, 0, 0, 0], WEIGHT: [10, 1, 1, 1]})
    trend = binned_relationship(frame, "x", bins=2)
    assert trend["players"].tolist() == [2, 2]
    assert trend["outcome"].tolist() == [pytest.approx(10 / 11), 0]
    masteries = pd.DataFrame({"champion_name": "Ahri", "champion_points": [20_000, 200_000, 300_000], WEIGHT: [20, 1, 1]})
    summary = mastery_summary(masteries).iloc[0]
    assert summary["players"] == 3
    assert summary["mean_mastery"] == pytest.approx(900_000 / 22)
    assert summary["median_mastery"] < 100_000
    assert summary["expert_share"] == pytest.approx(2 / 22)


def test_primary_representation_weights_both_sides_and_retains_support():
    frame = pd.DataFrame({
        "tier": ["IRON", "IRON", "GOLD", "GOLD"],
        "recent_primary_champion_name": ["Ahri", "Annie", "Ahri", "Ahri"],
        "recent_playstyle": "specialist", "recent_hhi": 0.9, "recent_top1_share": 0.9,
        "recent_normalized_entropy": 0.1, WEIGHT: [4, 4, 1, 1],
    })
    comparison = tier_population_comparison(frame, "Ahri", "Recent activity").set_index("tier")
    assert comparison.loc["IRON", "all_share"] == pytest.approx(0.8)
    assert comparison.loc["IRON", "champion_share"] == pytest.approx(4 / 6)
    assert comparison.loc["GOLD", "champion_players"] == 2
    frame["lifetime_mastery_points"] = 500_000
    holders = pd.DataFrame({"champion_name": ["Ahri", "Ahri"], "tier": ["IRON", "GOLD"],
                            "minimum_mastery": 0, "player_count": [2, 2], WEIGHT: [4, 1]})
    otp = one_trick_tier_distribution(frame, holders).set_index("tier")
    assert otp.loc["IRON", "one_trick_share"] == pytest.approx(4 / 6)
    assert otp.loc["IRON", "champion_share"] == pytest.approx(0.8)
    assert otp["one_trick_players"].sum() == 3


def test_activity_aggregates_use_weighted_numerators_and_observed_counts():
    players = pd.DataFrame({"recent_primary_champion_name": ["Ahri", "Ahri"], "rank_score": [100, 900], WEIGHT: [4, 1]})
    activity = pd.DataFrame({"champion_name": "Ahri", "recent_player_count": [1, 9],
                             "recent_pool_player_count": [10, 10], "mean_recent_share": [0.8, 0.2],
                             "role_sample_player_count": [1, 9], WEIGHT: [4, 1],
                             **{f"role_{role}_pct": [0.5, 0.1] for role in ["top", "jungle", "middle", "bottom", "support"]}})
    result = champion_estimates(pd.DataFrame({"champion_name": ["Ahri"]}), players, None, None, None, None, activity).iloc[0]
    assert result["recent_pool_membership_rate"] == pytest.approx(13 / 50)
    assert result["recent_player_count"] == 10
    assert result["avg_current_rank_score"] == 260
    assert result["role_top_pct"] == pytest.approx(2.9 / 13)


def test_player_export_needs_only_profiles_and_excludes_identifiers():
    query = DATASET_QUERIES["players"]
    assert "mart_player_profile" in query
    assert "mart_player_population_weights" not in query
    select = query.split("from", 1)[0]
    assert "population_weight" not in select
    assert "player_id" not in select and "puuid" not in select


def test_overlap_probabilities_weight_counts_but_support_stays_observed():
    frame = pd.DataFrame({
        "champion_key_a": 1, "champion_name_a": "Ahri", "champion_key_b": 2, "champion_name_b": "Annie",
        "pair_player_count": [1, 1], "player_count_a": [5, 1], "player_count_b": [2, 8],
        "recent_pool_player_count": [10, 10], WEIGHT: [4, 1],
    })
    pair = population_pairs(frame).iloc[0]
    assert pair["pair_player_count"] == 2
    assert pair["pair_player_count_mass"] == 5
    assert pair["prob_b_given_a"] == pytest.approx(5 / 21)
    assert pair["prob_a_given_b"] == pytest.approx(5 / 16)
    assert pair["jaccard"] == pytest.approx(5 / 32)
    assert pair["lift"] == pytest.approx(250 / 336)


@pytest.mark.parametrize("page", ["overview.py", "pages/2_Champion_Explorer.py", "pages/3_Notable_Champions.py"])
def test_pages_render_with_weighted_and_sample_denominators(page):
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / page), default_timeout=60).run()
    assert not app.exception
    widget = next(widget for widget in app.radio if widget.label == "Analysis denominator")
    widget.set_value("Collected sample").run()
    assert not app.exception
    assert app.session_state["population_estimate_mode"] == "Collected sample"
