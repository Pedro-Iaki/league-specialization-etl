from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import plotly.graph_objects as go
import pytest
from app_core.i18n import LANGUAGE_KEY, LOCALE_DIR, localize_figure, localize_frame, t
from streamlit.testing.v1 import AppTest

APP_ROOT = Path(__file__).resolve().parents[1]


def test_catalogs_match_and_keep_template_and_plotly_placeholders():
    english = json.loads((LOCALE_DIR / "en.json").read_text(encoding="utf-8"))
    portuguese = json.loads((LOCALE_DIR / "pt.json").read_text(encoding="utf-8"))
    assert english.keys() == portuguese.keys()
    for key, value in english.items():
        assert isinstance(portuguese[key], str) and portuguese[key]
        for expression in (r"\{p\d+\}", r"%\{[^}]+\}"):
            assert sorted(re.findall(expression, value)) == sorted(re.findall(expression, portuguese[key])), key


def test_localization_preserves_data_and_numeric_chart_values():
    frame = pd.DataFrame({"main_role": ["Top", "Jungle"], "cash_usd": [12.5, 3.0]})
    original = frame.copy(deep=True)
    figure = go.Figure(go.Bar(x=["Top", "Jungle"], y=[12.5, 3.0], name="Players",
                             hovertemplate="%{x}<br>%{fullData.name}: %{y:.1%}<br>Players: %{customdata[0]:,}<extra></extra>"))
    figure.update_xaxes(title="Current tier", categoryarray=["Top", "Jungle"])
    with patch("app_core.i18n._st.session_state", {LANGUAGE_KEY: "PT"}):
        assert t("Current tier") == "Elo atual"
        assert t("Insufficient data: 2 group(s) have fewer than 3 supporting players.").startswith("Dados insuficientes: 2")
        assert t("Master Yi") == "Master Yi"
        assert t("Top, Support") == "Topo, Suporte"
        assert t("main_role=Top") == "Função inferida=Topo"
        assert t("$1,234.50") == "US$ 1.234,50"
        assert t("Scenario demo · generator 1.2 · seed 42 · full generated history 2018-10-04 to 2026-09-29.").startswith(
            "Cenário demo · gerador 1.2 · semente 42"
        )
        translated = localize_frame(frame)
        chart = localize_figure(figure)
    pd.testing.assert_frame_equal(frame, original)
    assert translated["Gastos em USD"].tolist() == [12.5, 3.0]
    assert translated["Função inferida"].tolist() == ["Topo", "Selva"]
    assert list(chart.data[0].y) == list(figure.data[0].y)
    assert list(figure.data[0].x) == ["Top", "Jungle"]
    assert list(chart.data[0].x) == ["Topo", "Selva"]
    assert chart.layout.xaxis.title.text == "Elo atual"
    assert "Jogadores" in chart.data[0].hovertemplate


@pytest.mark.parametrize("page", ["app.py", "business.py", "overview.py", "pages/1_Overall_Analysis.py",
                                   "pages/2_Champion_Explorer.py", "pages/3_Notable_Champions.py",
                                   "pages/4_Population_Estimates.py"])
def test_all_pages_render_in_portuguese(page):
    app = AppTest.from_file(str(APP_ROOT / ("app.py" if page == "business.py" else page)), default_timeout=60)
    app.session_state[LANGUAGE_KEY] = "PT"
    app.run()
    if page == "business.py":
        app.switch_page(page).run()
    assert not app.exception
    assert any("Fonte de dados" in caption.value for caption in app.sidebar.caption)
    if page == 'app.py' and not app.get('plotly_chart'):
        assert any('retrato enriquecido com famílias' in item.value for item in app.info)
    elif page != 'app.py':
        assert any("Jogadores" in chart.proto.spec or "jogador" in chart.proto.spec for chart in app.get("plotly_chart"))
    if page == "business.py":
        assert len(app.get("plotly_chart")) == 4
        assert any("padrões de gastos são sintéticos" in caption.value for caption in app.caption)


def test_language_toggle_keeps_canonical_selections_and_survives_navigation():
    app = AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=60).run()
    app.switch_page("business.py").run()
    next(widget for widget in app.selectbox if widget.key == "business_tier").set_value("GOLD").run()
    next(widget for widget in app.selectbox if widget.label == "Group audiences by").set_value("Playstyle").run()
    next(widget for widget in app.segmented_control if widget.key == "_dashboard_language_choice").set_value("PT").run()
    assert not app.exception
    tier = next(widget for widget in app.selectbox if widget.key == "business_tier")
    assert tier.value == "GOLD" and "OURO" in tier.options
    assert next(widget for widget in app.selectbox if widget.label == "Agrupar públicos por").value == "Playstyle"
    next(widget for widget in app.selectbox if widget.key == "business_audience_dimension").set_value("Total playtime (estimated)").run()
    assert not app.exception
    assert "Tempo total de jogo (estimado)" in next(widget for widget in app.selectbox if widget.key == "business_audience_dimension").options
    assert "maestria" not in app.get("plotly_chart")[0].proto.spec.lower()
    assert app.session_state[LANGUAGE_KEY] == "PT"
    app.switch_page("overview.py").run()
    assert not app.exception
    assert app.session_state[LANGUAGE_KEY] == "PT"
    assert any(widget.label == "Janela de especialização" for widget in app.selectbox)
    next(widget for widget in app.segmented_control if widget.key == "_dashboard_language_choice").set_value("EN").run()
    assert not app.exception
    assert app.session_state[LANGUAGE_KEY] == "EN"
    assert any(widget.label == "Specialization window" for widget in app.selectbox)
