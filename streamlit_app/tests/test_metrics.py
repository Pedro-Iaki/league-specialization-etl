from __future__ import annotations

import pandas as pd
import pytest
from app_core.metrics import (
    active_alltime_transition,
    playstyle_tier_composition,
    role_playstyle_difference,
    weighted_growth_summary,
)


def test_playstyle_tier_composition_sums_to_one() -> None:
    players = pd.DataFrame(
        {
            "tier": ["GOLD", "GOLD", "GOLD", "SILVER"],
            "active_playstyle": ["specialist", "generalist", None, "versatile"],
        }
    )

    result = playstyle_tier_composition(players)
    tier_totals = result.groupby("tier", observed=True)["share"].sum()

    assert tier_totals.loc["GOLD"] == pytest.approx(1.0)
    assert tier_totals.loc["SILVER"] == pytest.approx(1.0)
    assert result.loc[result["tier"] == "GOLD", "players"].sum() == 2


def test_weighted_growth_uses_summed_outcomes() -> None:
    growth = pd.DataFrame(
        {
            "playstyle": ["specialist", "specialist"],
            "games_delta": [1, 9],
            "wins_delta": [1, 3],
            "lp_delta": [20, 0],
            "lp_per_game_lift_vs_tier": [10.0, -2.0],
        }
    )

    result = weighted_growth_summary(growth, ["playstyle"]).iloc[0]

    assert result["observed_games"] == 10
    assert result["observed_win_rate"] == pytest.approx(0.4)
    assert result["expected_lp_per_game"] == pytest.approx(2.0)
    assert result["lp_per_game_lift_vs_tier"] == pytest.approx(-0.8)


def test_active_alltime_transition_normalizes_rows() -> None:
    players = pd.DataFrame(
        {
            "active_playstyle": ["specialist", "specialist", "generalist", None],
            "alltime_playstyle": ["specialist", "generalist", "generalist", "specialist"],
        }
    )

    matrix = active_alltime_transition(players)

    assert matrix.loc["specialist"].sum() == pytest.approx(1.0)
    assert matrix.loc["specialist", "specialist"] == pytest.approx(0.5)
    assert matrix.loc["specialist", "generalist"] == pytest.approx(0.5)


def test_role_difference_is_percentage_point_difference() -> None:
    players = pd.DataFrame(
        {
            "active_playstyle": ["specialist", "specialist", "generalist", "generalist"],
            "main_role": ["Top", "Top", "Middle", "Middle"],
        }
    )

    result = role_playstyle_difference(players)

    assert result.loc["Top", "specialist"] == pytest.approx(50.0)
    assert result.loc["Middle", "specialist"] == pytest.approx(-50.0)
