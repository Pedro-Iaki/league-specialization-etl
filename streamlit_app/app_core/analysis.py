from __future__ import annotations

import numpy as np
import pandas as pd

from app_core.config import PLAYSTYLE_ORDER, ROLE_ORDER, TIER_ORDER

AXIS_LABELS = {
    "specialization_hhi": "Pool concentration (HHI)",
    "top_champion_share": "Top champion share",
    "inverse_entropy": "Pool concentration (1 − normalized entropy)",
    "champion_commitment": "Champion preference (mastery share)",
}


def profile_basis(players: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Expose the same profile columns for recent and lifetime mastery."""
    prefix = "active" if basis == "Active (60 days)" else "alltime"
    frame = players.copy()
    frame["playstyle"] = frame[f"{prefix}_playstyle"]
    frame["specialization_hhi"] = frame[f"{prefix}_hhi"]
    frame["top_champion_share"] = frame[f"{prefix}_top1_share"]
    frame["normalized_entropy"] = frame[f"{prefix}_normalized_entropy"]
    frame["primary_champion_name"] = (
        frame["active_primary_champion_name"] if prefix == "active" else frame["top_champion_name"]
    )
    frame["inverse_entropy"] = 1 - frame["normalized_entropy"]
    return frame


def growth_scatter_data(
    players: pd.DataFrame,
    growth_players: pd.DataFrame | None,
    basis: str,
) -> tuple[pd.DataFrame, str, str]:
    """Return a player-level scatter with an explicit outcome and time basis."""
    if basis == "Observed rank periods" and growth_players is not None:
        frame = growth_players.copy()
        frame["tier"] = frame["starting_tier"]
        frame["main_role"] = frame.get("current_main_role")
        frame["inverse_entropy"] = 1 - frame["normalized_entropy"]
        frame["outcome"] = frame["climbing_efficiency"]
        frame["support_games"] = frame["games"]
        return frame, "Climbing efficiency (LP/game vs tier)", "Observed rank periods"

    frame = profile_basis(players, basis)
    frame["outcome"] = frame["lp_per_game_recent"]
    frame["support_games"] = frame["games_recent"]
    return frame, "Recent rank LP/game (unadjusted)", f"{basis} pool × latest rank week"


def playstyle_composition(
    players: pd.DataFrame,
    basis: str,
    group: str = "tier",
    champion_name: str | None = None,
) -> pd.DataFrame:
    frame = profile_basis(players, basis)
    if champion_name is not None:
        frame = frame.loc[frame["primary_champion_name"] == champion_name]
    frame = frame.loc[frame["playstyle"].isin(PLAYSTYLE_ORDER)]
    frame = frame.loc[frame[group].notna()]
    grouped = frame.groupby([group, "playstyle"], observed=True).size().rename("players").reset_index()
    if grouped.empty:
        grouped["share"] = pd.Series(dtype=float)
        return grouped
    grouped["share"] = grouped["players"] / grouped.groupby(group)["players"].transform("sum")
    order = TIER_ORDER if group == "tier" else ROLE_ORDER
    grouped[group] = pd.Categorical(grouped[group], categories=order, ordered=True)
    return grouped.sort_values([group, "playstyle"])


def role_playstyle_skew(players: pd.DataFrame, basis: str) -> pd.DataFrame:
    frame = profile_basis(players, basis)
    frame = frame.loc[frame["playstyle"].isin(PLAYSTYLE_ORDER) & frame["main_role"].isin(ROLE_ORDER)]
    counts = pd.crosstab(frame["main_role"], frame["playstyle"]).reindex(
        index=ROLE_ORDER, columns=PLAYSTYLE_ORDER, fill_value=0
    )
    within_role = counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0)
    overall = frame["playstyle"].value_counts(normalize=True).reindex(PLAYSTYLE_ORDER, fill_value=0)
    return (within_role.subtract(overall, axis=1) * 100).fillna(0)


def binned_relationship(frame: pd.DataFrame, x: str, bins: int = 10) -> pd.DataFrame:
    valid = frame.loc[frame[x].notna() & frame["outcome"].notna(), [x, "outcome"]].copy()
    if len(valid) < 2 or valid[x].nunique() < 2:
        return pd.DataFrame(columns=[x, "outcome", "players"])
    valid["bin"] = pd.qcut(valid[x], q=min(bins, valid[x].nunique()), duplicates="drop")
    return valid.groupby("bin", observed=True).agg(
        **{x: (x, "mean"), "outcome": ("outcome", "mean"), "players": ("outcome", "size")}
    ).reset_index(drop=True)


def champion_landscape_data(champions: pd.DataFrame, players: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    frame = champions.copy()
    growth_column = "climbing_efficiency" if "climbing_efficiency" in frame else "lp_per_game_lift_vs_tier"
    frame["outcome"] = frame[growth_column]
    if "mean_commitment" in frame:
        frame["specialization_axis"] = frame["mean_commitment"]
        return frame, "Historical mean champion commitment"

    active = players.loc[players["active_primary_champion_name"].notna()].groupby(
        "active_primary_champion_name", observed=True
    )["active_hhi"].mean()
    frame["specialization_axis"] = frame["champion_name"].map(active)
    return frame, "Current primary players’ mean active HHI (preview)"


def growth_column(frame: pd.DataFrame) -> str:
    return "climbing_efficiency" if "climbing_efficiency" in frame else "lp_per_game_lift_vs_tier"


RANKED_SHARE_DIMENSIONS = {
    "Role": "current_main_role",
    "Tier": "starting_tier",
    "Champion": "favoured_champions",
}


def ranked_share_by_dimensions(
    players: pd.DataFrame,
    x_dimension: str,
    y_dimension: str,
    minimum_players: int = 1,
    champions: list[str] | None = None,
) -> pd.DataFrame:
    """Average player medians, with one row per player in each displayed cell."""
    frame = players.copy()
    for dimension in (x_dimension, y_dimension):
        source = RANKED_SHARE_DIMENSIONS[dimension]
        if dimension == "Champion":
            frame = frame.explode(source)
            if champions is not None:
                frame = frame.loc[frame[source].isin(champions)]
        frame[dimension] = frame[source]
    frame = frame.loc[
        frame[x_dimension].notna()
        & frame[y_dimension].notna()
        & frame["median_ranked_mastery_share"].notna()
    ]
    summary = frame.groupby([x_dimension, y_dimension], observed=True).agg(
        mean_share=("median_ranked_mastery_share", "mean"),
        player_count=("median_ranked_mastery_share", "size"),
    ).reset_index()
    return summary.loc[summary["player_count"] >= minimum_players]


def specialization_trend(players: pd.DataFrame) -> dict[str, float]:
    """Linear association matching the champion's unfiltered player scatter."""
    valid = players.loc[
        players["champion_commitment"].notna() & players["climbing_efficiency"].notna()
    ].copy()
    if len(valid) < 3:
        return {"players": len(valid), "slope_per_10pp": np.nan, "correlation": np.nan, "r_squared": np.nan}
    valid["x"] = valid["champion_commitment"] - valid["champion_commitment"].mean()
    valid["y"] = valid["climbing_efficiency"] - valid["climbing_efficiency"].mean()
    x = valid["x"].to_numpy(dtype=float)
    y = valid["y"].to_numpy(dtype=float)
    x_sum_squares = float(np.dot(x, x))
    y_sum_squares = float(np.dot(y, y))
    if x_sum_squares <= 0 or y_sum_squares <= 0:
        return {"players": len(valid), "slope_per_10pp": np.nan, "correlation": np.nan, "r_squared": np.nan}
    correlation = float(np.dot(x, y) / np.sqrt(x_sum_squares * y_sum_squares))
    return {
        "players": len(valid),
        "slope_per_10pp": 0.1 * float(np.dot(x, y) / x_sum_squares),
        "correlation": correlation,
        "r_squared": correlation**2,
    }


def composition_vs_population(champion: pd.DataFrame, population: pd.DataFrame, group: str) -> pd.DataFrame:
    baseline = population.loc[
        population[group].isin(champion[group]), [group, "playstyle", "share"]
    ].rename(columns={"share": "population_share"})
    result = baseline.merge(champion, on=[group, "playstyle"], how="left")
    result["share"] = result["share"].fillna(0)
    result["players"] = result["players"].fillna(0)
    result["difference_pp"] = 100 * (result["share"] - result["population_share"])
    return result


def champion_ranked_share_by_tier(players: pd.DataFrame, champion_name: str) -> pd.DataFrame:
    frame = players.loc[players["starting_tier"].notna()].copy()
    frame["favours_champion"] = frame["favoured_champions"].apply(
        lambda names: champion_name in names if isinstance(names, (list, tuple, np.ndarray)) else False
    )
    baseline = frame.groupby("starting_tier", observed=True)["median_ranked_mastery_share"].mean()
    champion = frame.loc[frame["favours_champion"]].groupby("starting_tier", observed=True).agg(
        share=("median_ranked_mastery_share", "mean"),
        players=("median_ranked_mastery_share", "size"),
    ).reset_index()
    champion["baseline_share"] = champion["starting_tier"].map(baseline)
    champion["difference_pp"] = 100 * (champion["share"] - champion["baseline_share"])
    return champion
