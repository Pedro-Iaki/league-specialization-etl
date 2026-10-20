import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.experience import (
    experience_bands, experience_cells, experience_chart, experience_display, experience_focus_cells,
    experience_overall, experience_ranges, role_focus_cells,
)
from app_core.i18n import LANGUAGE_KEY, localize_figure, t
from app_core.story_charts import audience_band_chart, audience_composition_chart
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("size", [0, 3, 25, 28, 103])
def test_bands_have_equal_counts_even_with_ties(size):
    players = pd.DataFrame({
        "tier": ["IRON"] * size,
        "lifetime_mastery_points": [100] * size,
        "lifetime_playstyle": ["specialist"] * size,
    })
    bands = experience_bands(players)
    counts = bands.groupby("mastery_band").size().reindex(range(1, 6), fill_value=0)
    assert counts.sum() == size
    assert counts.max() - counts.min() <= 1
    pd.testing.assert_frame_equal(bands, experience_bands(players))


def test_bands_are_pooled_and_master_exclusion_keeps_assignments():
    players = pd.DataFrame({
        "tier": ["IRON"] * 10 + ["MASTER"] * 10,
        "lifetime_mastery_points": range(20),
        "lifetime_playstyle": ["specialist"] * 20,
    })
    bands = experience_bands(players)
    assert bands.loc[bands["tier"].eq("IRON"), "mastery_band"].max() == 3
    included = experience_cells(bands)
    excluded = experience_cells(bands, include_master=False)
    assert included["n"].sum() == 20
    assert excluded["n"].sum() == 10
    pd.testing.assert_frame_equal(
        included.loc[included["tier_group"].eq("Iron-Silver")],
        excluded.loc[excluded["tier_group"].eq("Iron-Silver")],
    )


def test_only_classified_valid_mastery_enters_bands():
    players = pd.DataFrame({
        "lifetime_mastery_points": [0, 100, np.nan, np.inf, -1, 100],
        "lifetime_playstyle": ["generalist"] * 5 + ["insufficient activity"],
    })
    assert experience_bands(players)["lifetime_mastery_points"].tolist() == [0, 100]


def test_omission_uses_denominator_and_preserves_zero_share():
    bands = pd.DataFrame({
        "tier": ["IRON"] * 6 + ["GOLD"] * 2,
        "mastery_band": [1] * 3 + [3] * 3 + [2] * 2,
        "lifetime_playstyle": ["generalist"] * 3 + ["specialist", "generalist", "generalist"]
                             + ["specialist"] * 2,
        "_population_weight": [999] * 8,
    })
    cells = experience_cells(bands)
    visible = experience_display(cells, 3)
    low = visible.loc[visible["n"].lt(3)]
    assert low["share"].isna().all()
    supported = visible.loc[visible["n"].eq(3)]
    assert supported["share"].tolist() == [0, pytest.approx(1 / 3)]
    assert supported["count_label"].tolist() == ["n=3", "n=3"]
    assert supported["lower"].ge(0).all()
    assert supported["upper"].le(1).all()
    shown = experience_display(cells, 3, True)
    assert shown.loc[shown["n"].eq(2), "share"].item() == 1
    assert shown.loc[shown["n"].eq(2), "count_label"].item() == "n=2 ⚠"
    assert shown.loc[shown["n"].eq(0), "share"].isna().all()
    assert shown.loc[shown["n"].eq(0), "count_label"].eq("").all()
    trace = experience_chart(visible, lines=True).data[0]
    assert trace.connectgaps is False
    assert np.isnan(trace.y[1])
    assert len(experience_chart(visible).data) == 20


def test_wilson_interval_for_zero_and_all_specialists():
    bands = pd.DataFrame({
        "tier": ["IRON"] * 10 + ["GOLD"] * 10,
        "mastery_band": [1] * 20,
        "lifetime_playstyle": ["generalist"] * 10 + ["specialist"] * 10,
    })
    cells = experience_cells(bands)
    zero, one = cells.iloc[0], cells.iloc[1]
    assert zero["lower"] == pytest.approx(0)
    assert zero["upper"] == pytest.approx(0.2775328)
    assert one["lower"] == pytest.approx(0.7224672)
    assert one["upper"] == pytest.approx(1)


def test_overall_pools_counts_instead_of_averaging_band_shares():
    banded = pd.DataFrame({
        "tier": ["IRON"] * 12,
        "mastery_band": [1] * 3 + [2] * 9,
        "lifetime_playstyle": ["specialist"] * 3 + ["generalist"] * 9,
        "population_weight": [100] * 3 + [1] * 9,
    })
    overall = experience_overall(experience_focus_cells(banded))
    assert overall.groupby("tier_group")["members"].sum().tolist() == [0, 0, 0, 12]
    overall = overall.loc[overall["playstyle"].eq("specialist")].set_index("tier_group")
    assert overall.loc["Iron-Silver", "n"] == 12
    assert overall.loc["Iron-Silver", "members"] == 3
    assert overall.loc["Iron-Silver", "share"] == .25
    assert overall.loc["Diamond+", "n"] == 0
    assert pd.isna(overall.loc["Diamond+", "share"])


