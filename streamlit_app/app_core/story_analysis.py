"""Fixed, sample-based comparisons for the guided portfolio story."""
from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd

from app_core.analysis import one_trick_tier_distribution
from app_core.config import MIN_SUPPORT_PLAYERS, PLAYSTYLE_ORDER, TIER_ORDER

BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 42
CASE_GROUPS = {
    "Case group A": ["Teemo", "Mordekaiser", "Heimerdinger", "Tahm Kench"],
    "Case group B": ["Riven", "Gangplank", "Hwei"],
}
CASE_TIER_ORDER = [*TIER_ORDER[:-2], "Diamond+"]


def coverage_counts(players: pd.DataFrame, core_profiles: int | None) -> pd.DataFrame:
    """Nested coverage of current profiles; follow-up is distinct from usable growth."""
    counts = {
        "Current profiles": len(players),
        "Complete core context": core_profiles,
        "Rank-period follow-up": int(players["latest_rank_period_games"].notna().sum()),
        "Usable recent-week LP outcome": int((
            players["latest_rank_period_games"].ge(2)
            & np.isfinite(players["latest_rank_period_lp_per_game"])
        ).sum()),
    }
    return pd.DataFrame([
        {"stage": stage, "players": count} for stage, count in counts.items() if count is not None
    ])


def growth_uncertainty(growth: pd.DataFrame) -> pd.DataFrame:
    """Percentile bootstrap of equal-vote player/tier/style means, with measured SDs.

    No identifier is present in the serving file, so these intervals cannot cluster
    repeated observations by player. They describe this observed sample only.
    """
    random = np.random.default_rng(BOOTSTRAP_SEED)
    rows = []
    for style in PLAYSTYLE_ORDER:
        values = growth.loc[
            growth["rank_period_playstyle"].eq(style) & growth["games"].ge(1), "climbing_efficiency"
        ].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        mean = values.mean() if len(values) else np.nan
        low = high = np.nan
        if len(values) >= MIN_SUPPORT_PLAYERS:
            means = random.choice(values, (BOOTSTRAP_RESAMPLES, len(values)), replace=True).mean(axis=1)
            low, high = np.quantile(means, [0.025, 0.975])
        rows.append({
            "playstyle": style, "observations": len(values), "mean": mean, "low": low, "high": high,
            "sample_sd": values.std(ddof=1) if len(values) > 1 else np.nan,
        })
    return pd.DataFrame(rows)


def detectable_gap(summary: pd.DataFrame, sizes: np.ndarray) -> np.ndarray:
    """Approximate two-group 80% power at two-sided alpha=.05, equal group sizes."""
    supported = summary.loc[summary["observations"].ge(MIN_SUPPORT_PLAYERS)]
    degrees = supported["observations"] - 1
    pooled_variance = (degrees * supported["sample_sd"] ** 2).sum() / degrees.sum() if degrees.sum() else np.nan
    normal = NormalDist()
    return (normal.inv_cdf(0.975) + normal.inv_cdf(0.8)) * np.sqrt(2 * pooled_variance / sizes)


def champion_case_comparison(players: pd.DataFrame, tier_mastery: pd.DataFrame) -> pd.DataFrame:
    """Pool actual counts, with both holder and all-champion one-trick baselines.

    One-tricks follow the explorer default: >=300k lifetime mastery and recent
    main share >=80% OR HHI >=.65. Holder records can repeat across champions.
    """
    distribution = one_trick_tier_distribution(
        players.drop(columns="population_weight", errors="ignore"), tier_mastery,
    )
    distribution["tier"] = distribution["tier"].astype(object).replace({"DIAMOND": "Diamond+", "MASTER": "Diamond+"})
    holders = tier_mastery.loc[
        tier_mastery["minimum_mastery"].eq(0) & tier_mastery["tier"].isin(TIER_ORDER)
    ].copy()
    holders["tier"] = holders["tier"].replace({"DIAMOND": "Diamond+", "MASTER": "Diamond+"})
    all_mains = distribution.groupby("tier")["one_trick_players"].sum().reindex(CASE_TIER_ORDER, fill_value=0)
    rows = []
    for group, champions in CASE_GROUPS.items():
        selected = distribution.loc[distribution["champion_name"].isin(champions)]
        counts = selected.groupby("tier")[["one_trick_players"]].sum().reindex(CASE_TIER_ORDER, fill_value=0)
        counts["champion_players"] = holders.loc[holders["champion_name"].isin(champions)].groupby(
            "tier"
        )["player_count"].sum().reindex(CASE_TIER_ORDER, fill_value=0)
        for column, label in [("one_trick_players", "One-tricks"), ("champion_players", "Champion holders")]:
            total = int(counts[column].sum())
            for tier, count in counts[column].items():
                rows.append({"group": group, "series": label, "tier": tier, "players": int(count),
                             "total": total, "share": count / total if total else np.nan})
        for tier, count in all_mains.items():
            total = int(all_mains.sum())
            rows.append({"group": group, "series": "All-champion one-tricks", "tier": tier,
                         "players": int(count), "total": total, "share": count / total if total else np.nan})
    return pd.DataFrame(rows)
