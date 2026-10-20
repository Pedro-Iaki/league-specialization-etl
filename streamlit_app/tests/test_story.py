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
from app_core.experience import TIER_GROUPS, experience_bands, experience_focus_cells, experience_overall
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
        assert not app.selectbox  # the guided tour needs no analytical filter choices
        if number > 1:
            assert any(button.key == f"story_previous_{number}" for button in app.button)
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


def test_audience_presentation_preserves_counts_intervals_and_preferences():
    cells = experience_focus_cells(experience_bands(load_dataset("players")))
    overall = experience_overall(cells)
    app = AppTest.from_file(str(APP), default_timeout=45)
    app.session_state[LANGUAGE_KEY] = "EN"
    app.run()
    app.switch_page(STORY_PAGES[2][0]).run()
    baseline = None
    for language, terminology, title in [
        ("EN", "Plain", "Character focus separates audiences."),
        ("EN", "League", "Playstyles separate audiences."),
        ("PT", "League", "Os estilos de jogo diferenciam os públicos."),
        ("PT", "Plain", "O foco em personagens diferencia os públicos."),
    ]:
        previous_terminology = app.segmented_control(key="_story_terminology_choice").value
        app.segmented_control(key="_dashboard_language_choice").set_value(language).run()
        assert app.segmented_control(key="_story_terminology_choice").value == previous_terminology
        app.segmented_control(key="_story_terminology_choice").set_value(terminology).run()
        assert not app.exception
        assert any(title in item.value for item in app.markdown)
        assert app.session_state[LANGUAGE_KEY] == language
        assert app.session_state[TERMINOLOGY_KEY] == terminology
        charts = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
        bars, *panels, roles = charts
        assert len(panels) == len(PLAYSTYLE_ORDER)
        numeric = []
        for style, trace in zip(PLAYSTYLE_ORDER, bars["data"], strict=True):
            expected = overall.loc[overall["playstyle"].eq(style)]
            assert trace["type"] == "bar"
            assert trace["x"] == pytest.approx(expected["share"].tolist())
            assert trace["customdata"] == expected[["members", "n"]].to_numpy().tolist()
            numeric.append((trace["x"], trace["customdata"]))
        for style, panel in zip(PLAYSTYLE_ORDER, panels, strict=True):
            assert panel["layout"]["xaxis"]["tickvals"] == [0, 1, 2, 3]
            for band, trace in enumerate(panel["data"], 1):
                expected = cells.loc[cells["playstyle"].eq(style) & cells["mastery_band"].eq(band)]
                assert trace["y"] == pytest.approx(expected["share"].tolist())
                assert [row[:4] for row in trace["customdata"]] == expected[["members", "n", "lower", "upper"]].to_numpy().tolist()
                assert trace["error_y"]["array"] == pytest.approx((expected["upper"] - expected["share"]).tolist())
                assert trace["error_y"]["arrayminus"] == pytest.approx((expected["share"] - expected["lower"]).tolist())
                numeric.append((trace["x"], trace["y"], [row[:4] for row in trace["customdata"]]))
        numeric.append(roles["data"][0]["z"])
        if baseline is None:
            baseline = numeric
        assert numeric == baseline
        if terminology == "Plain":
            assert "Specialist" not in json.dumps(charts)
            assert "Specialist" not in " ".join(str(value) for frame in app.dataframe for value in frame.value.to_numpy().ravel())
        if language == "PT":
            assert bars["layout"]["xaxis"]["title"]["text"] == "Proporção de perfis"
            assert all("," in value for value in app.dataframe[1].value["Proporção de perfis"])
            assert any("600" in item.value and "30" in item.value and "1.200" in item.value for item in app.markdown)

    app.toggle(key="story_focus_intervals").set_value(True).run()
    assert not app.exception
    with_intervals = [json.loads(item.proto.spec) for item in app.get("plotly_chart")][1:5]
    for before, after in zip(panels, with_intervals, strict=True):
        for original, trace in zip(before["data"], after["data"], strict=True):
            assert trace["y"] == original["y"]
            assert trace["error_y"]["visible"] is True

    app.toggle(key="story_focus_bands_on_x").set_value(True).run()
    assert not app.exception
    inverted = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
    assert inverted[0]["data"] == charts[0]["data"]
    assert inverted[-1]["data"] == charts[-1]["data"]
    for style, before, panel in zip(PLAYSTYLE_ORDER, with_intervals, inverted[1:5], strict=True):
        assert panel["layout"]["xaxis"]["tickvals"] == [1, 2, 3, 4, 5]
        assert panel["layout"]["xaxis"]["title"]["text"].startswith("Faixa de atividade")
        assert panel["layout"]["yaxis"]["range"] == before["layout"]["yaxis"]["range"]
        for rank, trace in zip(TIER_GROUPS, panel["data"], strict=True):
            expected = cells.loc[cells["playstyle"].eq(style) & cells["tier_group"].eq(rank)]
            assert trace["y"] == pytest.approx(expected["share"].tolist())
            assert [row[:4] for row in trace["customdata"]] == expected[["members", "n", "lower", "upper"]].to_numpy().tolist()
            assert trace["error_y"]["visible"] is True
            assert trace["error_y"]["array"] == pytest.approx((expected["upper"] - expected["share"]).tolist())

    app.segmented_control(key="_story_terminology_choice").set_value("League").run()
    assert app.toggle(key="story_focus_bands_on_x").value is True
    assert "maestria" in json.loads(app.get("plotly_chart")[1].proto.spec)["layout"]["xaxis"]["title"]["text"]
    app.segmented_control(key="_dashboard_language_choice").set_value("EN").run()
    assert app.toggle(key="story_focus_bands_on_x").value is True
    app.toggle(key="story_focus_bands_on_x").set_value(False).run()
    assert not app.exception
    assert len(json.loads(app.get("plotly_chart")[1].proto.spec)["data"]) == 5
    app.segmented_control(key="_dashboard_language_choice").set_value("PT").run()
    app.button(key="story_previous_3").click().run()
    assert not app.exception
    assert any(button.key == "story_next_2" for button in app.button)
    app.switch_page(STORY_PAGES[1][0]).run()
    app.button(key="story_next_2").click().run()
    assert app.segmented_control(key="_story_terminology_choice").value == "League"
    assert app.session_state[LANGUAGE_KEY] == "PT"