def test_focus_charts_keep_supported_zero_and_break_at_sparse_cells():
    banded = pd.DataFrame({
        "tier": ["IRON"] * 3 + ["GOLD"] * 2,
        "mastery_band": [1] * 5,
        "lifetime_playstyle": ["generalist"] * 3 + ["specialist"] * 2,
    })
    cells = experience_focus_cells(banded)
    specialist = cells.loc[cells["playstyle"].eq("specialist")]
    chart = audience_band_chart(specialist, intervals=True)
    assert chart.data[0].y[0] == 0
    assert pd.isna(chart.data[0].y[1])
    assert chart.data[0].connectgaps is False
    assert chart.data[0].error_y.array[0] == pytest.approx(specialist.iloc[0]["upper"])
    assert chart.data[0].customdata[1][:2] == [2, 2]
    overall = audience_composition_chart(experience_overall(cells))
    assert overall.data[0].x[0] == 0
    assert pd.isna(overall.data[0].x[1])
    assert any("n = 2" in label for label in overall.layout.yaxis.ticktext)
    assert "Low support" in [annotation.text for annotation in overall.layout.annotations]


def test_all_focus_counts_reconcile_and_roles_retain_unknown_profiles():
    banded = pd.DataFrame({
        "tier": ["IRON"] * 5,
        "mastery_band": [1] * 5,
        "lifetime_playstyle": ["specialist", "multispecialist", "versatile", "generalist", "generalist"],
        "main_role": ["Top", "Top", None, "unexpected", "Support"],
    })
    cells = experience_focus_cells(banded)
    assert cells["members"].sum() == 5
    first = cells.iloc[:4]
    assert first["n"].eq(5).all()
    assert first["share"].sum() == pytest.approx(1)
    expected = experience_cells(banded)
    specialist = cells.loc[cells["playstyle"].eq("specialist")].reset_index(drop=True)
    pd.testing.assert_frame_equal(expected[["share", "lower", "upper"]], specialist[["share", "lower", "upper"]])
    roles = role_focus_cells(banded)
    assert roles["members"].sum() == 5
    assert roles.loc[roles["main_role"].eq("Unknown role"), "members"].sum() == 2


def test_hour_equivalents_use_declared_assumptions_without_changing_bands():
    players = pd.DataFrame({"tier": ["GOLD"] * 10, "lifetime_playstyle": ["generalist"] * 10,
                            "lifetime_mastery_points": np.arange(10) * 1200})
    banded = experience_bands(players)
    original = banded.copy(deep=True)
    ranges = experience_ranges(banded)
    assert ranges["hours_low"].tolist() == pytest.approx([0, 2, 4, 6, 8])
    assert ranges["hours_high"].tolist() == pytest.approx([1, 3, 5, 7, 9])
    pd.testing.assert_frame_equal(banded, original)


def test_page_layout_and_master_toggles_render():
    page = Path(__file__).resolve().parents[1] / "pages/1_Overall_Analysis.py"
    app = AppTest.from_file(str(page), default_timeout=60).run()
    assert not app.exception

    def chart():
        charts = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
        return next(item for item in charts if item["layout"]["yaxis"]["title"]["text"] == "Raw specialist share")

    assert len(chart()["data"]) == 20
    next(widget for widget in app.toggle if widget.label == "Lines across mastery bands").set_value(True).run()
    assert not app.exception
    assert len(chart()["data"]) == 4
    next(widget for widget in app.toggle if widget.label == "Merge Master into Diamond+").set_value(False).run()
    assert not app.exception
    next(widget for widget in app.slider if widget.key == "ranked_share_support").set_value(50).run()
    assert not app.exception
    assert len(chart()["data"]) == 4


def test_experience_portuguese_labels_and_hover():
    with patch("app_core.i18n._st.session_state", {LANGUAGE_KEY: "PT"}):
        assert t("Experience-stratified specialization") == "Especialização por faixa de experiência"
        empty = pd.DataFrame(columns=["mastery_band", "tier", "lifetime_playstyle"])
        chart = localize_figure(experience_chart(experience_display(experience_cells(empty), 3)))
        assert "Especialistas:" in chart.data[0].hovertemplate
        assert chart.layout.yaxis.title.text == "Proporção bruta de especialistas"
