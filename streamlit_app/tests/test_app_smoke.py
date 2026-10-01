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
    cycle = next(widget for widget in app.button if widget.label == "↻")
    assert "Using: Pearson r." in cycle.proto.help
    cycle.click().run()
    assert not app.exception
    cycle = next(widget for widget in app.button if widget.label == "↻")
    assert "Using: slope." in cycle.proto.help
    assert any(metric.label == "MG Association" for metric in app.metric)


@pytest.mark.parametrize("basis", ["Active (60 days)", "All-time"])
def test_current_profile_windows_use_current_tier_without_historical_period_filter(basis: str) -> None:
    app = AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=30).run()
    next(widget for widget in app.selectbox if widget.label == "Specialization window").set_value(basis).run()
    assert not app.exception
    assert any(widget.label == "Current tier" for widget in app.selectbox)
    assert not any("Minimum observed periods" in widget.label for widget in app.slider)
    assert any("not adjusted for tier" in message.value for message in app.info)