@pytest.mark.parametrize("size", [0, 2])
def test_audience_sparse_snapshot_keeps_counts_methods_and_navigation(size):
    players = load_dataset("players").head(size)
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_dataset", return_value=players):
        app.switch_page(STORY_PAGES[2][0]).run()
    assert not app.exception
    assert any("too few classified profiles" in item.value for item in app.info)
    assert not app.get("plotly_chart")
    assert app.dataframe[0].value["Profiles in focus group"].sum() == size
    assert app.dataframe[1].value["Profiles in focus group"].sum() == size
    assert app.dataframe[1].value["Share of profiles"].eq("Not shown").all()
    assert len(app.expander) == 3
    assert app.button(key="story_previous_3")
    assert app.button(key="story_next_3")


def test_audience_pools_sparse_bands_and_retains_zero_without_connecting_gaps():
    players = load_dataset("players").head(25).copy()
    players["tier"] = (["IRON"] * 3 + ["GOLD"] * 2) * 5
    players["lifetime_playstyle"] = (["generalist"] * 3 + ["specialist"] * 2) * 5
    players["lifetime_mastery_points"] = range(25)
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch("app_core.story.load_dataset", return_value=players):
        app.switch_page(STORY_PAGES[2][0]).run()
    assert not app.exception
    charts = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
    assert charts[0]["data"][0]["x"][1] == 1
    assert charts[0]["layout"]["xaxis"]["range"] == [0, 1]
    for panel in charts[1:5]:
        for trace in panel["data"]:
            assert trace["y"][1] is None
            assert trace["connectgaps"] is False
    assert charts[1]["data"][0]["y"][0] == 0
    assert charts[4]["layout"]["yaxis"]["range"] == [0, 1]


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
