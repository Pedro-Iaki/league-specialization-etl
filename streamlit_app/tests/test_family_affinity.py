"""Hand-computable affinity, source-quality, version and nullable-export contracts."""
from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from app_core.family_affinity import (
    COHORT_ID,
    DEFINITION_PATH,
    DEFINITION_SHA256,
    METRIC_ID,
    affinity_metadata,
    load_family_definition,
    player_family_affinity,
    prepare_family_definition,
)


@pytest.fixture
def payload():
    # Unequal family sizes, overlap, and a family with no audience in most examples.
    return {'schema_version': 1, 'cohort_id': 'test-families', 'families': [
        {'family_key': family, 'members': [{'character_key': key} for key in keys]}
        for family, keys in [('F01', [1, 2, 9, 10]), ('F02', [2, 3]), ('F03', [3, 4]), ('F04', [5])]]}


@pytest.fixture
def definition(payload):
    return prepare_family_definition(payload, definition_sha256='a' * 64)


def test_full_active_denominator_cutoff_and_overlap_are_hand_computable(definition):
    row = player_family_affinity([{'key': 1, 'points': 60000}, {'key': 2, 'points': 30000},
                                  {'key': 3, 'points': 10000}], definition)
    assert row['family_affinity'] == pytest.approx([.9, .3, 0, 0])
    assert sum(row['family_affinity']) == pytest.approx(1.2)  # not an additive vector
    assert row['family_category'] == row['primary_family_id'] == 'F01'
    assert row['family_state'] == 'primary'
    assert row['top_family_ids'] == ['F01'] and row['top_family_score'] == pytest.approx(.9)
    assert row['runner_up_family_ids'] == ['F02'] and row['runner_up_family_score'] == pytest.approx(.3)
    assert row['family_gap'] == pytest.approx(.6)
    assert row['active_pool_champion_count'] == 3 and row['active_pool_mastery_points'] == 100000
    assert row['eligible_pool_champion_count'] == row['scored_pool_champion_count'] == 2
    assert row['eligible_pool_mastery_points'] == row['scored_pool_mastery_points'] == 90000
    assert row['below_cutoff_mastery_points'] == 10000
    assert row['below_cutoff_mastery_share'] == pytest.approx(.1)
    assert row['scored_mastery_share'] == pytest.approx(.9)
    assert row['unmapped_mastery_share'] == 0 and not row['family_weighting_fallback']


def test_cutoff_is_inclusive_and_does_not_filter_the_denominator(definition):
    row = player_family_affinity([{'key': 1, 'points': 15000}, {'key': 3, 'points': 14999}], definition)
    assert row['family_affinity'] == pytest.approx([15000 / 29999, 0, 0, 0])
    assert row['active_pool_champion_count'] == 2 and row['eligible_pool_champion_count'] == 1
    assert row['below_cutoff_mastery_share'] == pytest.approx(14999 / 29999)
    assert row['runner_up_family_score'] == 0 and row['runner_up_family_ids'] == []
    assert row['family_gap'] == row['top_family_score']


def test_shared_single_champion_ties_despite_unequal_family_size(definition):
    row = player_family_affinity([{'key': 2, 'points': 90000}], definition)
    assert row['family_affinity'] == [1, 1, 0, 0]
    assert row['family_state'] == 'shared_top' and row['family_category'] == 'Shared top'
    assert row['primary_family_id'] is None
    assert row['top_family_ids'] == ['F01', 'F02']
    assert row['top_family_score'] == row['runner_up_family_score'] == 1
    assert row['runner_up_family_ids'] == [] and row['family_gap'] == 0


def test_second_place_ties_are_preserved_without_category_combinations(definition):
    row = player_family_affinity([{'key': 1, 'points': 60000}, {'key': 3, 'points': 30000}], definition)
    assert row['primary_family_id'] == 'F01'
    assert row['runner_up_family_ids'] == ['F02', 'F03']
    assert row['runner_up_family_score'] == pytest.approx(1 / 3)
    assert row['family_gap'] == pytest.approx(1 / 3)


def test_numerical_top_tolerance_and_display_rounding_do_not_create_a_leader(definition):
    # F01 and F04 differ by only 1e-13 in affinity.
    row = player_family_affinity([{'key': 1, 'points': 1e9}, {'key': 5, 'points': 1e9 + .0004}], definition)
    assert row['family_state'] == 'shared_top' and row['top_family_ids'] == ['F01', 'F04']
    different = player_family_affinity([{'key': 1, 'points': 1000001}, {'key': 5, 'points': 1000000}], definition)
    assert round(different['family_affinity'][0], 2) == round(different['family_affinity'][3], 2)
    assert different['family_state'] == 'primary' and different['primary_family_id'] == 'F01'


