from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app_core.config import PLAYSTYLE_ORDER
from app_core.data import DashboardDataError
from app_core.i18n import LANGUAGE_KEY
from app_core.story import STORY_PAGES
from app_core.story_analysis import (
    CASE_TIER_ORDER, champion_case_comparison, coverage_counts, detectable_gap, growth_uncertainty,
)

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.mark.parametrize("language", ["EN", "PT"])
def test_story_next_buttons_complete_the_tour_and_keep_language(language):
    app = AppTest.from_file(str(APP), default_timeout=45)
    app.session_state[LANGUAGE_KEY] = language
    app.run()
    for number, charts in enumerate([2, 0, 3, 2, 2, 0], 1):
        assert not app.exception
        assert len(app.get("plotly_chart")) == charts
        assert app.session_state[LANGUAGE_KEY] == language
        assert not app.selectbox  # the guided tour needs no analytical filter choices
        next(button for button in app.button if button.key == f"story_next_{number}").click().run()
        following = number % 6 + 1
        assert any(button.key == f"story_next_{following}" for button in app.button)
        # AppTest does not persist a page selected by st.switch_page into its next
        # widget request. Keep its requested page in sync with the rendered page.
        app.switch_page(STORY_PAGES[following - 1][0])
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    app.switch_page("overview.py").run()
    assert not app.exception
    assert any(widget.value == "Recent activity" for widget in app.selectbox)


def test_older_snapshot_without_growth_keeps_story_navigation():
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_optional_dataset", return_value=None):
        app.switch_page(STORY_PAGES[3][0]).run()
        assert not app.exception
        assert any("no observed-period growth extract" in item.value for item in app.info)
        next(button for button in app.button if button.key == "story_next_4").click().run()
        assert not app.exception
        assert len(app.get("plotly_chart")) == 2


def test_invalid_growth_snapshot_shows_the_existing_load_error():
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_optional_dataset", side_effect=DashboardDataError("missing growth columns")):
        app.switch_page(STORY_PAGES[3][0]).run()
    assert not app.exception
    assert any("could not be loaded" in item.value for item in app.error)


def test_bootstrap_uses_observed_outcomes_and_retains_sparse_groups():
    growth = pd.DataFrame({
        "rank_period_playstyle": ["specialist"] * 5 + ["multispecialist"] * 4 + ["versatile"] * 2,
        "games": [1, 2, 3, 0, 2] + [1] * 6,
        "climbing_efficiency": [-2, 0, 2, 999, np.inf] + [5] * 4 + [-1, 1],
    })
    first = growth_uncertainty(growth)
    pd.testing.assert_frame_equal(first, growth_uncertainty(growth))
    summary = first.set_index("playstyle")
    assert list(summary.index) == PLAYSTYLE_ORDER
    assert summary.loc["specialist", "observations"] == 3
    assert summary.loc["specialist", "mean"] == 0
    assert summary.loc["specialist", "low"] < 0 < summary.loc["specialist", "high"]
    assert summary.loc["multispecialist", ["mean", "low", "high"]].eq(5).all()
    assert summary.loc["versatile", ["low", "high"]].isna().all()
    assert summary.loc["generalist", "observations"] == 0
    assert summary.loc["generalist", ["mean", "low", "high"]].isna().all()
    gap = detectable_gap(first, np.array([100, 400]))
    assert gap[0] == pytest.approx(2 * gap[1])
    doubled = first.assign(sample_sd=first["sample_sd"] * 2)
    assert np.allclose(detectable_gap(doubled, np.array([100, 400])), gap * 2)


def test_champion_cases_pool_counts_and_keep_holders_without_one_tricks():
    players = pd.DataFrame({
        "tier": ["IRON", "DIAMOND", "MASTER", "GOLD", "GOLD"],
        "recent_primary_champion_name": ["Teemo", "Riven", "Riven", "Ahri", "Teemo"],
        "lifetime_mastery_points": [300_000] * 4 + [299_999],
        "recent_top1_share": [.8, .5, .9, .9, .9],
        "recent_hhi": [.1, .65, .8, .8, .8],
        "population_weight": [100, 1, 1, 1, 1],  # story shares count observations equally
    })
    holders = pd.DataFrame({
        "champion_name": ["Teemo", "Mordekaiser", "Riven", "Riven", "Ahri", "Teemo"],
        "tier": ["IRON", "GOLD", "DIAMOND", "MASTER", "GOLD", "IRON"],
        "minimum_mastery": [0] * 5 + [10_000],
        "player_count": [10, 30, 15, 5, 40, 999],
    })
    result = champion_case_comparison(players, holders)
    for _, group in result.groupby(["group", "series"]):
        assert group["share"].sum() == pytest.approx(1)
        assert group["players"].sum() == group["total"].iloc[0]
        assert group["tier"].tolist() == CASE_TIER_ORDER
    case_a = result.loc[result["group"].eq("Case group A")]
    assert case_a.loc[case_a["series"].eq("One-tricks"), "total"].eq(1).all()
    assert case_a.loc[case_a["series"].eq("Champion holders"), "total"].eq(40).all()
    all_mains = case_a.loc[case_a["series"].eq("All-champion one-tricks")].set_index("tier")
    assert all_mains.loc["Diamond+", "share"] == .5
    assert all_mains.loc["GOLD", "share"] == .25


def test_coverage_distinguishes_follow_up_from_usable_outcomes():
    players = pd.DataFrame({"latest_rank_period_games": [np.nan, 1, 2, 4, 3],
                            "latest_rank_period_lp_per_game": [np.nan, 5, 0, np.inf, -2]})
    coverage = coverage_counts(players, None).set_index("stage")
    assert "Complete core context" not in coverage.index
    assert coverage.loc["Current profiles", "players"] == 5
    assert coverage.loc["Rank-period follow-up", "players"] == 4
    assert coverage.loc["Usable recent-week LP outcome", "players"] == 2
