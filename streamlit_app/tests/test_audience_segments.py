"""Frozen wider cohorts, honest affinity coverage and weighted map denominators."""
from __future__ import annotations

import copy
import hashlib
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core import data
from app_core.audience_segments import (
    BAND_SPECS,
    assign_bands,
    band_order,
    build_segment_reference,
    family_cells,
    load_segment_reference,
    prepare_segments,
    rank_context,
    segment_counts,
)
from app_core.data import DashboardDataError
from app_core.family_affinity import affinity_metadata, load_family_definition
from app_core.snapshot_hash import sha256_file


@pytest.fixture
def profiles():
    frame = pd.DataFrame({
        'region': ['na1'] * 120, 'queue': ['RANKED_SOLO_5x5'] * 120,
        'tier': ['BRONZE'] * 60 + ['DIAMOND'] * 60, 'as_of_date': '2026-10-20',
        'lifetime_mastery_points': [100000, 600000, 600001, 5000000] * 30,
        'total_games': [0, 24, 25, np.nan] * 30, 'oldest_retained_play_days': [0, 365, 366, None] * 30,
        'main_role': [None] * 120, 'family_state': ['no_active_pool'] * 120,
        'family_category': ['No active pool'] * 120, 'primary_family_id': [None] * 120,
        'family_affinity': [None] * 120,
    })
    frame.attrs['family_affinity'] = affinity_metadata(load_family_definition())
    return frame


def test_wider_base_keeps_empty_pool_missing_type_history_and_focus(profiles):
    reference = build_segment_reference(profiles, 'hash')
    frame, diagnostics = prepare_segments(profiles, reference)
    assert len(frame) == 120 and frame.population_weight.notna().all()
    assert frame.character_type.eq('Unavailable').all()
    assert frame.engagement_band.value_counts().to_dict() == {'E0': 30, 'E1': 30, 'E2': 30, 'Missing': 30}
    assert frame.family_state.eq('no_active_pool').all()
    assert len(diagnostics) == 10
    with pytest.raises(ValueError, match='complete matching'):
        prepare_segments(profiles.head(20), reference)


def test_fixed_bands_include_boundaries_and_never_depend_on_filter_or_order(profiles):
    reference = build_segment_reference(profiles, 'hash')
    prepared, _ = prepare_segments(profiles, reference)
    assert prepared.activity_band.iloc[:4].tolist() == ['A1', 'A1', 'A2', 'A5']
    subset = prepared.iloc[[8, 3, 5]]
    pd.testing.assert_series_equal(assign_bands(subset, reference).activity_band, subset.activity_band)
    shuffled, _ = prepare_segments(profiles.sample(frac=1, random_state=3), reference)
    pd.testing.assert_series_equal(prepared.activity_band, shuffled.sort_index().activity_band)
    assert band_order(reference, 'engagement_band') == ['E0', 'E1', 'E2', 'E3', 'E4', 'E5', 'Missing']


def test_zero_missing_negative_infinite_are_not_conflated(profiles):
    reference = build_segment_reference(profiles, 'hash')
    profiles['lifetime_mastery_points'] = profiles.lifetime_mastery_points.astype(float)
    profiles.loc[:3, 'lifetime_mastery_points'] = [0., -1., np.inf, np.nan]
    assert assign_bands(profiles, reference).activity_band.iloc[:4].tolist() == ['A0', 'Missing', 'Missing', 'Missing']


def test_weights_remain_inherited_after_selection_and_support_is_not_imputed(profiles):
    reference = build_segment_reference(profiles, 'hash')
    frame, _ = prepare_segments(profiles, reference)
    selected = frame.iloc[[0, 1, 60]].copy()
    summary = segment_counts(selected, ['rank_group'])
    expected = .1660 / (.1660 + .0368 / 2)
    assert summary.set_index('rank_group').loc['Lowest', 'share'] == pytest.approx(expected)
    assert summary.share.sum() == pytest.approx(1)
    context = rank_context(reference)
    assert context.reference_share.sum() == pytest.approx(1)
    assert context.supported_share.sum() == pytest.approx(.1660 + .0368)
    assert context.unsupported_share.sum() == pytest.approx(1 - .1660 - .0368)