def test_zero_affinities_do_not_tie_with_tiny_positive_mass(definition):
    row = player_family_affinity([{'key': 1, 'points': 15000}, {'key': 9999, 'points': 1e20}], definition)
    assert 0 < row['top_family_score'] < 1e-12
    assert row['family_state'] == 'primary' and row['top_family_ids'] == ['F01']
    assert row['runner_up_family_ids'] == []


def test_unknown_and_below_cutoff_mass_are_disjoint_not_silently_renormalized(definition):
    row = player_family_affinity([{'key': 1, 'points': 30000}, {'key': 9999, 'points': 20000},
                                  {'key': 9998, 'points': 10000}], definition)
    assert row['family_affinity'] == [.5, 0, 0, 0]
    assert row['unknown_champion_count'] == 2
    assert row['eligible_pool_champion_count'] == 2 and row['scored_pool_champion_count'] == 1
    assert row['below_cutoff_mastery_share'] == pytest.approx(1 / 6)
    assert row['unmapped_mastery_share'] == pytest.approx(1 / 3)
    assert row['scored_mastery_share'] == .5
    assert math.fsum(row[name] for name in ['below_cutoff_mastery_share', 'unmapped_mastery_share',
                                           'scored_mastery_share']) == pytest.approx(1)


@pytest.mark.parametrize('members,state,available,count', [
    (None, 'unavailable_pool', False, None), ([], 'no_active_pool', True, 0),
    ([{'key': 1, 'points': 0}], 'insufficient_mastery', True, 1),
    ([{'key': 1, 'points': 14999}], 'insufficient_mastery', True, 1),
    ([{'key': 9999, 'points': 30000}], 'unmapped_pool', True, 1),
])
def test_non_scoring_states_are_null_not_zero_interest(definition, members, state, available, count):
    row = player_family_affinity(members, definition)
    assert row['family_state'] == state and row['active_pool_available'] is available
    assert row['active_pool_champion_count'] == count
    assert row['family_affinity'] is None and row['primary_family_id'] is None
    assert row['top_family_score'] is row['runner_up_family_score'] is row['family_gap'] is None
    assert row['top_family_ids'] == row['runner_up_family_ids'] == []
    assert row['family_weighting_fallback'] is False
    json.dumps(row, allow_nan=False)


def test_zero_total_keeps_counts_but_has_no_fabricated_equal_weight_fallback(definition):
    row = player_family_affinity([{'key': 1, 'points': 0}, {'key': 2, 'points': 0}], definition)
    assert row['family_state'] == 'insufficient_mastery'
    assert row['active_pool_champion_count'] == 2 and row['active_pool_mastery_points'] == 0
    assert row['below_cutoff_mastery_share'] is row['scored_mastery_share'] is row['unmapped_mastery_share'] is None


@pytest.mark.parametrize('members', [
    42, 'not a pool', {'key': 1, 'points': 30000}, [1], [{}], [{'key': 1}],
    [{'key': 0, 'points': 30000}], [{'key': True, 'points': 30000}], [{'key': 1., 'points': 30000}],
    [{'key': 1, 'points': None}], [{'key': 1, 'points': True}], [{'key': 1, 'points': '30000'}],
    [{'key': 1, 'points': -1}], [{'key': 1, 'points': float('nan')}],
    [{'key': 1, 'points': float('inf')}], [{'key': 1, 'points': float('-inf')}],
    [{'key': 1, 'points': 0}, {'key': 1, 'points': 0}],
    [{'key': 1, 'points': 1e308}, {'key': 2, 'points': 1e308}],
])
def test_bad_source_values_and_duplicate_join_rows_fail_loudly(definition, members):
    with pytest.raises((ValueError, TypeError)):
        player_family_affinity(members, definition)


def test_numpy_scalar_records_and_generator_input(definition):
    result = player_family_affinity(({'key': np.int64(k), 'points': np.int64(p)} for k, p in [(1, 30000), (5, 60000)]), definition)
    assert result['primary_family_id'] == 'F04'
    json.dumps(result, allow_nan=False)


