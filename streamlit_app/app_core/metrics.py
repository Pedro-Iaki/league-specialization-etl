from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from app_core.config import PLAYSTYLE_ORDER, ROLE_ORDER, TIER_ORDER


def classified_players(players: pd.DataFrame) -> pd.DataFrame:
    """Return players with an active-pool classification."""
    return players.loc[players["active_playstyle"].isin(PLAYSTYLE_ORDER)].copy()


def player_coverage(players: pd.DataFrame) -> dict[str, float | int]:
    total = len(players)
    classified = int(players["active_playstyle"].notna().sum())
    recent = int(players["lp_per_game_recent"].notna().sum())
    role_inferred = int(players["main_role"].notna().sum())
    return {
        "players": total,
        "classified": classified,
        "classified_pct": classified / total if total else 0.0,
        "recent_form": recent,
        "recent_form_pct": recent / total if total else 0.0,
        "role_inferred": role_inferred,
        "role_inferred_pct": role_inferred / total if total else 0.0,
    }


def playstyle_tier_composition(players: pd.DataFrame) -> pd.DataFrame:
    frame = classified_players(players)
    grouped = frame.groupby(["tier", "active_playstyle"], observed=True).size().rename("players").reset_index()
    grouped["share"] = grouped["players"] / grouped.groupby("tier")["players"].transform("sum")
    grouped["tier"] = pd.Categorical(grouped["tier"], categories=TIER_ORDER, ordered=True)
    grouped["active_playstyle"] = pd.Categorical(grouped["active_playstyle"], categories=PLAYSTYLE_ORDER, ordered=True)
    return grouped.sort_values(["tier", "active_playstyle"]).reset_index(drop=True)


def active_alltime_transition(players: pd.DataFrame, normalize: bool = True) -> pd.DataFrame:
    frame = players.loc[
        players["active_playstyle"].isin(PLAYSTYLE_ORDER) & players["alltime_playstyle"].isin(PLAYSTYLE_ORDER),
        ["active_playstyle", "alltime_playstyle"],
    ]
    matrix = pd.crosstab(frame["active_playstyle"], frame["alltime_playstyle"])
    matrix = matrix.reindex(index=PLAYSTYLE_ORDER, columns=PLAYSTYLE_ORDER, fill_value=0)
    if normalize:
        denominator = matrix.sum(axis=1).replace(0, np.nan)
        matrix = matrix.div(denominator, axis=0)
    return matrix


def role_playstyle_difference(players: pd.DataFrame) -> pd.DataFrame:
    """Percentage-point difference between each role and the classified population."""
    frame = classified_players(players)
    frame = frame.loc[frame["main_role"].isin(ROLE_ORDER)]
    counts = pd.crosstab(frame["main_role"], frame["active_playstyle"])
    counts = counts.reindex(index=ROLE_ORDER, columns=PLAYSTYLE_ORDER, fill_value=0)
    within_role = counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0)
    overall = frame["active_playstyle"].value_counts(normalize=True).reindex(PLAYSTYLE_ORDER, fill_value=0)
    return (within_role.subtract(overall, axis=1) * 100).fillna(0)


def filter_players(
    players: pd.DataFrame,
    tiers: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    minimum_tracking_days: int = 0,
) -> pd.DataFrame:
    frame = players.copy()
    if tiers:
        frame = frame.loc[frame["tier"].isin(tiers)]
    if roles:
        frame = frame.loc[frame["main_role"].isin(roles)]
    if "days_tracked" in frame and minimum_tracking_days:
        frame = frame.loc[frame["days_tracked"].fillna(0) >= minimum_tracking_days]
    return frame


def weighted_growth_summary(
    growth: pd.DataFrame,
    group_columns: Sequence[str],
) -> pd.DataFrame:
    """Aggregate interval outcomes without averaging pre-computed rates."""
    frame = growth.loc[growth["games_delta"].fillna(0) > 0].copy()
    frame["lift_games"] = frame["lp_per_game_lift_vs_tier"] * frame["games_delta"]
    frame["lift_observed_games"] = np.where(frame["lp_per_game_lift_vs_tier"].notna(), frame["games_delta"], 0)
    grouped = frame.groupby(list(group_columns), dropna=False, observed=True)
    result = grouped.agg(
        intervals=("games_delta", "size"),
        observed_games=("games_delta", "sum"),
        wins=("wins_delta", "sum"),
        lp_delta=("lp_delta", "sum"),
        lift_games=("lift_games", "sum"),
        lift_observed_games=("lift_observed_games", "sum"),
    ).reset_index()
    result["observed_win_rate"] = result["wins"] / result["observed_games"]
    result["expected_lp_per_game"] = result["lp_delta"] / result["observed_games"]
    result["lp_per_game_lift_vs_tier"] = result["lift_games"] / result["lift_observed_games"].replace(0, np.nan)
    return result


def champion_playstyle_growth(
    growth: pd.DataFrame,
    minimum_games: int,
    top_n_champions: int = 20,
) -> pd.DataFrame:
    frame = growth.loc[growth["primary_champion_name"].notna() & growth["playstyle"].isin(PLAYSTYLE_ORDER)]
    summary = weighted_growth_summary(frame, ["primary_champion_name", "playstyle"])
    champion_games = summary.groupby("primary_champion_name")["observed_games"].sum()
    top_champions = champion_games.nlargest(top_n_champions).index
    return summary.loc[
        summary["primary_champion_name"].isin(top_champions) & (summary["observed_games"] >= minimum_games)
    ].copy()


def champion_neighbors(
    cooccurrence: pd.DataFrame,
    champion_name: str,
    minimum_players: int = 100,
) -> pd.DataFrame:
    left = cooccurrence.loc[cooccurrence["champion_name_a"] == champion_name].copy()
    left["related_champion"] = left["champion_name_b"]
    left["conditional_probability"] = left["prob_b_given_a"]

    right = cooccurrence.loc[cooccurrence["champion_name_b"] == champion_name].copy()
    right["related_champion"] = right["champion_name_a"]
    right["conditional_probability"] = right["prob_a_given_b"]

    combined = pd.concat([left, right], ignore_index=True)
    combined = combined.loc[combined["pair_player_count"] >= minimum_players]
    return combined.sort_values(["npmi", "pair_player_count"], ascending=False).reset_index(drop=True)


def safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else float("nan")