def test_conditional_denominator_and_transpose_preserve_statistic():
    frame = pd.DataFrame({'rank_group': ['Lowest', 'Lowest', 'Highest', 'Highest'],
                          'activity_band': ['A1', 'A2', 'A1', 'A2'], 'population_weight': [2., 1., 3., 4.]})
    first = segment_counts(frame, ['activity_band', 'rank_group'], conditional_on=['rank_group'])
    flipped = segment_counts(frame, ['rank_group', 'activity_band'], conditional_on=['rank_group'])
    assert first.groupby('rank_group').share.sum().eq(1).all()
    assert first.set_index(['activity_band', 'rank_group']).loc[('A1', 'Lowest'), 'share'] == pytest.approx(2 / 3)
    for key, row in first.set_index(['rank_group', 'activity_band']).iterrows():
        assert row.share == flipped.set_index(['rank_group', 'activity_band']).loc[key, 'share']
    joint = segment_counts(frame, ['activity_band', 'rank_group'])
    assert joint.share.sum() == pytest.approx(1)
    assert joint.set_index(['activity_band', 'rank_group']).loc[('A1', 'Lowest'), 'share'] == pytest.approx(.2)


def test_suppression_keeps_denominators_and_missing_categories():
    frame = pd.DataFrame({'kind': ['common'] * 40 + ['small'] + [None], 'population_weight': 1.})
    levels = {'kind': ['common', 'small', 'Missing', 'empty']}
    result = segment_counts(frame, ['kind'], levels=levels).set_index('kind')
    assert result.loc['common', 'estimate'] == pytest.approx(40 / 42)
    assert result.loc['small', 'status'] == 'sparse' and pd.isna(result.loc['small', 'estimate'])
    assert result.loc['small', 'share'] == pytest.approx(1 / 42)
    assert result.loc['empty', 'status'] == 'empty' and result.loc['empty', 'share'] == 0
    assert result.denominator_weight.eq(42).all()
    assert result.share.sum() == pytest.approx(1)
    with pytest.raises(ValueError, match='cannot drop'):
        segment_counts(frame, ['kind'], levels={'kind': ['common']})


def test_effective_support_masks_dominating_weights_even_with_enough_rows():
    frame = pd.DataFrame({'kind': ['x'] * 40, 'population_weight': [1000.] + [1.] * 39})
    result = segment_counts(frame, ['kind']).iloc[0]
    assert result.profiles == 40 and result.effective_players < 2
    assert result.status == 'sparse' and pd.isna(result.estimate)


def test_affinity_means_mask_unavailable_but_keep_measured_zero_and_overlap(profiles):
    frame, _ = prepare_segments(profiles, build_segment_reference(profiles, 'hash'))
    frame['population_weight'] = 1.
    vector = [1., 1.] + [0.] * 23
    for i in range(40):
        frame.at[i, 'family_affinity'] = vector.copy()
        frame.at[i, 'family_state'] = 'shared_top'
        frame.at[i, 'family_category'] = 'Shared top'
    for i in range(40, 80):
        frame.at[i, 'family_affinity'] = [0., 1.] + [0.] * 23
        frame.at[i, 'family_state'] = 'primary'
        frame.at[i, 'family_category'] = frame.at[i, 'primary_family_id'] = 'F02'
    first = family_cells(frame, 'F01', []).iloc[0]
    second = family_cells(frame, 'F02', []).iloc[0]
    assert first.scored_coverage == pytest.approx(2 / 3)
    assert first.mean_affinity == pytest.approx(.5) and second.mean_affinity == 1
    assert first.primary_share == 0 and second.primary_share == pytest.approx(1 / 3)
    assert pd.isna(first.primary_estimate) and second.primary_estimate == pytest.approx(1 / 3)
    assert first.mean_affinity + second.mean_affinity == 1.5
    exclusive = segment_counts(frame, ['family_category'])
    assert exclusive.share.sum() == pytest.approx(1)
    assert set(exclusive.family_category) == {'Shared top', 'F02', 'No active pool'}


