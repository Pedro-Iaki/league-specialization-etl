"""Shared audience identity, localization and character selection across chapters."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app_core.audience import (
    WINDOWS, band_distributions, leader_states, load_reference, overview_grid, prepare_audience,
)
from app_core.data import DashboardDataError, load_dataset
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
from app_core.story import STORY_PAGES

APP = Path(__file__).resolve().parents[1] / "app.py"


def charts(app):
    return [json.loads(item.proto.spec) for item in app.get("plotly_chart")]


def map_count(chart):
    return sum(sum(sum(row) for row in trace["z"]) for trace in chart["data"])


@pytest.mark.parametrize("language,terminology", [("EN", "Plain"), ("EN", "League"), ("PT", "Plain"), ("PT", "League")])
def test_chapters_share_cohort_and_preserve_values_in_both_languages_and_terminologies(language, terminology):
    players = load_dataset("players", include_all_tiers=True)
    banded = prepare_audience(players, load_reference())
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.session_state[LANGUAGE_KEY] = language
    app.session_state[TERMINOLOGY_KEY] = terminology
    app.run()
    assert not app.exception
    assert [int(metric.value.replace(",", "").replace(".", "")) for metric in app.metric] == [len(players), len(banded), 24990]
    assert sum(charts(app)[0]["data"][0]["y"]) == len(players)
    app.switch_page(STORY_PAGES[1][0]).run()
    assert not app.exception
    specs = charts(app)
    assert len(specs) == 5
    summary = band_distributions(banded)
    for index, window in enumerate(WINDOWS):
        box = specs[index]["data"][0]
        expected = summary.loc[summary.window.eq(window)]
        assert box["median"] == pytest.approx(expected["median"].to_list())
        assert box["lowerfence"] == pytest.approx(expected.p10.to_list())
        assert box["upperfence"] == pytest.approx(expected.p90.to_list())
        assert specs[index]["layout"]["xaxis"]["range"] == [0, 1]
        overview = specs[index + 3]
        assert map_count(overview) == len(banded)
        assert overview["data"][0]["z"] == overview_grid(banded, window).pivot(
            index="activity_band", columns="focus_bin", values="profiles"
        ).to_numpy().tolist()
    assert specs[3]["data"][0]["zmax"] == specs[4]["data"][0]["zmax"]
    app.switch_page(STORY_PAGES[3][0]).run()
    assert not app.exception
    specs = charts(app)
    assert sum(specs[0]["data"][0]["x"]) == len(banded)
    assert specs[0]["data"][0]["y"] == list("ABCDE")
    assert [metric.value for metric in app.metric] == (["18.629", "1.093", "0"] if language == "PT" else ["18,629", "1,093", "0"])
    assert map_count(specs[-1]) == len(banded)
    assert app.session_state[LANGUAGE_KEY] == language
    assert app.session_state[TERMINOLOGY_KEY] == terminology
    if language == "PT":
        assert any("Interesses em personagens tornam" in item.value for item in app.markdown)
        assert "Perfis" in specs[0]["data"][0]["hovertemplate"]
        assert specs[0]["data"][0]["text"][0] == "4.308 · 21,8%"
        assert app.selectbox(key="story_character_audience").label == "Recorte do público"


def test_character_map_selections_keep_reference_bins_and_count_scale():
    banded = prepare_audience(load_dataset("players", include_all_tiers=True), load_reference())
    states = leader_states(banded)
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.switch_page(STORY_PAGES[3][0]).run()
    baseline = charts(app)[-1]
    for selected, n in [("qualified", 18629), ("below", 1093), (157, 663), ("all", 19722)]:
        app.selectbox(key="story_character_audience").set_value(selected).run()
        assert not app.exception
        chart = charts(app)[-1]
        assert map_count(chart) == n
        assert chart["layout"]["coloraxis"] == baseline["layout"]["coloraxis"]
        if selected == "below":
            expected = banded.loc[states.eq("below")]
            for trace, rank in zip(chart["data"], ["Iron-Silver", "Gold-Platinum", "Emerald", "Diamond+"], strict=True):
                assert sum(sum(row) for row in trace["z"]) == expected.rank_group.eq(rank).sum()
    app.radio(key="story_character_map_window").set_value("lifetime").run()
    assert not app.exception
    assert map_count(charts(app)[-1]) == 19722
    assert charts(app)[-1]["layout"]["coloraxis"] == baseline["layout"]["coloraxis"]


def test_missing_overlap_keeps_character_reference_and_navigation():
    original = load_dataset

    def without_pairs(name, **kwargs):
        if name == "cooccurrence":
            raise DashboardDataError("missing pair file")
        return original(name, **kwargs)

    app = AppTest.from_file(str(APP), default_timeout=60).run()
    with patch("app_core.story.load_dataset", side_effect=without_pairs):
        app.switch_page(STORY_PAGES[3][0]).run()
    assert not app.exception
    assert any("overlap is unavailable" in info.value for info in app.info)
    assert map_count(charts(app)[-1]) == 19722
    assert app.button(key="story_previous_4") and app.button(key="story_next_4")


def test_character_view_keeps_canonical_selection_when_preferences_change():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.switch_page(STORY_PAGES[3][0]).run()
    app.selectbox(key="story_character_audience").set_value(157).run()
    app.radio(key="story_character_map_window").set_value("lifetime").run()
    for language, terminology in [("PT", "Plain"), ("PT", "League"), ("EN", "League"), ("EN", "Plain")]:
        app.segmented_control(key="_dashboard_language_choice").set_value(language).run()
        app.segmented_control(key="_story_terminology_choice").set_value(terminology).run()
        assert not app.exception
        assert app.radio(key="story_character_map_window").value == "lifetime"
        assert app.selectbox(key="story_character_audience").value == 157
        assert map_count(charts(app)[-1]) == 663
