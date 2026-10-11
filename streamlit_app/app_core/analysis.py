from __future__ import annotations

import numpy as np
import pandas as pd

from app_core.config import MIN_SUPPORT_PLAYERS, PLAYSTYLE_ORDER, ROLE_ORDER, TIER_ORDER
from app_core.population import (
    effective_sample_size,
    eligible_weighted_rows,
    row_weights,
    weighted_mean,
    weighted_quantile,
)

AXIS_LABELS = {
    "specialization_hhi": "Pool concentration (HHI)",
    "top_champion_share": "Top champion mastery share",
    "inverse_entropy": "Pool concentration (1 − normalized entropy)",
    "champion_commitment": "Champion mastery share",
}


def profile_basis(players: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Expose active or lifetime profiles, optionally requiring an observed LP delta."""
    prefix = "active" if basis in {"Active (60 days)", "Active and observed"} else "alltime"
    frame = eligible_weighted_rows(players)
    if basis == "Active and observed":
        frame = frame.loc[frame["lp_delta_recent"].notna()].copy()
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
        return frame, "LP/game above starting-tier baseline", "Observed rank periods"

    frame = profile_basis(players, basis)
    frame["outcome"] = frame["lp_per_game_recent"]
    frame["support_games"] = frame["games_recent"]
    return frame, "Recent rank LP/game (unadjusted)", f"{basis} pool × latest rank week"


def composition_cells(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    frame = frame.copy()
    frame["_weight"] = row_weights(frame)
    frame = frame.loc[frame["_weight"].notna()]
    grouped = frame.groupby([group, "playstyle"], observed=True).agg(
        players=("_weight", "size"), weighted_mass=("_weight", "sum"),
    ).reset_index()
    grouped["share"] = grouped["weighted_mass"] / grouped.groupby(group, observed=True)["weighted_mass"].transform("sum")
    effective = frame.groupby(group, observed=True)["_weight"].agg(effective_sample_size)
    grouped["effective_group_players"] = grouped[group].map(effective).astype(float)
    return grouped


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
    grouped = composition_cells(frame, group)
    if grouped.empty:
        grouped["share"] = pd.Series(dtype=float)
        return grouped
    order = TIER_ORDER if group == "tier" else ROLE_ORDER if group == "main_role" else sorted(frame[group].dropna().unique())
    grouped[group] = pd.Categorical(grouped[group], categories=order, ordered=True)
    return grouped.sort_values([group, "playstyle"])


def role_playstyle_skew(players: pd.DataFrame, basis: str) -> pd.DataFrame:
    frame = profile_basis(players, basis)
    frame = frame.loc[frame["playstyle"].isin(PLAYSTYLE_ORDER) & frame["main_role"].isin(ROLE_ORDER)]
    counts = pd.crosstab(frame["main_role"], frame["playstyle"]).reindex(
        index=ROLE_ORDER, columns=PLAYSTYLE_ORDER, fill_value=0
    )
    frame["_weight"] = row_weights(frame)
    masses = frame.pivot_table(index="main_role", columns="playstyle", values="_weight", aggfunc="sum", observed=True).reindex(
        index=ROLE_ORDER, columns=PLAYSTYLE_ORDER, fill_value=0,
    ).fillna(0)
    within_role = masses.div(masses.sum(axis=1).replace(0, np.nan), axis=0)
    overall = frame.groupby("playstyle", observed=True)["_weight"].sum().reindex(PLAYSTYLE_ORDER, fill_value=0)
    overall = overall / overall.sum() if overall.sum() else overall * np.nan
    differences = within_role.subtract(overall, axis=1) * 100
    role_support = counts.sum(axis=1)
    supported_cells = (counts >= MIN_SUPPORT_PLAYERS) | (
        counts.eq(0) & role_support.ge(MIN_SUPPORT_PLAYERS).to_numpy()[:, None]
    )
    raw_differences = differences.copy()
    differences = differences.where(supported_cells)
    differences.attrs["support_counts"] = counts
    differences.attrs["raw_differences"] = raw_differences
    return differences


def climber_playstyle_composition(
    players: pd.DataFrame, basis: str, group: str = "tier", *, normalized: bool = False,
    minimum_mastery: int = 0,
) -> pd.DataFrame:
    """Count each classified player with positive net LP in the latest observed period once."""
    climbers = players.loc[players["lp_delta_recent"].gt(0) & players["games_recent"].gt(0)]
    if normalized:
        return mastery_normalized_composition(
            climbers, basis, group, minimum_mastery, baseline_players=players,
        )
    return playstyle_composition(climbers, basis, group)


def mastery_normalized_composition(
    players: pd.DataFrame, basis: str, group: str = "tier", minimum_mastery: int = 0, bins: int = 8,
    *, baseline_players: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Observed / expected share at each group's median mastery, interpolated between pooled bands.

    All styles (including measured zeros) enter each band denominator. Out-of-range
    medians use the nearest band; a zero expected share gives an undefined ratio.
    An optional baseline population supplies bands while group medians and observed
    shares always come from the players being compared.
    This is a descriptive median-based adjustment, not full distribution standardization.
    """
    frame = profile_basis(players, basis)
    frame = frame.loc[
        frame["total_mastery_points"].ge(max(1, minimum_mastery))
        & frame["playstyle"].isin(PLAYSTYLE_ORDER)
        & frame[group].notna()
    ].copy()
    if group in {"tier", "main_role"}:
        frame = frame.loc[frame[group].isin(TIER_ORDER if group == "tier" else ROLE_ORDER)]
    columns = [group, "playstyle", "players", "share", "median_mastery", "baseline_share", "relative_share"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    reference = frame.copy() if baseline_players is None else profile_basis(baseline_players, basis)
    reference = reference.loc[
        reference["total_mastery_points"].ge(max(1, minimum_mastery))
        & reference["playstyle"].isin(PLAYSTYLE_ORDER) & reference[group].notna()
    ].copy()
    if group in {"tier", "main_role"}:
        reference = reference.loc[reference[group].isin(TIER_ORDER if group == "tier" else ROLE_ORDER)]
    if reference.empty:
        return pd.DataFrame(columns=columns)
    if reference["total_mastery_points"].nunique() < 2:
        reference["band"] = 0
    else:
        reference["band"] = pd.qcut(
            reference["total_mastery_points"], q=min(bins, reference["total_mastery_points"].nunique()),
            duplicates="drop",
        )
    reference["_weight"] = row_weights(reference)
    band_counts = reference.groupby(["band", "playstyle"], observed=True)["_weight"].sum().unstack(fill_value=0)
    band_counts = band_counts.reindex(columns=PLAYSTYLE_ORDER, fill_value=0)
    band_shares = band_counts.div(band_counts.sum(axis=1), axis=0)
    band_mastery = reference.groupby("band", observed=True).apply(
        lambda rows: weighted_quantile(rows["total_mastery_points"], rows["_weight"]), include_groups=False,
    )
    # Tied band medians have one common baseline interpolation point.
    band_shares["mastery"] = band_mastery
    baseline = band_shares.groupby("mastery", sort=True)[PLAYSTYLE_ORDER].mean()

    counts = frame.groupby([group, "playstyle"], observed=True).size().unstack(fill_value=0)
    counts = counts.reindex(columns=PLAYSTYLE_ORDER, fill_value=0)
    result = counts.rename_axis(columns="playstyle").stack().rename("players").reset_index()
    cells = composition_cells(frame, group)
    result = result.merge(cells.drop(columns="players"), on=[group, "playstyle"], how="left")
    result["share"] = result["share"].fillna(0)
    result["weighted_mass"] = result["weighted_mass"].fillna(0)
    frame["_weight"] = row_weights(frame)
    group_medians = frame.groupby(group, observed=True).apply(
        lambda rows: weighted_quantile(rows["total_mastery_points"], rows["_weight"]), include_groups=False,
    )
    group_effective = frame.groupby(group, observed=True)["_weight"].agg(effective_sample_size)
    result["effective_group_players"] = result[group].map(group_effective).astype(float)
    result["median_mastery"] = result[group].map(
        group_medians
    ).astype(float)
    result["baseline_share"] = np.nan
    for style in PLAYSTYLE_ORDER:
        mask = result["playstyle"].eq(style)
        result.loc[mask, "baseline_share"] = np.interp(
            result.loc[mask, "median_mastery"], baseline.index.to_numpy(dtype=float), baseline[style],
        )
    result["relative_share"] = result["share"] / result["baseline_share"].replace(0, np.nan)
    order = TIER_ORDER if group == "tier" else ROLE_ORDER if group == "main_role" else sorted(counts.index)
    result[group] = pd.Categorical(result[group], categories=order, ordered=True)
    return result.sort_values([group, "playstyle"])


def binned_relationship(frame: pd.DataFrame, x: str, bins: int = 10) -> pd.DataFrame:
    valid = eligible_weighted_rows(frame)
    valid = valid.loc[valid[x].notna() & valid["outcome"].notna()].copy()
    valid["_weight"] = row_weights(valid)
    if len(valid) < 2 or valid[x].nunique() < 2:
        return pd.DataFrame(columns=[x, "outcome", "players"])
    valid["bin"] = pd.qcut(valid[x], q=min(bins, valid[x].nunique()), duplicates="drop")
    return valid.groupby("bin", observed=True).apply(
        lambda rows: pd.Series({x: weighted_mean(rows[x], rows["_weight"]),
                               "outcome": weighted_mean(rows["outcome"], rows["_weight"]),
                               "players": len(rows)}), include_groups=False,
    ).reset_index(drop=True)


def smoothed_relationship(frame: pd.DataFrame, x: str) -> pd.DataFrame:
    """Local medians on overlapping x-neighborhoods; robust to extreme outcomes."""
    valid = eligible_weighted_rows(frame)
    valid = valid.loc[valid[x].notna() & valid["outcome"].notna()]
    weights = row_weights(valid).to_numpy()
    if len(valid) < 9 or valid[x].nunique() < 4:
        return pd.DataFrame(columns=[x, "outcome", "players"])
    x_values = valid[x].to_numpy(dtype=float)
    outcomes = valid["outcome"].to_numpy(dtype=float)
    neighbors = max(MIN_SUPPORT_PLAYERS, int(np.ceil(len(valid) * 0.3)))
    grid = np.unique(np.quantile(x_values, np.linspace(0.05, 0.95, 50)))
    medians = []
    for point in grid:
        nearby = np.argpartition(np.abs(x_values - point), neighbors - 1)[:neighbors]
        medians.append(weighted_quantile(pd.Series(outcomes[nearby]), pd.Series(weights[nearby])))
    kernel = np.array([1, 2, 3, 2, 1], dtype=float) / 9
    smoothed = np.convolve(np.pad(medians, (2, 2), mode="edge"), kernel, mode="valid")
    return pd.DataFrame({x: grid, "outcome": smoothed, "players": neighbors})


def champion_landscape_data(champions: pd.DataFrame, players: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    frame = champions.copy()
    growth_column = "climbing_efficiency" if "climbing_efficiency" in frame else "lp_per_game_lift_vs_tier"
    frame["outcome"] = frame[growth_column]
    if "mean_commitment" in frame:
        frame["specialization_axis"] = frame["mean_commitment"]
        return frame, "Mean champion mastery share in favoured periods"

    active = players.loc[players["active_primary_champion_name"].notna()].groupby(
        "active_primary_champion_name", observed=True
    ).apply(lambda rows: weighted_mean(rows["active_hhi"], row_weights(rows)), include_groups=False)
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
    frame = eligible_weighted_rows(players)
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
    if frame.empty:
        return pd.DataFrame(columns=[x_dimension, y_dimension, "mean_share", "player_count"])
    summary = frame.groupby([x_dimension, y_dimension], observed=True).agg(
        mean_share=("median_ranked_mastery_share", "mean"),
        player_count=("median_ranked_mastery_share", "size"),
    ).reset_index()
    frame["_weight"] = row_weights(frame)
    means = frame.groupby([x_dimension, y_dimension], observed=True).apply(
        lambda rows: weighted_mean(rows["median_ranked_mastery_share"], rows["_weight"]), include_groups=False,
    ).rename("weighted_mean").reset_index()
    summary = summary.merge(means, on=[x_dimension, y_dimension])
    summary["mean_share"] = summary.pop("weighted_mean")
    return summary.loc[summary["player_count"] >= minimum_players]


def specialization_trend(players: pd.DataFrame) -> dict[str, float]:
    """Linear association matching the champion's unfiltered player scatter."""
    valid = eligible_weighted_rows(players)
    valid = valid.loc[valid["champion_commitment"].notna() & valid["climbing_efficiency"].notna()].copy()
    if len(valid) < 3:
        return {"players": len(valid), "slope_per_10pp": np.nan, "correlation": np.nan, "r_squared": np.nan}
    weights = row_weights(valid)
    valid["x"] = valid["champion_commitment"] - weighted_mean(valid["champion_commitment"], weights)
    valid["y"] = valid["climbing_efficiency"] - weighted_mean(valid["climbing_efficiency"], weights)
    x = valid["x"].to_numpy(dtype=float)
    y = valid["y"].to_numpy(dtype=float)
    x_sum_squares = float(np.dot(weights * x, x))
    y_sum_squares = float(np.dot(weights * y, y))
    if x_sum_squares <= 0 or y_sum_squares <= 0:
        return {"players": len(valid), "slope_per_10pp": np.nan, "correlation": np.nan, "r_squared": np.nan}
    cross = float(np.dot(weights * x, y))
    correlation = cross / np.sqrt(x_sum_squares * y_sum_squares)
    return {
        "players": len(valid),
        "slope_per_10pp": 0.1 * (cross / x_sum_squares),
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
    frame = eligible_weighted_rows(players)
    frame = frame.loc[frame["starting_tier"].notna()].copy()
    frame["_weight"] = row_weights(frame)
    frame["favours_champion"] = frame["favoured_champions"].apply(
        lambda names: champion_name in names if isinstance(names, (list, tuple, np.ndarray)) else False
    )
    baseline = frame.groupby("starting_tier", observed=True).apply(
        lambda rows: weighted_mean(rows["median_ranked_mastery_share"], rows["_weight"]), include_groups=False,
    )
    champion = frame.loc[frame["favours_champion"]].groupby("starting_tier", observed=True).agg(
        share=("median_ranked_mastery_share", "mean"),
        players=("median_ranked_mastery_share", "size"),
    ).reset_index()
    means = frame.loc[frame["favours_champion"]].groupby("starting_tier", observed=True).apply(
        lambda rows: weighted_mean(rows["median_ranked_mastery_share"], rows["_weight"]), include_groups=False,
    )
    champion["share"] = champion["starting_tier"].map(means)
    champion["baseline_share"] = champion["starting_tier"].map(baseline)
    champion["difference_pp"] = 100 * (champion["share"] - champion["baseline_share"])
    return champion


def tier_population_comparison(players: pd.DataFrame, champion_name: str, basis: str) -> pd.DataFrame:
    """Compare primary-player tier membership with the tracked population."""
    frame = profile_basis(players, basis)
    frame = eligible_weighted_rows(frame.loc[frame["tier"].isin(TIER_ORDER)])
    frame["_weight"] = row_weights(frame)
    baseline = frame.groupby("tier").size().reindex(TIER_ORDER, fill_value=0)
    selected = frame.loc[frame["primary_champion_name"] == champion_name]
    counts = selected.groupby("tier").size().reindex(TIER_ORDER, fill_value=0)
    mass = frame.groupby("tier", observed=True)["_weight"].sum().reindex(TIER_ORDER, fill_value=0)
    champion_mass = selected.groupby("tier", observed=True)["_weight"].sum().reindex(TIER_ORDER, fill_value=0)
    total, champion_total = mass.sum(), champion_mass.sum()
    result = pd.DataFrame({"tier": TIER_ORDER, "all_players": baseline.to_numpy(), "champion_players": counts.to_numpy()})
    result["all_share"] = mass.to_numpy() / total if total else np.nan
    result["champion_share"] = champion_mass.to_numpy() / champion_total if champion_total else np.nan
    result["representation_ratio"] = result["champion_share"] / result["all_share"].replace(0, np.nan)
    return result


def champion_overlap_summary(pairs: pd.DataFrame, champion_name: str) -> dict[str, float]:
    """Conditional overlap from the selected champion's perspective, weighted by shared players."""
    support = "pair_player_count_mass" if "pair_player_count_mass" in pairs else "pair_player_count"
    left = pairs.loc[pairs["champion_name_a"] == champion_name, [support, "prob_b_given_a"]].rename(columns={support: "pair_player_count", "prob_b_given_a": "conditional"})
    right = pairs.loc[pairs["champion_name_b"] == champion_name, [support, "prob_a_given_b"]].rename(columns={support: "pair_player_count", "prob_a_given_b": "conditional"})
    frame = pd.concat([left, right]).dropna()
    if frame.empty or frame["pair_player_count"].sum() == 0:
        return {"conditional": np.nan, "pairs": 0}
    return {"conditional": float(np.average(frame["conditional"], weights=frame["pair_player_count"])), "pairs": len(frame)}


def mastery_representation_by_tier(tier_mastery: pd.DataFrame, minimum_mastery: int) -> pd.DataFrame:
    """Compare each champion's tier distribution of mastery points with the sample distribution."""
    frame = tier_mastery.loc[
        tier_mastery["minimum_mastery"].eq(minimum_mastery)
        & tier_mastery["tier"].isin(TIER_ORDER)
        & tier_mastery["player_count"].gt(0)
        & tier_mastery["mean_mastery"].gt(0)
    ].copy()
    if frame.empty:
        return frame

    frame = eligible_weighted_rows(frame)
    frame["mastery_points"] = frame["mean_mastery"] * frame["player_count"] * row_weights(frame)
    champion_totals = frame.groupby("champion_name", observed=True)["mastery_points"].transform("sum")
    tier_totals = frame.groupby("tier", observed=True)["mastery_points"].transform("sum")
    frame["champion_tier_share"] = frame["mastery_points"] / champion_totals
    frame["sample_tier_share"] = tier_totals / frame["mastery_points"].sum()
    frame["representation_ratio"] = frame["champion_tier_share"] / frame["sample_tier_share"]
    frame["log2_representation"] = np.log2(frame["representation_ratio"])

    holder_mass = frame["player_count"] * row_weights(frame)
    rank_weight = frame["mean_rank_score"] * holder_mass
    tier_rank = rank_weight.groupby(frame["tier"], observed=True).sum() / holder_mass.groupby(frame["tier"], observed=True).sum()
    frame["tier_rank_score"] = frame["tier"].map(tier_rank)
    frame["tier"] = pd.Categorical(frame["tier"], categories=TIER_ORDER, ordered=True)
    return frame.sort_values(["champion_name", "tier"])


def one_trick_tier_distribution(
    players: pd.DataFrame,
    tier_mastery: pd.DataFrame,
    minimum_mastery: int = 300_000,
    minimum_share: float = 0.8,
    minimum_hhi: float = 0.65,
    criterion: str = "Main share or HHI",
    mastery_column: str = "total_mastery_points",
) -> pd.DataFrame:
    """Player-count tier distributions of active mains versus all champion mastery holders.

    The baseline uses the unfiltered zero-threshold champion-holder counts, not
    mastery-point weights. All tier denominators are calculated before support filtering.
    """
    share_pass = players["active_top1_share"].ge(minimum_share)
    hhi_pass = players["active_hhi"].ge(minimum_hhi)
    concentration = share_pass if criterion == "Main share" else hhi_pass if criterion == "HHI" else share_pass | hhi_pass
    players = eligible_weighted_rows(players)
    mains = players.loc[
        concentration & players[mastery_column].ge(minimum_mastery)
        & players["active_primary_champion_name"].notna() & players["tier"].isin(TIER_ORDER)
    ]
    baseline = tier_mastery.loc[
        tier_mastery["minimum_mastery"].eq(0) & tier_mastery["tier"].isin(TIER_ORDER)
    ]
    columns = ["champion_name", "tier", "one_trick_players", "champion_players", "one_trick_total",
               "champion_total", "one_trick_share", "champion_share", "representation_ratio", "difference_pp"]
    if mains.empty or baseline.empty:
        return pd.DataFrame(columns=columns)
    names = sorted(set(mains["active_primary_champion_name"]) & set(baseline["champion_name"]))
    index = pd.MultiIndex.from_product([names, TIER_ORDER], names=["champion_name", "tier"])
    counts = mains.rename(columns={"active_primary_champion_name": "champion_name"}).groupby(
        ["champion_name", "tier"], observed=True,
    ).size().reindex(index, fill_value=0)
    holder_counts = baseline.groupby(["champion_name", "tier"], observed=True)["player_count"].sum().reindex(index, fill_value=0)
    result = pd.DataFrame({"one_trick_players": counts, "champion_players": holder_counts}).reset_index()
    result["one_trick_total"] = result.groupby("champion_name")["one_trick_players"].transform("sum")
    result["champion_total"] = result.groupby("champion_name")["champion_players"].transform("sum")
    mains = mains.assign(_weight=row_weights(mains)).rename(columns={"active_primary_champion_name": "champion_name"})
    main_mass = mains.groupby(["champion_name", "tier"], observed=True)["_weight"].sum().reindex(index, fill_value=0)
    baseline = baseline.assign(_mass=baseline["player_count"] * row_weights(baseline))
    holder_mass = baseline.groupby(["champion_name", "tier"], observed=True)["_mass"].sum().reindex(index, fill_value=0)
    result["one_trick_share"] = main_mass.to_numpy() / main_mass.groupby(level=0).transform("sum").replace(0, np.nan).to_numpy()
    result["champion_share"] = holder_mass.to_numpy() / holder_mass.groupby(level=0).transform("sum").replace(0, np.nan).to_numpy()
    result["representation_ratio"] = result["one_trick_share"] / result["champion_share"].replace(0, np.nan)
    result["difference_pp"] = 100 * (result["one_trick_share"] - result["champion_share"])
    result["tier"] = pd.Categorical(result["tier"], categories=TIER_ORDER, ordered=True)
    return result.sort_values(["champion_name", "tier"])


def expert_share_vs_sample(tier_mastery: pd.DataFrame, champion_name: str, minimum_mastery: int) -> pd.DataFrame:
    """Compare a champion's expert share with the pooled holder share in each tier."""
    frame = tier_mastery.loc[
        tier_mastery["minimum_mastery"].eq(minimum_mastery)
        & tier_mastery["tier"].isin(TIER_ORDER)
        & tier_mastery["player_count"].gt(0)
    ].copy()
    baseline = frame.groupby("tier", observed=True).agg(
        experts=("expert_player_count", "sum"), holders=("player_count", "sum")
    )
    baseline["sample_expert_share"] = baseline["experts"] / baseline["holders"]
    selected = frame.loc[frame["champion_name"].eq(champion_name)].copy()
    selected["expert_share"] = selected["expert_player_count"] / selected["player_count"]
    selected["sample_expert_share"] = selected["tier"].map(baseline["sample_expert_share"])
    selected["expert_share_difference_pct"] = 100 * (
        selected["expert_share"] / selected["sample_expert_share"].replace(0, np.nan) - 1
    )
    return selected


def playstyle_mastery_bands(players: pd.DataFrame, basis: str, minimum_mastery: int, bins: int = 8, tier: str | None = None) -> pd.DataFrame:
    frame = profile_basis(players, basis)
    if tier is not None:
        frame = frame.loc[frame["tier"] == tier]
    frame = frame.loc[(frame["total_mastery_points"] >= max(1, minimum_mastery)) & frame["playstyle"].isin(PLAYSTYLE_ORDER)].copy()
    if frame.empty or frame["total_mastery_points"].nunique() < 2:
        return pd.DataFrame(columns=["mastery", "log_mean_mastery", "playstyle", "players", "share"])
    frame["band"] = pd.qcut(frame["total_mastery_points"], q=min(bins, frame["total_mastery_points"].nunique()), duplicates="drop")
    frame["_weight"] = row_weights(frame)
    band_mastery = frame.groupby("band", observed=True).apply(
        lambda rows: pd.Series({
            "mastery": weighted_quantile(rows["total_mastery_points"], rows["_weight"]),
            "mean_mastery": weighted_mean(rows["total_mastery_points"], rows["_weight"]),
        }), include_groups=False,
    ).reset_index()
    grouped = frame.groupby(["band", "playstyle"], observed=True).agg(
        players=("_weight", "size"), weighted_mass=("_weight", "sum"),
    ).reset_index().merge(band_mastery, on="band", how="left")
    grouped["log_mean_mastery"] = np.log10(grouped["mean_mastery"].clip(lower=1))
    grouped["share"] = grouped["weighted_mass"] / grouped.groupby("band", observed=True)["weighted_mass"].transform("sum")
    return grouped
