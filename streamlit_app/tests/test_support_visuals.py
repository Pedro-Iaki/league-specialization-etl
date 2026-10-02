from __future__ import annotations

import numpy as np
import pandas as pd
from app_core.analysis import role_playstyle_skew, smoothed_relationship
from app_core.charts import (
    champion_tier_outcome_heatmap,
    ranked_share_heatmap,
    role_difference_heatmap,
    specialization_relationship_chart,
    transition_heatmap,
)
from app_core.config import MIN_SUPPORT_PLAYERS
from app_core.metrics import active_alltime_transition


def test_role_heatmap_distinguishes_missing_support_from_zero_difference() -> None:
    players = pd.DataFrame({
        "active_playstyle": ["specialist", "specialist", "specialist", "generalist", "generalist"],
        "main_role": ["Top", "Top", "Top", "Middle", "Middle"],
        "active_hhi": [0.5] * 5,
        "active_top1_share": [0.5] * 5,
        "active_normalized_entropy": [0.5] * 5,
        "active_primary_champion_name": ["Ahri"] * 5,
    })
    result = role_playstyle_skew(players, "Active (60 days)")
    counts = result.attrs["support_counts"]
    assert counts.loc["Top", "specialist"] == MIN_SUPPORT_PLAYERS
    assert result.loc["Top", "generalist"] == -40
    assert pd.isna(result.loc["Middle", "generalist"])
    assert pd.isna(result.loc["Jungle", "specialist"])

    chart = role_difference_heatmap(result)
    assert np.isnan(chart.data[0].z[2][3])
    assert any(label.text == "n<3" for label in chart.layout.annotations)
    assert any(label.text == "—" for label in chart.layout.annotations)
    result.attrs["show_sparse"] = True
    revealed = role_difference_heatmap(result)
    assert revealed.data[0].z[2][3] == 60
    assert "n=2" in revealed.data[0].text[2][3]


def test_ranked_share_heatmap_mutes_thin_cell_but_keeps_count() -> None:
    summary = pd.DataFrame({
        "Tier": ["GOLD", "SILVER"],
        "Role": ["Middle", "Middle"],
        "mean_share": [0.9, 0.4],
        "player_count": [2, 3],
    })
    chart = ranked_share_heatmap(summary, "Tier", "Role")
    assert np.isnan(chart.data[0].z[0][1])
    assert chart.data[0].z[0][0] == 0.4
    assert any(label.text == "n<3" and label.x == "GOLD" for label in chart.layout.annotations)
    assert "n=3" in chart.data[0].text[0][0]
    summary.attrs["show_sparse"] = True
    revealed = ranked_share_heatmap(summary, "Tier", "Role")
    assert revealed.data[0].z[0][1] == 0.9
    assert "n=2" in revealed.data[0].text[0][1]


def test_transition_heatmap_keeps_measured_zero_in_supported_row() -> None:
    players = pd.DataFrame({
        "active_playstyle": ["specialist"] * 3 + ["generalist"],
        "alltime_playstyle": ["specialist"] * 3 + ["generalist"],
    })
    matrix = active_alltime_transition(players)
    matrix.attrs["support_counts"] = active_alltime_transition(players, normalize=False)
    chart = transition_heatmap(matrix)
    assert chart.data[0].z[0][3] == 0
    assert "n=0" in chart.data[0].text[0][3]
    assert np.isnan(chart.data[0].z[3][3])
    matrix.attrs["show_sparse"] = True
    revealed = transition_heatmap(matrix)
    assert revealed.data[0].z[3][3] == 1
    assert "n=1" in revealed.data[0].text[3][3]


def test_champion_tier_heatmap_reveals_low_support_cell_on_request() -> None:
    styles = pd.DataFrame({
        "starting_tier": ["GOLD"],
        "playstyle": ["specialist"],
        "observed_player_count": [2],
        "climbing_efficiency": [2.0],
    })
    baseline = pd.DataFrame({"starting_tier": ["GOLD"], "climbing_efficiency": [1.0]})
    hidden = champion_tier_outcome_heatmap(styles, baseline, "climbing_efficiency", False)
    assert np.isnan(hidden.data[0].z[0][0])
    styles.attrs["show_sparse"] = True
    revealed = champion_tier_outcome_heatmap(styles, baseline, "climbing_efficiency", False)
    assert revealed.data[0].z[0][0] == 2.0
    assert "n=2" in revealed.data[0].text[0][0]


def test_optional_local_median_resists_one_extreme_outcome() -> None:
    frame = pd.DataFrame({
        "specialization_hhi": np.linspace(0.1, 0.9, 30),
        "outcome": [1.0] * 29 + [1000.0],
        "tier": ["GOLD"] * 30,
    })
    smooth = smoothed_relationship(frame, "specialization_hhi")
    assert not smooth.empty
    assert smooth["outcome"].max() < 10

    chart = specialization_relationship_chart(
        frame, "specialization_hhi", "Pool concentration (HHI)", "LP/game", trend=None
    )
    trend = next(trace for trace in chart.data if trace.name == "Smoothed local median (optional)")
    assert trend.visible == "legendonly"
    assert np.max(trend.y) < 10
