"""Synthetic customer metrics preserve cents, nonbuyers and exclusive audience rows."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.audience_segments import BAND_SPECS
from app_core.customer_audiences import customer_summary, family_customer_summary, prepare_customers
from app_core.data import DashboardDataError
from app_core.family_affinity import affinity_metadata, load_family_definition
from app_core.i18n import LANGUAGE_KEY, TERMINOLOGY_KEY
from app_core.story import STORY_PAGES
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


@pytest.fixture
def customers():
    metadata = affinity_metadata(load_family_definition())
    categories = ['F01', 'F01', 'F02', 'Shared top', 'No active pool', 'Insufficient mastery']
    frame = pd.DataFrame({
        'family_category': categories * 40,
        'family_state': ['primary', 'primary', 'primary', 'shared_top', 'no_active_pool', 'insufficient_mastery'] * 40,
        'primary_family_id': ['F01', 'F01', 'F02', None, None, None] * 40,
        'cash_purchase_count_60d': [1, 0, 1, 1, 0, 0] * 40,
        'cash_spent_usd_60d': [10., 0., 30., 20., 0., 0.] * 40,
        'audience_tier': ['BRONZE', 'BRONZE', 'DIAMOND', 'EMERALD', 'GOLD', 'GOLD'] * 40,
        'audience_main_role': ['Top', 'Top', 'Middle', 'Bottom', None, 'Support'] * 40,
        'audience_total_games': [10, 10, 150, 600, 0, 0] * 40,
        'audience_lifetime_mastery_points': [100000, 200000, 1000000, 2000000, 3000000, 5000000] * 40,
        'audience_oldest_retained_play_days': [100, 100, 700, 1400, 2000, 3000] * 40,
    }).assign(scenario_id='fixture', as_of_date='2026-09-29', snapshot_date='2026-09-29',
              purchase_window_start='2026-08-01', purchase_window_end='2026-09-29',
              audience_as_of_date='2026-10-20', audience_snapshot_date='2026-10-18',
              audience_region='na1', audience_queue='RANKED_SOLO_5x5', tier='SILVER', lifetime_mastery_points=1)
    frame.attrs['family_affinity'] = metadata
    frame.attrs['business_scenario'] = {'scenario_id': 'fixture', 'player_count': len(frame),
        'as_of_date': '2026-09-29', 'purchase_window_start': '2026-08-01', 'purchase_window_end': '2026-09-29',
        'generator_version': '1.2', 'generator_seed': 42}
    reference = {'family_affinity': metadata, 'as_of_date': '2026-10-20',
                 'scope': {'region': 'na1', 'queue': 'RANKED_SOLO_5x5'}, 'bands': copy.deepcopy(BAND_SPECS)}
    with patch('app_core.customer_story.load_optional_dataset', return_value=frame), \
            patch('app_core.customer_story.load_segment_reference', return_value=reference):
        yield frame, reference


def customer_app(language='EN', terminology='Plain'):
    app = AppTest.from_file(str(APP), default_timeout=60)
    app.session_state[LANGUAGE_KEY] = language
    app.session_state[TERMINOLOGY_KEY] = terminology
    return app.run().switch_page(STORY_PAGES[4][0]).run()


def plots(app):
    return [json.loads(item.proto.spec) for item in app.get('plotly_chart')]


def test_cash_ratios_nonbuyers_and_exclusive_accounting_ignore_gameplay_weights(customers):
    frame, reference = customers
    base = prepare_customers(frame, reference)
    summary = family_customer_summary(base, list(load_family_definition().family_order)).set_index('family_category')
    assert summary.profiles.sum() == len(frame) == 240
    assert summary.cash_purchasers.sum() == 120
    assert summary.cash_cents.sum() == 240000
    assert summary.loc['F01', 'purchaser_share'] == .5 and summary.loc['F01', 'cash_per_purchaser'] == 10
    assert summary.loc['No active pool', 'purchaser_share'] == 0
    assert np.isnan(summary.loc['No active pool', 'cash_per_purchaser'])
    assert summary.audience_share.sum() == pytest.approx(1) and summary.cash_share.sum() == pytest.approx(1)
    weighted = family_customer_summary(base.assign(population_weight=np.arange(len(base)) + 1), list(load_family_definition().family_order))
    pd.testing.assert_frame_equal(weighted.set_index('family_category'), summary)
    other = family_customer_summary(base, list(load_family_definition().family_order), ['F01']).set_index('family_category')
    assert other.loc['Other families', 'cash_cents'] == 120000
    assert other.cash_cents.sum() == summary.cash_cents.sum()
    assert base.rank_group.iloc[0] == 'Lowest' and base.activity_band.iloc[0] == 'A1'
    assert frame.tier.eq('SILVER').all() and frame.lifetime_mastery_points.eq(1).all()


def test_cents_and_invalid_money_dates_or_metadata_are_explicit(customers):
    frame, reference = customers
    amounts = frame.copy()
    amounts.loc[amounts.cash_purchase_count_60d.eq(1), 'cash_spent_usd_60d'] = .10
    total = customer_summary(prepare_customers(amounts, reference).assign(group='All'), ['group'])
    assert total.cash_cents.iloc[0] == 1200
    for column, value in [('cash_spent_usd_60d', .105), ('cash_purchase_count_60d', -1),
                          ('audience_as_of_date', '2026-09-29'), ('purchase_window_end', '2026-10-20')]:
        broken = frame.copy()
        broken.loc[0, column] = value
        with pytest.raises(ValueError):
            prepare_customers(broken, reference)
    broken = frame.copy()
    broken.attrs.pop('family_affinity')
    with pytest.raises(ValueError, match='family-enriched'):
        prepare_customers(broken, reference)


def test_sparse_purchaser_support_masks_estimates_without_changing_totals(customers):
    raw, reference = customers
    frame = prepare_customers(raw, reference)
    selected = frame.loc[frame.family_category.eq('F01')].head(40)
    summary = customer_summary(selected, ['family_category']).iloc[0]
    assert summary.profiles == 40 and summary.cash_purchasers == 20
    assert summary.purchaser_estimate == .5 and summary.cash_per_purchaser == 10
    assert np.isnan(summary.cash_per_purchaser_estimate)
    thin = customer_summary(frame.head(12), ['family_category'])
    assert thin.purchaser_estimate.isna().all()
    assert thin.cash_per_purchaser_estimate.isna().all()
    assert thin.audience_share.sum() == pytest.approx(1) and thin.cash_share.sum() == pytest.approx(1)


@pytest.mark.parametrize('language,terms', [('EN', 'Plain'), ('EN', 'League'), ('PT', 'Plain'), ('PT', 'League')])
def test_customer_charts_in_all_presentation_modes_have_same_numbers(customers, language, terms):
    app = customer_app(language, terms)
    assert not app.exception and len(plots(app)) == 3
    charts = plots(app)
    np.testing.assert_allclose(charts[0]['data'][0]['x'], [.5, 1, 1, 0, 0])
    np.testing.assert_allclose(np.asarray(charts[1]['data'][0]['x'], dtype=float), [10, 30, 20, np.nan, np.nan], equal_nan=True)
    assert sum(charts[2]['data'][0]['x']) == pytest.approx(1)
    assert sum(charts[2]['data'][1]['x']) == pytest.approx(1)
    assert [metric.value for metric in app.metric] == (['100,0%', '50,0%', 'US$ 20,00'] if language == 'PT' else ['100.0%', '50.0%', '$20.00'])
    assert app.session_state[LANGUAGE_KEY] == language and app.session_state[TERMINOLOGY_KEY] == terms
    if language == 'PT':
        assert any('Explore públicos com compras simuladas' in value.value for value in app.markdown)
    assert app.button(key='story_previous_5') and app.button(key='story_next_5')


def test_refinements_fixed_bands_zero_cash_empty_and_translated_selection(customers):
    app = customer_app()
    app.selectbox(key='story_customer_lens').set_value('Accumulated activity').run()
    app.selectbox(key='story_customer_activity_band').set_value('A1').run()
    assert not app.exception
    assert app.metric[0].value == '33.3%' and app.metric[1].value == '50.0%'
    app.segmented_control(key='_dashboard_language_choice').set_value('PT').run()
    app.segmented_control(key='_story_terminology_choice').set_value('League').run()
    assert not app.exception and app.selectbox(key='story_customer_activity_band').value == 'A1'
    app.selectbox(key='story_customer_lens').set_value('Rank group').run()
    app.selectbox(key='story_customer_rank_group').set_value('Medium').run()
    assert not app.exception
    assert app.metric[1].value == '0,0%' and app.metric[2].value == 'Indisponível'
    app.selectbox(key='story_customer_lens').set_value('Recorded ranked volume').run()
    app.selectbox(key='story_customer_engagement_band').set_value('E2').run()
    assert not app.exception and app.metric[0].value == '0,0%'
    assert np.isnan(np.asarray(plots(app)[0]['data'][0]['x'], dtype=float)).all()
    app.selectbox(key='story_customer_lens').set_value('Character type').run()
    app.selectbox(key='story_customer_character_type').set_value('Unavailable').run()
    assert not app.exception and app.metric[0].value == '16,7%'


def test_missing_business_or_reference_keeps_navigation(customers):
    app = customer_app()
    for target, settings in [('load_optional_dataset', {'return_value': None}),
                             ('load_segment_reference', {'side_effect': DashboardDataError('mismatched reference')})]:
        with patch(f'app_core.customer_story.{target}', **settings):
            app.run()
        assert not app.exception and not app.get('plotly_chart')
        assert app.button(key='story_previous_5') and app.button(key='story_next_5')
