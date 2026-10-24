"""Family audiences preserve categorical, vector, availability and trait denominators."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.audience_segments import build_segment_reference, family_cells, prepare_segments
from app_core.family_affinity import affinity_metadata, load_family_definition, player_family_affinity
from app_core.family_audience import breadth_summary, family_catalogue, known_mix, primary_categories
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
from app_core.story import STORY_PAGES
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


@pytest.fixture
def audience():
    definition = load_family_definition()
    exclusive = {definition.family_order[indexes[0]]: key for key, indexes in definition.champion_families.items() if len(indexes) == 1}
    shared = next(key for key, indexes in definition.champion_families.items() if len(indexes) > 1)
    cases = [player_family_affinity([{'key': exclusive[fid], 'points': 50000}], definition) for fid in ['F01', 'F02']]
    cases += [player_family_affinity([{'key': shared, 'points': 50000}], definition),
              player_family_affinity([], definition), player_family_affinity([{'key': shared, 'points': 100}], definition)]
    rows = []
    for tier in ['BRONZE', 'GOLD', 'EMERALD', 'DIAMOND']:
        for activity in [100000, 1000000, 2000000, 3000000, 5000000]:
            for index in range(200):
                rows.append({**cases[index % 5], 'tier': tier, 'lifetime_mastery_points': activity,
                             'total_games': 10 if index % 2 else 600, 'oldest_retained_play_days': 100 if index % 2 else 700,
                             'main_role': ['Top', 'Jungle', 'Middle', 'Bottom', 'Support'][(index // 5) % 5],
                             'lifetime_playstyle': ['specialist', 'multispecialist', 'versatile', 'generalist'][index % 4]})
    raw = pd.DataFrame(rows).assign(region='na1', queue='RANKED_SOLO_5x5', as_of_date='2026-10-20', snapshot_date='2026-10-20')
    raw.attrs['family_affinity'] = affinity_metadata(definition)
    ref = build_segment_reference(raw, 'fixture')
    with patch('app_core.story.load_dataset', return_value=raw), patch('app_core.audience_story.load_segment_reference', return_value=ref):
        yield prepare_segments(raw, ref)[0], ref


def family_app(language='EN', terms='Plain'):
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.session_state[LANGUAGE_KEY] = language
    app.session_state[TERMINOLOGY_KEY] = terms
    app.run().switch_page(STORY_PAGES[3][0]).run()
    return app


def chart(app, position=1):
    return json.loads(app.get('plotly_chart')[position].proto.spec)


def matrix(app):
    return np.asarray(chart(app)['data'][0]['z'], dtype=float)


def test_exclusive_categories_other_and_known_trait_denominators(audience):
    frame, _ = audience
    ids = list(family_catalogue())
    full, collapsed = primary_categories(frame, ids), primary_categories(frame, ids, ['F01'])
    assert full.share.sum() == pytest.approx(1) and collapsed.share.sum() == pytest.approx(1)
    for category in ['F01', 'Other families', 'Shared top', 'No active pool', 'Insufficient mastery']:
        assert collapsed.set_index('family_category').loc[category, 'share'] == pytest.approx(.2)
    primary = frame.loc[frame.primary_family_id.eq('F01')].copy()
    primary.loc[primary.index[:100], 'character_type'] = 'Unavailable'
    mix, coverage = known_mix(primary, 'character_type', list('ABCDE'))
    assert mix.share.sum() == pytest.approx(1)
    assert coverage == pytest.approx(primary.loc[primary.character_type.ne('Unavailable'), 'population_weight'].sum() / primary.population_weight.sum())
    assert breadth_summary(primary) == {'scored_characters': 1, 'positive_families': 1}
    assert breadth_summary(frame.loc[frame.family_state.eq('shared_top')])['positive_families'] > 1


@pytest.mark.parametrize('language,terms', [('EN', 'Plain'), ('EN', 'League'), ('PT', 'Plain'), ('PT', 'League')])
def test_actual_vectors_and_full_base_in_all_presentation_modes(audience, language, terms):
    frame, _ = audience
    app = family_app(language, terms)
    assert not app.exception and len(app.get('plotly_chart')) == 3
    chosen = app.selectbox(key='story_family_choice').value
    expected = family_cells(frame, chosen, ['activity_band', 'rank_group']).pivot(
        index='rank_group', columns='activity_band', values='affinity_estimate').loc[['Lowest', 'Medium', 'High', 'Highest']].to_numpy()
    np.testing.assert_allclose(matrix(app), expected)
    assert any(('60,0%' if language == 'PT' else '60.0%') in cap.value for cap in app.caption)
    assert app.session_state[LANGUAGE_KEY] == language and app.session_state[TERMINOLOGY_KEY] == terms
    assert app.radio(key='story_family_curiosity').value == 'Off'
    assert len(chart(app)['data'][0]['customdata'][0][0]) == 8
    assert app.button(key='story_previous_4') and app.button(key='story_next_4')


def test_primary_denominator_inversion_units_and_preferences(audience):
    app = family_app()
    app.selectbox(key='story_family_choice').set_value('F02').run()
    before = matrix(app)
    app.segmented_control(key='story_family_measure').set_value('Primary share').run()
    assert not app.exception and not np.allclose(before, matrix(app))
    primary = matrix(app)
    np.testing.assert_allclose(primary, .2)
    app.toggle(key='story_family_invert').set_value(True).run()
    app.segmented_control(key='story_family_units').set_value('Estimated hours').run()
    app.segmented_control(key='_dashboard_language_choice').set_value('PT').run()
    # The actual browser sends display strings, unlike AppTest's canonical
    # values. A translated selection must be pushed back over that boundary.
    assert app.selectbox(key='story_family_choice').proto.set_value
    assert 'personagens' in app.selectbox(key='story_family_choice').proto.raw_value
    app.segmented_control(key='_story_terminology_choice').set_value('League').run()
    assert not app.exception
    np.testing.assert_allclose(matrix(app), primary.T)
    assert app.segmented_control(key='story_family_measure').value == 'Primary share'
    assert app.selectbox(key='story_family_choice').value == 'F02'
    assert app.toggle(key='story_family_invert').value


def test_sparse_empty_and_measured_zero_are_different(audience):
    app = family_app()
    app.selectbox(key='story_family_engagement').set_value('E1').run()
    app.segmented_control(key='story_family_measure').set_value('Primary share').run()
    assert not app.exception and np.isnan(matrix(app)).all()
    app.selectbox(key='story_family_history').set_value('H5').run()
    assert not app.exception and np.isnan(matrix(app)).all()
    assert any('no supported map cells' in info.value for info in app.info)
    app.selectbox(key='story_family_history').set_value('All').run()
    app.selectbox(key='story_family_engagement').set_value('All').run()
    app.selectbox(key='story_family_choice').set_value('F25').run()
    assert not app.exception and np.isnan(matrix(app)).all()
    assert all(row[0] == 'No primary observations' for line in chart(app)['data'][0]['customdata'] for row in line)
    app.segmented_control(key='story_family_measure').set_value('Mean affinity').run()
    assert not app.exception
    np.testing.assert_allclose(matrix(app), 0)


def test_optional_focus_retains_four_classes_and_breadth_preserves_map(audience):
    app = family_app()
    original = matrix(app)
    app.radio(key='story_family_curiosity').set_value('Whole-history focus').run()
    assert not app.exception and len(app.get('plotly_chart')) == 4
    assert len(chart(app, 3)['data'][0]['x']) == 4
    np.testing.assert_allclose(matrix(app), original)
    app.radio(key='story_family_curiosity').set_value('Pool breadth').run()
    assert not app.exception and len(app.get('plotly_chart')) == 3
    np.testing.assert_allclose(matrix(app), original)
