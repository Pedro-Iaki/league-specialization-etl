from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    [
        "app.py",
        "pages/1_Overall_Analysis.py",
        "pages/2_Champion_Explorer.py",
        "pages/3_Notable_Champions.py",
    ],
)
def test_page_renders_without_exception(relative_path: str) -> None:
    app = AppTest.from_file(str(APP_ROOT / relative_path), default_timeout=30)
    app.run()
    assert not app.exception


def test_refreshed_growth_views_render() -> None:
    growth_players = pd.DataFrame(
        {
            "starting_tier": ["GOLD", "GOLD"],
            "current_main_role": ["Middle", "Middle"],
            "specialization_hhi": [0.5, 0.8],
            "top_champion_share": [0.6, 0.9],
            "normalized_entropy": [0.5, 0.2],
            "climbing_efficiency": [1.2, 2.5],
            "estimated_ranked_mastery_share": [0.5, 0.7],
            "period_count": [2, 3],
            "games": [12, 20],
        }
    )
    growth_styles = pd.DataFrame(
        {
            "starting_tier": ["GOLD"],
            "current_main_role": ["Middle"],
            "playstyle": ["specialist"],
            "climbing_efficiency": [1.2],
            "win_rate": [0.55],
            "period_count": [2],
            "games": [12],
        }
    )
    champion_players = pd.DataFrame(
        {
            "champion_name": ["Ahri", "Ahri"],
            "starting_tier": ["GOLD", "GOLD"],
            "champion_commitment": [0.5, 0.8],
            "specialization_hhi": [0.4, 0.7],
            "top_champion_share": [0.6, 0.8],
            "climbing_efficiency": [1.0, 2.0],
            "period_count": [2, 3],
            "attributed_games": [10, 15],
        }
    )
    champion_tiers = pd.DataFrame(
        {
            "champion_name": ["Ahri"],
            "starting_tier": ["GOLD"],
            "cohort_scope": ["champion_tier_playstyle"],
            "playstyle": ["specialist"],
            "observed_player_count": [20],
            "observed_period_count": [25],
            "climbing_efficiency": [1.2],
            "observed_win_rate": [0.55],
        }
    )
    ranked_cohorts = pd.DataFrame(
        {
            "window_name": ["All observed periods", "All observed periods"],
            "starting_tier": ["GOLD", "SILVER"],
            "current_main_role": ["Middle", "Top"],
            "median_ranked_mastery_share": [0.6, 0.8],
            "period_count": [2, 1],
            "first_period_end": pd.to_datetime(["2026-09-20", "2026-09-20"]),
            "last_period_end": pd.to_datetime(["2026-09-27", "2026-09-20"]),
            "favoured_champions": [["Ahri", "Ezreal"], ["Aatrox"]],
        }
    )
    optional = {
        "growth_players": growth_players,
        "growth_player_styles": growth_styles,
        "champion_growth_players": champion_players,
        "champion_tier_growth": champion_tiers,
        "ranked_mastery_cohorts": ranked_cohorts,
    }
    with patch("app_core.data.load_optional_dataset", side_effect=optional.get):
        for relative_path in ("app.py", "pages/1_Overall_Analysis.py", "pages/2_Champion_Explorer.py"):
            app = AppTest.from_file(str(APP_ROOT / relative_path), default_timeout=30).run()
            assert not app.exception, relative_path
            if relative_path == "app.py":
                next(widget for widget in app.selectbox if widget.label == "Specialization window").set_value("Observed rank periods").run()
                assert any("concentration band" in warning.value for warning in app.warning)


def test_optional_tier_mastery_views_render() -> None:
    tier_mastery = pd.DataFrame({
        "champion_name": ["Ahri", "Ahri"],
        "tier": ["GOLD", "PLATINUM"],
        "minimum_mastery": [0, 0],
        "player_count": [20, 15],
        "expert_player_count": [5, 7],
        "mean_mastery": [80000.0, 100000.0],
        "q1_mastery": [20000.0, 30000.0],
        "median_mastery": [60000.0, 90000.0],
        "q3_mastery": [120000.0, 150000.0],
        "min_mastery": [1000, 2000],
        "max_mastery": [300000, 350000],
        "mean_rank_score": [1400.0, 1800.0],
        "median_rank_score": [1400.0, 1800.0],
    })
    from app_core.data import load_optional_dataset as original
    with patch("app_core.data.load_optional_dataset", side_effect=lambda name: tier_mastery if name == "champion_tier_mastery" else original(name)):
        for path in ("pages/2_Champion_Explorer.py", "pages/3_Notable_Champions.py"):
            app = AppTest.from_file(str(APP_ROOT / path), default_timeout=30).run()
            assert not app.exception, path


