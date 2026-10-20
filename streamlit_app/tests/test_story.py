from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app_core.config import PLAYSTYLE_ORDER
from app_core.data import DashboardDataError, load_dataset
from app_core.experience import TIER_GROUPS
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
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
    for number in range(1, len(STORY_PAGES) + 1):
        assert not app.exception
        assert app.session_state[LANGUAGE_KEY] == language
        assert len(app.selectbox) == (1 if number == 4 else 0)
        if number > 1:
            assert any(button.key == f"story_previous_{number}" for button in app.button)
        next(button for button in app.button if button.key == f"story_next_{number}").click().run()
        following = number % 6 + 1
        assert any(button.key == f"story_next_{following}" for button in app.button)
        # AppTest does not persist a page selected by st.switch_page into its next
        # widget request. Keep its requested page in sync with the rendered page.
        app.switch_page(STORY_PAGES[following - 1][0])
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    app.switch_page("overview.py").run()
    assert not app.exception
    assert any(widget.value == "Recent activity" for widget in app.selectbox)


def test_audience_presentation_preserves_paired_values_and_preferences():
    from app_core.audience import WINDOWS, concentration_cells, load_reference, prepare_audience

    banded = prepare_audience(load_dataset("players", include_all_tiers=True), load_reference())
    cells = concentration_cells(banded)
    app = AppTest.from_file(str(APP), default_timeout=45)
    app.session_state[LANGUAGE_KEY] = "EN"
    app.run()
    app.switch_page(STORY_PAGES[2][0]).run()
    baseline = None
    for language, terminology, title in [
        ("EN", "Plain", "Rank differences need activity context."),
        ("EN", "League", "Tier differences need mastery context."),
        ("PT", "League", "Diferenças entre elos precisam de contexto de maestria."),
        ("PT", "Plain", "Diferenças de classificação precisam de contexto de atividade."),
    ]:
        app.segmented_control(key="_dashboard_language_choice").set_value(language).run()
        app.segmented_control(key="_story_terminology_choice").set_value(terminology).run()
        assert not app.exception
        assert any(title in item.value for item in app.markdown)
        assert app.session_state[LANGUAGE_KEY] == language
        assert app.session_state[TERMINOLOGY_KEY] == terminology
        charts = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
        assert sum(charts[0]["data"][0]["x"]) == len(banded)
        assert sum(sum(row) for row in charts[1]["data"][0]["z"]) == len(banded)
        values = []
        for (window, _), chart in zip(WINDOWS.items(), charts[2:4], strict=True):
            assert chart["layout"]["yaxis"]["range"] == [0, 1]
            for rank, trace in zip(TIER_GROUPS, chart["data"], strict=True):
                expected = cells.loc[cells.window.eq(window) & cells.rank_group.eq(rank)]
                assert trace["y"] == pytest.approx(expected["median"].tolist())
                assert [row[:4] for row in trace["customdata"]] == expected[
                    ["n", "q1", "q3", "median_hhi"]
                ].to_numpy().tolist()
                values.append((trace["y"], [row[:4] for row in trace["customdata"]]))
        assert sum(sum(sum(row) for row in trace["z"]) for trace in charts[4]["data"]) == len(banded)
        values.append([trace["z"] for trace in charts[4]["data"]])
        if baseline is None:
            baseline = values
        assert values == baseline
        assert "Unknown role" not in json.dumps(charts)
        if terminology == "Plain":
            assert "Specialist" not in json.dumps(charts)
        if language == "PT":
            assert charts[2]["layout"]["yaxis"]["title"]["text"] == (
                "Proporção do campeão principal" if terminology == "League" else "Proporção do personagem principal"
            )
            assert any("1.200" in x.value for x in app.caption)

    original = charts[2:4]
    app.toggle(key="story_concentration_quartiles").set_value(True).run()
    quartiles = [json.loads(item.proto.spec) for item in app.get("plotly_chart")][2:4]
    for before, after in zip(original, quartiles, strict=True):
        for old, trace in zip(before["data"], after["data"], strict=True):
            assert trace["y"] == old["y"] and trace["error_y"]["visible"] is True
    app.toggle(key="story_focus_bands_on_x").set_value(False).run()
    inverted = [json.loads(item.proto.spec) for item in app.get("plotly_chart")][2:4]
    for before, after in zip(quartiles, inverted, strict=True):
        assert len(after["data"]) == 5
        for rank, rank_trace in enumerate(before["data"]):
            for band, band_trace in enumerate(after["data"]):
                assert rank_trace["y"][band] == band_trace["y"][rank]
                assert rank_trace["customdata"][band][:4] == band_trace["customdata"][rank][:4]
    app.radio(key="story_audience_map_window").set_value("lifetime").run()
    changed = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
    assert changed[2:4] == inverted
    assert changed[4]["layout"]["coloraxis"]["cmax"] == charts[4]["layout"]["coloraxis"]["cmax"]
    assert sum(sum(sum(row) for row in trace["z"]) for trace in changed[4]["data"]) == len(banded)
    app.button(key="story_previous_3").click().run()
    assert not app.exception
    app.switch_page(STORY_PAGES[1][0]).run()
    app.button(key="story_next_2").click().run()
    assert app.segmented_control(key="_story_terminology_choice").value == "Plain"
    assert app.session_state[LANGUAGE_KEY] == "PT"


@pytest.mark.parametrize("size", [0, 2])
def test_audience_mismatched_snapshot_keeps_navigation(size):
    players = load_dataset("players", include_all_tiers=True).head(size)
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_dataset", return_value=players):
        app.switch_page(STORY_PAGES[2][0]).run()
    assert not app.exception
    assert any("unavailable for the current snapshot" in item.value for item in app.info)
    assert not app.get("plotly_chart")
    assert app.button(key="story_previous_3") and app.button(key="story_next_3")


@pytest.mark.parametrize("number", [2, 3, 4])
def test_audience_missing_reference_does_not_invent_new_bands(number):
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_audience_reference", side_effect=DashboardDataError("reference mismatch")):
        app.switch_page(STORY_PAGES[number - 1][0]).run()
    assert not app.exception
    assert not app.get("plotly_chart")
    assert any("reference mismatch" in item.value for item in app.code)
    assert app.button(key=f"story_next_{number}")


def test_older_snapshot_without_growth_keeps_story_navigation():
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_optional_dataset", return_value=None):
        app.switch_page(STORY_PAGES[5][0]).run()
        assert not app.exception
        assert any("no observed-period growth extract" in item.value for item in app.info)
        next(button for button in app.button if button.key == "story_next_6").click().run()
        assert not app.exception
        assert len(app.get("plotly_chart")) == 1


def test_invalid_growth_snapshot_shows_the_existing_load_error():
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_optional_dataset", side_effect=DashboardDataError("missing growth columns")):
        app.switch_page(STORY_PAGES[5][0]).run()
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
