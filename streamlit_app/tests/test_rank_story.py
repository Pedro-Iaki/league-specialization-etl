"""Rank conditionals, reference context and presentation controls keep their meaning."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.audience_segments import RANK_GROUPS, build_segment_reference, prepare_segments, segment_counts
from app_core.family_affinity import affinity_metadata, load_family_definition
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
from app_core.story import STORY_PAGES
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'legacy_app.py'


@pytest.fixture
def rank_audience():
    rows = [(tier, activity, games, history) for tier in ['BRONZE', 'GOLD', 'EMERALD', 'DIAMOND']
            for activity in [100000, 1000000, 2000000, 3000000, 5000000]
            for games in [10, 60, 150, 350, 600] for history in [100, 700] for _ in range(20)]
    players = pd.DataFrame(rows, columns=['tier', 'lifetime_mastery_points', 'total_games', 'oldest_retained_play_days'])
    players = players.assign(region='na1', queue='RANKED_SOLO_5x5', as_of_date='2026-10-20', snapshot_date='2026-10-20',
                             main_role=None, family_state='no_active_pool', family_category='No active pool',
                             primary_family_id=None, family_affinity=None)
    players.attrs['family_affinity'] = affinity_metadata(load_family_definition())
    reference = build_segment_reference(players, 'fixture')
    with patch('app_core.story.load_dataset', return_value=players), \
            patch('app_core.audience_story.load_segment_reference', return_value=reference):
        yield players, reference


def chart(app):
    return json.loads(app.get('plotly_chart')[0].proto.spec)


def rank_app(language='EN', terms='Plain'):
    app = AppTest.from_file(str(APP), default_timeout=45)
    app.session_state[LANGUAGE_KEY] = language
    app.session_state[TERMINOLOGY_KEY] = terms
    app.run().switch_page(STORY_PAGES[2][0]).run()
    return app


@pytest.mark.parametrize('language,terms', [('EN', 'Plain'), ('EN', 'League'), ('PT', 'Plain'), ('PT', 'League')])
def test_rank_map_covers_all_groups_without_focus_gate_and_modes_preserve_values(rank_audience, language, terms):
    players, reference = rank_audience
    base, _ = prepare_segments(players, reference)
    cells = segment_counts(base, ['activity_band', 'rank_group'], conditional_on=['rank_group'])
    np.testing.assert_allclose(cells.groupby('rank_group')['share'].sum(), 1)
    app = rank_app(language, terms)
    assert not app.exception and len(app.get('plotly_chart')) == 1 and not app.metric
    actual = chart(app)
    np.testing.assert_allclose(np.asarray(actual['data'][0]['z'], dtype=float), np.full((4, 5), .2))
    labels = actual['data'][0]['y']
    assert len(labels) == 4 and len(actual['layout']['annotations']) == 20
    assert any(('42,03%' if language == 'PT' else '42.03%') in label for label in labels)
    assert actual['data'][0]['zmax'] == 1
    assert app.session_state[LANGUAGE_KEY] == language and app.session_state[TERMINOLOGY_KEY] == terms
    assert actual['layout']['yaxis']['title']['text'] == (
        ('Grupo de elos' if terms == 'League' else 'Grupo de classificação') if language == 'PT'
        else ('Tier group' if terms == 'League' else 'Rank group'))


def test_rank_filters_inversion_and_units_preserve_reference_and_conditionals(rank_audience):
    players, reference = rank_audience
    app = rank_app()
    initial = chart(app)
    app.selectbox(key='story_rank_engagement').set_value('E2').run()
    base, _ = prepare_segments(players, reference)
    selected = base.loc[base.engagement_band.eq('E2')]
    expected = segment_counts(selected, ['activity_band', 'rank_group'], conditional_on=['rank_group'])
    assert expected.profiles.sum() == len(selected) < len(base)
    assert not app.exception
    filtered = chart(app)
    assert filtered['data'][0]['y'] == initial['data'][0]['y']
    np.testing.assert_allclose(np.nansum(filtered['data'][0]['z'], axis=1), 1)
    np.testing.assert_allclose(expected.groupby('rank_group')['share'].sum(), 1)
    app.toggle(key='story_rank_invert').set_value(True).run()
    assert not app.exception
    np.testing.assert_allclose(np.asarray(chart(app)['data'][0]['z']), np.asarray(filtered['data'][0]['z']).T)
    app.segmented_control(key='story_rank_units').set_value('Estimated hours').run()
    assert not app.exception
    np.testing.assert_allclose(np.asarray(chart(app)['data'][0]['z']), np.asarray(filtered['data'][0]['z']).T)
    assert chart(app)['data'][0]['x'] == initial['data'][0]['y']
    app.segmented_control(key='_dashboard_language_choice').set_value('PT').run()
    app.segmented_control(key='_story_terminology_choice').set_value('League').run()
    assert not app.exception and app.selectbox(key='story_rank_engagement').value == 'E2'
    assert app.toggle(key='story_rank_invert').value
    assert app.segmented_control(key='story_rank_units').value == 'Estimated hours'


def test_sparse_then_empty_selections_do_not_invent_estimates_or_drop_levels(rank_audience):
    app = rank_app()
    app.selectbox(key='story_rank_engagement').set_value('E1').run()
    app.selectbox(key='story_rank_history').set_value('H1').run()
    assert not app.exception
    assert np.isnan(np.asarray(chart(app)['data'][0]['z'], dtype=float)).all()
    assert all(row[0] == 'Limited support' for line in chart(app)['data'][0]['customdata'] for row in line)
    assert any('no supported cells' in item.value for item in app.info)
    app.selectbox(key='story_rank_history').set_value('H5').run()
    assert not app.exception
    assert all(row[0] == 'No observations' for line in chart(app)['data'][0]['customdata'] for row in line)
    assert len(chart(app)['data'][0]['y']) == len(RANK_GROUPS)
    assert app.button(key='story_previous_3') and app.button(key='story_next_3')
    app.selectbox(key='story_rank_history').set_value('All').run()
    app.selectbox(key='story_rank_engagement').set_value('All').run()
    np.testing.assert_allclose(np.asarray(chart(app)['data'][0]['z']), .2)