def test_missing_weights_cannot_silently_fall_back_to_sample_and_duplicate_indices_are_safe():
    with pytest.raises(ValueError, match='frozen'):
        segment_counts(pd.DataFrame({'x': ['a']}), ['x'])
    frame = pd.DataFrame({'x': ['a', 'a', 'b'], 'population_weight': [1., np.nan, 3.]}, index=[4, 4, 4])
    result = segment_counts(frame, ['x']).set_index('x')
    assert result.loc['a', 'share'] == .25 and result.loc['b', 'share'] == .75


def test_empty_selection_has_no_fabricated_family_estimate(profiles):
    frame, _ = prepare_segments(profiles, build_segment_reference(profiles, 'hash'))
    assert family_cells(frame.iloc[:0], 'F01', []).empty
    result = segment_counts(frame.iloc[:0], ['rank_group'], levels={'rank_group': ['Lowest', 'Highest']})
    assert result.status.eq('empty').all() and result.share.isna().all() and result.estimate.isna().all()


@pytest.mark.parametrize('change', ['family', 'bands', 'reference', 'policy'])
def test_frozen_contract_rejects_incompatible_inputs(profiles, change):
    reference = build_segment_reference(profiles, 'hash')
    if change == 'family':
        reference['family_affinity']['metric_version'] = 999
    elif change == 'bands':
        reference['bands']['activity_band']['right_closed_cuts'][0] = 1
    elif change == 'reference':
        reference['rank_reference'][0]['source'] = 'different'
    else:
        reference['minimum_players'] = 1
    with pytest.raises(ValueError):
        prepare_segments(profiles, reference)
    assert BAND_SPECS['activity_band']['right_closed_cuts'][0] == 600000


def test_multiple_or_wrong_population_scopes_are_rejected(profiles):
    profiles.loc[0, 'region'] = 'br1'
    with pytest.raises(ValueError, match='one documented'):
        build_segment_reference(profiles, 'hash')
    profiles['region'] = 'br1'
    with pytest.raises(ValueError, match='NA ranked'):
        build_segment_reference(profiles, 'hash')


def test_reference_loader_checks_actual_snapshot_and_manifest(tmp_path, profiles):
    file = tmp_path / 'player_profiles.parquet'
    profiles.to_parquet(file, index=False)
    reference = build_segment_reference(profiles, hashlib.sha256(file.read_bytes()).hexdigest())
    path = tmp_path / 'audience_segments_reference.json'
    path.write_text(json.dumps(reference), encoding='utf-8')
    manifest = {'audience_segments_reference': {'sha256': sha256_file(path, normalize_newlines=True)}}
    with patch.object(data, 'DATA_DIR', tmp_path), patch.object(data, 'load_manifest', return_value=manifest):
        assert load_segment_reference() == reference
        reference['source_profile_sha256'] = 'wrong'
        path.write_text(json.dumps(reference), encoding='utf-8')
        with pytest.raises(DashboardDataError, match='manifest'):
            load_segment_reference()
        with patch.object(data, 'load_manifest', return_value={}), \
                pytest.raises(DashboardDataError, match='different player snapshot'):
            load_segment_reference()


def test_build_reference_does_not_mutate_source_or_global_bands(profiles):
    before = profiles.copy(deep=True)
    reference = build_segment_reference(profiles, 'hash')
    reference['bands']['activity_band']['right_closed_cuts'][0] = 10
    pd.testing.assert_frame_equal(profiles, before)
    assert BAND_SPECS == copy.deepcopy(build_segment_reference(profiles, 'hash')['bands'])
