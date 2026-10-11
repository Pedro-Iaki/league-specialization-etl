from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from app_core.business import (
    AUDIENCE_DIMENSIONS,
    BUSINESS_PUBLIC_COLUMNS,
    CASH_DISCOUNT_COLUMNS,
    audience_summary,
    cosmetic_summary,
    discount_summary,
    experience_summary,
)
from app_core.business_charts import audience_chart
from app_core.data import _validate_dataset
from scripts.export_data import validate_public_frame
from streamlit.testing.v1 import AppTest


@pytest.fixture
def business_frame():
    frame = pd.DataFrame({column: [None] * 12 for column in BUSINESS_PUBLIC_COLUMNS})
    frame["scenario_id"] = "business-test"
    frame["tier"] = ["GOLD"] * 6 + ["SILVER"] * 6
    frame["main_role"] = ["Middle"] * 6 + ["Top"] * 6
    frame["active_playstyle"] = ["specialist"] * 6 + ["generalist"] * 6
    frame["active_primary_champion_name"] = ["Ahri"] * 6 + ["Garen"] * 6
    frame["total_mastery_points"] = [100_000] * 3 + [200_000] * 3 + [300_000] * 3 + [400_000] * 3
    frame["active_top1_share"] = [0.8] * 6 + [0.2] * 6
    frame["active_normalized_entropy"] = [0.2] * 6 + [0.8] * 6
    frame["content_purchase_count_alltime"] = 10
    frame["cosmetic_bias_alltime"] = [0.5] * 6 + [0.25] * 6
    frame["as_of_date"] = pd.Timestamp("2026-09-29")
    frame["snapshot_date"] = pd.Timestamp("2026-09-29")
    frame["purchase_window_start"] = pd.Timestamp("2026-08-01")
    frame["purchase_window_end"] = pd.Timestamp("2026-09-29")
    frame["first_purchase_at"] = pd.Timestamp("2025-01-01")
    frame["cash_purchase_count_60d"] = [2, 0] * 6
    frame["cash_spent_usd_60d"] = [20, 0] * 3 + [10, 0] * 3
    frame["cash_discounted_purchase_count_60d"] = [1, 0] * 6
    frame["cash_discount_share_60d"] = [0.5, None] * 6
    frame["cash_discount_mean_60d"] = [0.1, None] * 3 + [0.3, None] * 3
    return frame


def test_business_summaries_preserve_denominators_and_weight_cash_discounts(business_frame):
    frame = business_frame
    validate_public_frame("business_players", frame)
    with pytest.raises(ValueError, match="forbidden"):
        validate_public_frame("business_players", frame.assign(player_id="private"))
    summary = audience_summary(frame, "main_role").set_index("main_role")
    assert summary.loc["Middle", "cash_purchaser_share"] == 0.5
    assert summary.loc["Middle", "usd_per_player"] == 10
    assert summary.loc["Middle", "usd_per_purchaser"] == 20
    assert experience_summary(frame)["players"].sum() == len(frame)
    assert set(cosmetic_summary(frame, "active_top1_share", "active_playstyle")["mean_cosmetic_share"]) == {0.25, 0.5}
    two = frame.iloc[:2].copy()
    two["cash_purchase_count_60d"] = [2, 4]
    two["cash_discounted_purchase_count_60d"] = [1, 3]
    two["cash_discount_mean_60d"] = [0.1, 0.3]
    two["discount_mean_alltime"] = 0.9  # game-currency-inclusive metrics must not affect this chart
    discounts = discount_summary(two, "main_role").iloc[0]
    assert discounts["cash_discount_share"] == pytest.approx(4 / 6)
    assert discounts["cash_discount_mean"] == pytest.approx(0.25)
    nonpayer = frame.iloc[[1]].copy()
    assert audience_summary(nonpayer, "main_role")["usd_per_purchaser"].isna().all()
    assert experience_summary(nonpayer)["usd_per_player"].eq(0).all()
    assert discount_summary(nonpayer, "main_role").empty


def test_four_business_views_and_controls_render(business_frame):
    root = Path(__file__).resolve().parents[1]
    with patch("app_core.data.load_optional_dataset", return_value=business_frame):
        app = AppTest.from_file(str(root / "app.py"), default_timeout=30).run()
        assert not app.exception
        assert len(app.get("plotly_chart")) == 4
        assert sum("patterns are synthetic" in caption.value for caption in app.caption) == 4
        assert not any(widget.label == "Primary champion" for widget in app.selectbox)
        assert not any(widget.label == "Champion audiences to compare" for widget in app.multiselect)
        next(widget for widget in app.slider if widget.key == "business_support").set_value(1).run()
        for label, value in (
            *(("Group audiences by", group) for group in AUDIENCE_DIMENSIONS),
            ("Experience outcome", "usd_per_purchaser"),
            ("Champion-pool measure", "Champion-pool diversity (entropy)"),
            ("Compare cash discounts by", "Tier"),
        ):
            next(widget for widget in app.selectbox if widget.label == label).set_value(value).run()
            assert not app.exception, label
            if label == "Group audiences by":
                assert len(app.get("plotly_chart")) == 4
                assert "mastery" not in app.get("plotly_chart")[0].proto.spec.lower()
        next(widget for widget in app.selectbox if widget.label == "Current tier").set_value("GOLD").run()
        next(widget for widget in app.selectbox if widget.label == "Inferred role").set_value("Top").run()
        assert not app.exception
        assert any("No profiles match" in notice.value for notice in app.warning)


def test_audience_traits_keep_every_player_and_do_not_split_equal_playtime(business_frame):
    frame = business_frame.copy()
    frame["first_purchase_at"] = pd.to_datetime(["2026-03-01", "2024-01-01", "2020-01-01"] * 4)
    for dimension in AUDIENCE_DIMENSIONS.values():
        summary = audience_summary(frame, dimension)
        assert summary["players"].sum() == len(frame)
        assert summary["cash_purchasers"].sum() == frame["cash_purchase_count_60d"].gt(0).sum()
        assert summary["cash_usd"].sum() == frame["cash_spent_usd_60d"].sum()
        assert summary[dimension].is_unique
        assert summary[dimension].notna().all()
        assert "mastery" not in audience_chart(summary, dimension).to_json().lower()
    age = audience_summary(frame, "tenure_band")
    assert set(age["audience"]) == {"Under 1 year", "1–3 years", "3+ years"}
    tied = audience_summary(frame.assign(total_mastery_points=100_000), "playtime_band")
    assert len(tied) == 1 and tied["players"].iloc[0] == len(frame)
    with pytest.raises(ValueError, match="Unsupported audience"):
        audience_summary(frame, "active_primary_champion_name")


def test_older_business_snapshot_and_absent_sample_still_render(business_frame):
    legacy = business_frame.drop(columns=list(CASH_DISCOUNT_COLUMNS))
    _validate_dataset("business_players", legacy)
    root = Path(__file__).resolve().parents[1]
    with patch("app_core.data.load_optional_dataset", return_value=legacy):
        app = AppTest.from_file(str(root / "app.py"), default_timeout=30).run()
        assert not app.exception
        assert len(app.get("plotly_chart")) == 3
        assert any("cash-only discount breakdown" in notice.value for notice in app.info)
    with patch("app_core.data.load_optional_dataset", return_value=None):
        app = AppTest.from_file(str(root / "app.py"), default_timeout=30).run()
        assert not app.exception
        assert any("no business sample" in info.value for info in app.info)