@pytest.mark.parametrize("relative_path", ["app.py", "pages/1_Overall_Analysis.py", "pages/2_Champion_Explorer.py"])
def test_player_support_controls_default_to_three(relative_path: str) -> None:
    app = AppTest.from_file(str(APP_ROOT / relative_path), default_timeout=30).run()
    support_sliders = [slider for slider in app.slider if slider.label.startswith("Minimum players")
                       or slider.label.startswith("Minimum historical players")
                       or slider.label.startswith("Minimum player–tier observations")]
    assert support_sliders
    assert all(slider.value == 3 for slider in support_sliders)
    if relative_path == "pages/2_Champion_Explorer.py":
        assert next(slider for slider in app.slider if slider.label == "Minimum shared players").value == 100


def test_insufficient_data_warning_can_reveal_and_hide_champions() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/3_Notable_Champions.py"), default_timeout=30).run()
    minimum = next(slider for slider in app.slider if slider.label == "Minimum historical players per champion")
    minimum.set_value(100).run()
    assert not app.exception
    show = next(button for button in app.button if button.key == "toggle_omitted_cross_champions")
    assert show.label == "Show omitted"
    show.click().run()
    assert not app.exception
    hide = next(button for button in app.button if button.key == "toggle_omitted_cross_champions")
    assert hide.label == "Hide omitted"
    assert any("Showing low-support results" in warning.value for warning in app.warning)
    hide.click().run()
    assert not app.exception
    assert next(button for button in app.button if button.key == "toggle_omitted_cross_champions").label == "Show omitted"


def test_ranked_share_dimension_controls_render() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/1_Overall_Analysis.py"), default_timeout=30).run()
    horizontal = next(widget for widget in app.selectbox if widget.label == "Horizontal dimension")
    horizontal.set_value("Champion").run()
    assert not app.exception
    assert any(widget.label == "Champions to display" for widget in app.multiselect)

    horizontal = next(widget for widget in app.selectbox if widget.label == "Horizontal dimension")
    horizontal.set_value("Role").run()
    vertical = next(widget for widget in app.selectbox if widget.label == "Vertical dimension")
    vertical.set_value("Champion").run()
    assert not app.exception


def test_champion_over_under_controls_render() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/2_Champion_Explorer.py"), default_timeout=30).run()
    for toggle in app.toggle:
        toggle.set_value(True)
    app.run()
    assert not app.exception
    outcome = next(widget for widget in app.selectbox if widget.label == "Outcome")
    outcome.set_value("Win rate").run()
    assert not app.exception
    cycle = next(widget for widget in app.button if widget.label == "→")
    assert "Using: Pearson r." in cycle.proto.help
    cycle.click().run()
    assert not app.exception
    cycle = next(widget for widget in app.button if widget.label == "→")
    assert "Using: slope." in cycle.proto.help
    assert any(metric.label == "SxG Association" for metric in app.metric)


def test_rank_score_player_mix_renders() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/2_Champion_Explorer.py"), default_timeout=30).run()
    next(widget for widget in app.selectbox if widget.label == "Compare by").set_value("Rank score").run()
    assert not app.exception
    next(widget for widget in app.toggle if widget.label == "Difference from sample").set_value(True).run()
    assert not app.exception


def test_champion_header_buttons_cycle_values() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/2_Champion_Explorer.py"), default_timeout=30).run()
    for label in ("Primary players", "Active players", "Historical players"):
        assert "%" in next(metric for metric in app.metric if metric.label == label).value
    next(button for button in app.button if button.key == "toggle_primary_pct").click().run()
    assert "%" not in next(metric for metric in app.metric if metric.label == "Primary players").value
    ranked = next(metric for metric in app.metric if metric.label == "Ranked share")
    assert "%" in ranked.value
    next(button for button in app.button if button.key == "cycle_ranked_share").click().run()
    assert "pp" in next(metric for metric in app.metric if metric.label == "Ranked share").value
    next(button for button in app.button if button.key == "cycle_ranked_share").click().run()
    assert "Mean difference" in next(button for button in app.button if button.key == "cycle_ranked_share").proto.help


def test_champion_mastery_threshold_updates_cards() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/2_Champion_Explorer.py"), default_timeout=30).run()
    assert next(slider for slider in app.slider if slider.label == "Minimum champion mastery points").value == 20_000
    first = next(metric.value for metric in app.metric if metric.label == "Mean mastery")
    for key in ("mastery_mean", "mastery_median"):
        assert any(button.key == f"toggle_{key}_comparison" for button in app.button)
    assert not any(metric.label == "Players ≥100K mastery" for metric in app.metric)
    next(button for button in app.button if button.key == "toggle_mastery_mean_comparison").click().run()
    assert "%" in next(metric for metric in app.metric if metric.label == "Mean mastery vs sample").value
    next(button for button in app.button if button.key == "toggle_mastery_mean_comparison").click().run()
    next(slider for slider in app.slider if slider.label == "Minimum champion mastery points").set_value(50_000).run()
    assert not app.exception
    second = next(metric.value for metric in app.metric if metric.label == "Mean mastery")
    assert first != second
    assert next(slider for slider in app.slider if slider.label == "Minimum champion mastery points").value == 50_000
    next(widget for widget in app.segmented_control if widget.label == "Tier measure").set_value("Mastery distribution").run()
    assert not app.exception