def test_member_and_family_order_do_not_change_answers_or_mutate_inputs(payload, definition):
    members = [{'key': 3, 'points': 30000}, {'key': 1, 'points': 60000}, {'key': 9, 'points': 1}]
    original_members, original_payload = copy.deepcopy(members), copy.deepcopy(payload)
    expected = player_family_affinity(members, definition)
    changed = copy.deepcopy(payload)
    changed['families'].reverse()
    for family in changed['families']:
        family['members'].reverse()
    reordered = prepare_family_definition(changed, definition_sha256='a' * 64)
    assert player_family_affinity(list(reversed(members)), reordered) == expected
    assert affinity_metadata(reordered) == affinity_metadata(definition)
    assert members == original_members and payload == original_payload
    with pytest.raises(TypeError):
        definition.champion_families[100] = (0,)


@pytest.mark.parametrize('change', ['duplicate_id', 'duplicate_member', 'empty_members', 'bad_key', 'bad_schema', 'bad_id'])
def test_invalid_definitions_are_rejected(payload, change):
    if change == 'duplicate_id':
        payload['families'][1]['family_key'] = 'F01'
    elif change == 'duplicate_member':
        payload['families'][0]['members'].append({'character_key': 1})
    elif change == 'empty_members':
        payload['families'][0]['members'] = []
    elif change == 'bad_key':
        payload['families'][0]['members'][0]['character_key'] = 1.
    elif change == 'bad_schema':
        payload['schema_version'] = True
    else:
        payload['families'][0]['family_key'] = 'arbitrary'
    with pytest.raises(ValueError):
        prepare_family_definition(payload, definition_sha256='a' * 64)


def test_frozen_definition_identity_and_versioned_metadata(tmp_path):
    definition = load_family_definition()
    assert definition.cohort_id == COHORT_ID
    assert definition.family_order == tuple(f'F{i:02}' for i in range(1, 26))
    assert len(definition.champion_families) == 173
    assert definition.sha256 == hashlib.sha256(DEFINITION_PATH.read_bytes()).hexdigest() == DEFINITION_SHA256
    metadata = affinity_metadata(definition)
    assert metadata['metric_id'] == METRIC_ID and metadata['metric_version'] == 1
    assert metadata['family_order'] == list(definition.family_order)
    assert metadata['minimum_mastery'] == 15000 and metadata['tie_rtol'] == 0
    assert metadata['weighting_fallback'] is False
    assert set(metadata['null_vector_states']) == {
        'no_active_pool', 'insufficient_mastery', 'unmapped_pool', 'unavailable_pool'}
    json.dumps(metadata, allow_nan=False)
    changed = tmp_path / 'definition.json'
    changed.write_bytes(DEFINITION_PATH.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='SHA-256'):
        load_family_definition(changed)


def test_nullable_vector_and_category_fields_roundtrip_together_in_parquet(tmp_path):
    definition = load_family_definition()
    key = next(iter(definition.champion_families))
    rows = [player_family_affinity(pool, definition) for pool in [None, [], [{'key': key, 'points': 30000}],
                                                               [{'key': key, 'points': 100}]]]
    table = pa.Table.from_pylist(rows)
    metadata = affinity_metadata(definition)
    table = table.replace_schema_metadata({b'family_affinity': json.dumps(metadata).encode()})
    path = tmp_path / 'joint-profile-fields.parquet'
    pq.write_table(table, path)
    restored = pq.read_table(path)
    assert restored.to_pylist() == rows
    assert json.loads(restored.schema.metadata[b'family_affinity']) == metadata
    assert restored.column('family_affinity').null_count == 3


def test_random_pools_match_an_independent_scalar_formula_and_conserve_coverage(definition):
    random = np.random.default_rng(42)
    groups = {family: {key for key, indices in definition.champion_families.items() if index in indices}
              for index, family in enumerate(definition.family_order)}
    for _ in range(30):
        members = [{'key': key, 'points': int(random.integers(0, 100000))} for key in [1, 2, 3, 4, 5, 9, 9999]]
        row = player_family_affinity(members, definition)
        total = sum(member['points'] for member in members)
        expected = [sum(member['points'] for member in members
                        if member['points'] >= 15000 and member['key'] in keys) / total for keys in groups.values()]
        assert row['family_affinity'] == pytest.approx(expected, abs=1e-14)
        assert all(0 <= score <= 1 for score in row['family_affinity'])
        assert row['below_cutoff_mastery_share'] + row['unmapped_mastery_share'] + row['scored_mastery_share'] == pytest.approx(1)
