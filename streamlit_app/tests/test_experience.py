import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.experience import experience_bands, experience_cells, experience_chart, experience_display
from app_core.i18n import LANGUAGE_KEY, localize_figure, t
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("size", [0, 3, 25, 28, 103])
def test_bands_have_equal_counts_even_with_ties(size):
    players = pd.DataFrame({
        "tier": ["IRON"] * size,
        "total_mastery_points": [100] * size,
        "alltime_playstyle": ["specialist"] * size,
    })
    bands = experience_bands(players)
    counts = bands.groupby("mastery_band").size().reindex(range(1, 6), fill_value=0)
    assert counts.sum() == size
    assert counts.max() - counts.min() <= 1
    pd.testing.assert_frame_equal(bands, experience_bands(players))


def test_bands_are_pooled_and_master_exclusion_keeps_assignments():
    players = pd.DataFrame({
        "tier": ["IRON"] * 10 + ["MASTER"] * 10,
        "total_mastery_points": range(20),
        "alltime_playstyle": ["specialist"] * 20,
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
        "total_mastery_points": [0, 100, np.nan, np.inf, -1, 100],
        "alltime_playstyle": ["generalist"] * 5 + ["insufficient activity"],
    })
    assert experience_bands(players)["total_mastery_points"].tolist() == [0, 100]


def test_omission_uses_denominator_and_preserves_zero_share():
    bands = pd.DataFrame({
        "tier": ["IRON"] * 6 + ["GOLD"] * 2,
        "mastery_band": [1] * 3 + [3] * 3 + [2] * 2,
        "alltime_playstyle": ["generalist"] * 3 + ["specialist", "generalist", "generalist"]
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
        "alltime_playstyle": ["generalist"] * 10 + ["specialist"] * 10,
    })
    cells = experience_cells(bands)
    zero, one = cells.iloc[0], cells.iloc[1]
    assert zero["lower"] == pytest.approx(0)
    assert zero["upper"] == pytest.approx(0.2775328)
    assert one["lower"] == pytest.approx(0.7224672)
    assert one["upper"] == pytest.approx(1)


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
        empty = pd.DataFrame(columns=["mastery_band", "tier", "alltime_playstyle"])
        chart = localize_figure(experience_chart(experience_display(experience_cells(empty), 3)))
        assert "Especialistas:" in chart.data[0].hovertemplate
        assert chart.layout.yaxis.title.text == "Proporção bruta de especialistas"
