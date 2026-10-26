"""The wider audience opening: real statistics survive presentation controls."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.audience_segments import build_segment_reference, prepare_segments, segment_counts
from app_core.audience_story import under_100_share
from app_core.data import DashboardDataError
from app_core.family_affinity import affinity_metadata, load_family_definition
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
from app_core.segment_presentation import audience_map_figure
from app_core.story import STORY_PAGES
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'legacy_app.py'


@pytest.fixture
def audience():
    players = pd.DataFrame({
        'region': 'na1', 'queue': 'RANKED_SOLO_5x5', 'tier': ['BRONZE'] * 250 + ['DIAMOND'] * 250,
        'as_of_date': '2026-10-20', 'snapshot_date': '2026-10-20',
        'lifetime_mastery_points': [100000, 1000000, 2000000, 3000000, 5000000] * 100,
        'total_games': [10, 60, 150, 350, 10, 10, 60, 150, 350, 600] * 50,
        'oldest_retained_play_days': [100, 700, 1400, 2200, 2800] * 100,
        'main_role': None, 'family_state': 'no_active_pool', 'family_category': 'No active pool',
        'primary_family_id': None, 'family_affinity': None,
    })
    players.attrs['family_affinity'] = affinity_metadata(load_family_definition())
    reference = build_segment_reference(players, 'fixture')
    with patch('app_core.story.load_dataset', return_value=players), \
            patch('app_core.audience_story.load_segment_reference', return_value=reference):
        yield players, reference


def chart(app):
    return json.loads(app.get('plotly_chart')[0].proto.spec)


@pytest.mark.parametrize('language,terms', [('EN', 'Plain'), ('EN', 'League'), ('PT', 'Plain'), ('PT', 'League')])
def test_opening_and_page2_use_the_same_full_base_and_localize_without_numeric_change(audience, language, terms):
    players, reference = audience
    base, _ = prepare_segments(players, reference)
    expected = segment_counts(base, ['activity_band', 'engagement_band'])
    app = AppTest.from_file(str(APP), default_timeout=45)
    app.session_state[LANGUAGE_KEY] = language
    app.session_state[TERMINOLOGY_KEY] = terms
    app.run()
    assert not app.exception and len(app.get('plotly_chart')) == 1
    preview = np.array(chart(app)['data'][0]['z'], dtype=float)
    assert np.nansum(preview) == pytest.approx(expected.estimate.sum())
    assert not app.metric  # observed profile counts are no longer hero metrics
    app.switch_page(STORY_PAGES[1][0]).run()
    assert not app.exception and len(app.get('plotly_chart')) == 1
    np.testing.assert_allclose(np.array(chart(app)['data'][0]['z'], dtype=float), preview, equal_nan=True)
    assert [metric.value for metric in app.metric] == (['50,0%', '50,0%'] if language == 'PT' else ['50.0%', '50.0%'])
    assert app.session_state[TERMINOLOGY_KEY] == terms
    assert app.session_state[LANGUAGE_KEY] == language
    if language == 'PT':
        assert 'Parcela do público' in json.dumps(chart(app), ensure_ascii=False)
        assert 'Partidas ranqueadas registradas' in chart(app)['layout']['yaxis']['title']['text']
        assert any('Atividade acumulada e volume' in item.value for item in app.markdown)


def test_units_history_and_language_changes_preserve_analytical_inputs(audience):
    players, reference = audience
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    app.switch_page(STORY_PAGES[1][0]).run()
    before = chart(app)
    app.segmented_control(key='story_activity_units').set_value('Estimated hours').run()
    assert not app.exception
    assert chart(app)['data'][0]['z'] == before['data'][0]['z']
    assert chart(app)['data'][0]['x'] != before['data'][0]['x']
    assert any('1,200' in item.value for item in app.caption)
    app.selectbox(key='story_history_lens').set_value('H1').run()
    assert not app.exception
    assert chart(app)['data'][0]['x'] == ['≤500 h', '500–1,250 h', '1,250–2,083 h', '2,083–3,333 h', '>3,333 h']
    assert np.nansum(np.asarray(chart(app)['data'][0]['z'], dtype=float)) == pytest.approx(1)
    assert chart(app)['data'][0]['z'][0][0] == pytest.approx(1)
    app.segmented_control(key='_dashboard_language_choice').set_value('PT').run()
    assert not app.exception
    assert app.selectbox(key='story_history_lens').value == 'H1'
    assert app.segmented_control(key='story_activity_units').value == 'Estimated hours'
    app.selectbox(key='story_history_lens').set_value('All').run()
    assert chart(app)['data'][0]['z'] == before['data'][0]['z']
    base, _ = prepare_segments(players, reference)
    assert under_100_share(base) == pytest.approx(.5)
    assert under_100_share(base.iloc[:0]) is None


def test_map_transpose_keeps_values_and_suppressed_cells(audience):
    players, reference = audience
    base, _ = prepare_segments(players, reference)
    cells = segment_counts(base, ['activity_band', 'engagement_band'])
    orders = {'activity_band': [f'A{i}' for i in range(1, 6)], 'engagement_band': [f'E{i}' for i in range(1, 6)]}
    first = audience_map_figure(cells, reference, orders=orders)
    transposed = audience_map_figure(cells, reference, orders=orders, x_dimension='engagement_band', y_dimension='activity_band')
    np.testing.assert_allclose(np.asarray(first.data[0].z, dtype=float).T,
                               np.asarray(transposed.data[0].z, dtype=float), equal_nan=True)
    assert first.data[0].zmax == transposed.data[0].zmax
    assert len(first.layout.annotations) == 25
    assert first.data[0].colorbar.title.side == 'top' and first.layout.xaxis.tickangle == 0


def test_missing_segment_reference_keeps_navigation_without_substituting_paired_data(audience):
    app = AppTest.from_file(str(APP), default_timeout=45).run()
    with patch('app_core.audience_story.load_segment_reference', side_effect=DashboardDataError('reference mismatch')):
        app.switch_page(STORY_PAGES[1][0]).run()
    assert not app.exception and not app.get('plotly_chart')
    assert any('reference mismatch' in item.value for item in app.code)
    assert app.button(key='story_previous_2') and app.button(key='story_next_2')
