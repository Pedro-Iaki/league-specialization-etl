"""Rebuild pooled champion estimates from records retaining tier information."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app_core.population import row_weights, weighted_quantile, weighted_summary


def mastery_summary(masteries: pd.DataFrame, minimum: int = 15_000) -> pd.DataFrame:
    frame = masteries.loc[masteries["champion_points"].ge(minimum)].copy()
    frame["expert"] = frame["champion_points"].ge(100_000).astype(float)
    result = weighted_summary(frame, "champion_name", {"mean_mastery": "champion_points", "expert_share": "expert"})
    medians = frame.groupby("champion_name", observed=True).apply(
        lambda rows: weighted_quantile(rows["champion_points"], row_weights(rows)), include_groups=False,
    )
    result["median_mastery"] = result["champion_name"].map(medians)
    result["expert_player_count"] = result["champion_name"].map(frame.groupby("champion_name")["expert"].sum())
    return result


def population_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    """Estimate overlap probabilities from tier counts, retaining observed support."""
    frame = frame.copy()
    counts = ["pair_player_count", "player_count_a", "player_count_b", "recent_pool_player_count"]
    for column in counts:
        frame[column + "_mass"] = frame[column] * row_weights(frame)
    keys = ["champion_key_a", "champion_name_a", "champion_key_b", "champion_name_b"]
    result = frame.groupby(keys, observed=True)[counts + [column + "_mass" for column in counts]].sum().reset_index()
    pair, a, b, total = [result[column + "_mass"] for column in counts]
    result["jaccard"] = pair / (a + b - pair).replace(0, np.nan)
    result["prob_b_given_a"] = pair / a.replace(0, np.nan)
    result["prob_a_given_b"] = pair / b.replace(0, np.nan)
    result["lift"] = pair * total / (a * b).replace(0, np.nan)
    support = pair / total.replace(0, np.nan)
    result["npmi"] = np.log2(result["lift"].replace(0, np.nan)) / -np.log2(support.replace({0: np.nan, 1: np.nan}))
    return result


def champion_estimates(
    champions: pd.DataFrame, players: pd.DataFrame, growth: pd.DataFrame | None,
    ranked: pd.DataFrame | None, masteries: pd.DataFrame | None, tier_mastery: pd.DataFrame | None,
    activity: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Counts retain their grain. Historical pooling uses player–tier summaries.

    Aggregates without tier detail have undefined population values until the
    additional anonymous activity export is available.
    """
    result = champions.copy().set_index("champion_name")
    for column in ("recent_pool_membership_rate", "recent_player_count", "recent_pool_player_count", "avg_recent_pool_share",
                   "role_sample_player_count", "role_top_pct", "role_jungle_pct", "role_middle_pct",
                   "role_bottom_pct", "role_support_pct", "median_mastery_points",
                   "observed_win_rate", "climbing_efficiency", "mean_commitment", "mean_rank_period_hhi",
                   "avg_end_rank_score", "median_end_rank_score", "observed_player_tier_count"):
        if column in result:
            result[column] = np.nan
    primary = weighted_summary(players, "recent_primary_champion_name", {
        "avg_current_rank_score": "rank_score",
    }).set_index("recent_primary_champion_name")
    result["avg_current_rank_score"] = primary["avg_current_rank_score"]
    result["recent_primary_player_count"] = primary["players"]
    medians = players.groupby("recent_primary_champion_name", observed=True).apply(
        lambda rows: weighted_quantile(rows["rank_score"], row_weights(rows)), include_groups=False,
    )
    result["median_current_rank_score"] = medians
    if growth is not None:
        metrics = {"climbing_efficiency": "climbing_efficiency", "observed_win_rate": "win_rate",
                   "mean_commitment": "champion_commitment", "mean_rank_period_hhi": "specialization_hhi"}
        if "end_rank_score" in growth:
            metrics["avg_end_rank_score"] = "end_rank_score"
        metrics = {label: source for label, source in metrics.items() if source in growth}
        pooled = weighted_summary(growth, "champion_name", metrics).set_index("champion_name")
        for column in metrics:
            result[column] = pooled[column]
        result["observed_player_tier_count"] = pooled["players"]
        if "end_rank_score" in growth:
            medians = growth.groupby("champion_name", observed=True).apply(
                lambda rows: weighted_quantile(rows["end_rank_score"], row_weights(rows)), include_groups=False,
            )
            result["median_end_rank_score"] = medians
    if ranked is not None:
        periods = ranked.loc[ranked["window_name"].eq("All observed periods")].explode("favoured_champions")
        pooled = weighted_summary(periods, "favoured_champions", {"mean_ranked_share": "median_ranked_mastery_share"})
        pooled = pooled.set_index("favoured_champions")
        result["mean_ranked_share"] = pooled["mean_ranked_share"]
        result["ranked_share_players"] = pooled["players"]
    if tier_mastery is not None:
        holders = tier_mastery.loc[tier_mastery["minimum_mastery"].eq(0) & tier_mastery["tier"].ne("ALL")].copy()
        holders["mass"] = holders["player_count"] * row_weights(holders)
        holders["expert_mass"] = holders["expert_player_count"] * row_weights(holders)
        holders["points_mass"] = holders["mean_mastery"] * holders["mass"]
        pooled = holders.groupby("champion_name")[["mass", "expert_mass", "points_mass", "player_count", "expert_player_count"]].sum()
        result["expert_player_share"] = pooled["expert_mass"] / pooled["mass"].replace(0, np.nan)
        result["avg_mastery_points"] = pooled["points_mass"] / pooled["mass"].replace(0, np.nan)
        result["mastery_player_count"] = pooled["player_count"]
        result["expert_player_count"] = pooled["expert_player_count"]
    if masteries is not None:
        pooled = mastery_summary(masteries).set_index("champion_name")
        result["mean_mastery_15k"] = pooled["mean_mastery"]
        result["median_mastery_15k"] = pooled["median_mastery"]
        result["mastery_players_15k"] = pooled["players"]
    if activity is not None:
        recent_activity = activity.copy()
        recent_activity["mass"] = recent_activity["recent_player_count"] * row_weights(recent_activity)
        recent_activity["denominator_mass"] = recent_activity["recent_pool_player_count"] * row_weights(recent_activity)
        recent_activity["share_mass"] = recent_activity["mean_recent_share"] * recent_activity["mass"]
        pooled = recent_activity.groupby("champion_name")[["mass", "denominator_mass", "share_mass", "recent_player_count", "recent_pool_player_count"]].sum()
        result["recent_pool_membership_rate"] = pooled["mass"] / pooled["denominator_mass"].replace(0, np.nan)
        result["avg_recent_pool_share"] = pooled["share_mass"] / pooled["mass"].replace(0, np.nan)
        result["recent_player_count"] = pooled["recent_player_count"]
        result["recent_pool_player_count"] = pooled["recent_pool_player_count"]
        recent_activity["role_mass"] = recent_activity["role_sample_player_count"] * row_weights(recent_activity)
        for column in ("role_top_pct", "role_jungle_pct", "role_middle_pct", "role_bottom_pct", "role_support_pct"):
            numerator = (recent_activity[column] * recent_activity["role_mass"]).groupby(recent_activity["champion_name"]).sum(min_count=1)
            denominator = recent_activity["role_mass"].where(recent_activity[column].notna()).groupby(recent_activity["champion_name"]).sum()
            result[column] = numerator / denominator.replace(0, np.nan)
        result["role_sample_player_count"] = recent_activity.groupby("champion_name")["role_sample_player_count"].sum()
    return result.reset_index()