def test_champion_ladder_and_expert_comparison_controls() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/2_Champion_Explorer.py"), default_timeout=30).run()
    assert not any(widget.label == "Ladder horizontal axis" for widget in app.segmented_control)
    next(widget for widget in app.toggle if widget.label == "Difference from sampled expert share").set_value(True).run()
    assert not app.exception


def test_notable_mastery_curves_and_threshold_render() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/3_Notable_Champions.py"), default_timeout=30).run()
    options = next(widget for widget in app.selectbox if widget.label == "Measure").options
    assert {"Mean mastery (at least 15K)", "Median mastery (at least 15K)", "Expert player share", "Active play rate"}.issubset(set(options))
    next(slider for slider in app.slider if slider.label == "Minimum champion mastery").set_value(90_000).run()
    assert not app.exception
    assert not any(widget.label == "Ladder horizontal axis" for widget in app.segmented_control)
    assert next(slider for slider in app.slider if slider.label == "Minimum mastery for player boxes").value == 15_000


def test_cross_champion_player_mastery_boxes_render_when_extract_exists() -> None:
    from app_core.data import load_optional_dataset as original

    player_mastery = pd.DataFrame({
        "champion_name": ["Ahri", "Ahri"],
        "tier": ["GOLD", "DIAMOND"],
        "champion_points": [20_000, 50_000],
        "total_mastery_points": [100_000, 100_000],
        "mastery_share": [0.2, 0.5],
    })
    with patch("app_core.data.load_optional_dataset", side_effect=lambda name: player_mastery if name == "champion_player_mastery_share" else original(name)):
        app = AppTest.from_file(str(APP_ROOT / "pages/3_Notable_Champions.py"), default_timeout=30).run()
        assert not app.exception
        assert any("2 champion mastery holders" in caption.value for caption in app.caption)
        next(slider for slider in app.slider if slider.label == "Minimum mastery for player boxes").set_value(50_000).run()
        assert not app.exception
        assert any("1 champion mastery holders" in caption.value for caption in app.caption)


def test_mastery_controls_render_without_exception() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/1_Overall_Analysis.py"), default_timeout=30).run()
    next(widget for widget in app.selectbox if widget.label == "Mastery tier").set_value("GOLD").run()
    next(widget for widget in app.toggle if widget.label == "Log mean mastery on horizontal axis").set_value(True).run()
    assert not app.exception


@pytest.mark.parametrize("basis", ["Active (60 days)", "All-time"])
def test_current_profile_windows_use_current_tier_without_historical_period_filter(basis: str) -> None:
    app = AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=30).run()
    next(widget for widget in app.selectbox if widget.label == "Specialization window").set_value(basis).run()
    assert not app.exception
    assert not any(widget.label == "Current tier" for widget in app.selectbox)
    assert not any("Minimum observed periods" in widget.label for widget in app.slider)
    assert any("not adjusted for tier" in message.value for message in app.info)


def test_overview_historical_controls_and_playstyle_outcomes() -> None:
    app = AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=30).run()
    assert next(widget for widget in app.selectbox if widget.label == "Specialization window").value == "Active (60 days)"
    assert not any(widget.label == "Minimum estimated ranked share" for widget in app.slider)
    assert not any(widget.label == "Role-purity tier" for widget in app.selectbox)
    assert any(widget.label == "Starting tier" for widget in app.selectbox)
    next(widget for widget in app.selectbox if widget.label == "Specialization window").set_value("Observed rank periods").run()
    assert next(slider for slider in app.slider if slider.label == "Minimum estimated ranked share").value == 0.35
    assert all(any(slider.label == label for slider in app.slider) for label in (
        "Minimum ranked games in outcome window",
        "Minimum observed periods per player and tier",
        "Minimum estimated ranked share",
    ))
    assert not app.exception


def test_overall_pool_shape_is_one_measure() -> None:
    app = AppTest.from_file(str(APP_ROOT / "pages/1_Overall_Analysis.py"), default_timeout=30).run()
    assert any(widget.label == "Pool measure" for widget in app.selectbox)
    assert not any(widget.label == "Pool display" for widget in app.segmented_control)
