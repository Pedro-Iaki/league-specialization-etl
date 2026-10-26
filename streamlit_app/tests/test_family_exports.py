"""Actual key association, strict public projection, loader versions and nullable exports."""
from __future__ import annotations

import copy
import hashlib
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core import data
from app_core.business import BUSINESS_PUBLIC_COLUMNS
from app_core.family_affinity import AFFINITY_COLUMNS, affinity_metadata, load_family_definition
from app_core.family_exports import (
    BUSINESS_AUDIENCE_COLUMNS,
    HISTORY_COLUMNS,
    PROFILE_AUDIENCE_COLUMNS,
    PROFILE_CONTEXT_COLUMNS,
    attach_business_audience,
    prepare_private_profiles,
    validate_family_frame,
)
from app_core.population import population_weights
from scripts import export_data
from scripts.export_data import validate_public_frame


@pytest.fixture
def definition():
    return load_family_definition()


@pytest.fixture
def private_source(definition):
    row = {key: None for key in [*PROFILE_CONTEXT_COLUMNS, *HISTORY_COLUMNS]}
    row.update(as_of_date='2026-10-20', snapshot_date='2026-10-19', region='NA', queue='RANKED_SOLO_5x5',
               tier='GOLD', tier_order=3, rank_score=1000, lifetime_mastery_points=100000,
               total_games=100, main_role='Middle', recent_playstyle='versatile', lifetime_playstyle='generalist',
               oldest_retained_play_at=pd.Timestamp('2019-01-01', tz='UTC'),
               oldest_retained_play_days=(pd.Timestamp('2026-10-20') - pd.Timestamp('2019-01-01')).days,
               _active_pool_available=True)
    keys = list(definition.champion_families)
    return pd.DataFrame([
        dict(row, player_id='actual-B', _active_members=[{'key': keys[1], 'points': 30000, 'name': 'B'}]),
        dict(row, player_id='actual-A', _active_members=[{'key': keys[0], 'points': 60000, 'name': 'A'}]),
        dict(row, player_id='actual-empty', _active_members=[]),
    ], index=[8, 8, 2])


@pytest.fixture
def private_profiles(private_source, definition):
    return prepare_private_profiles(private_source, definition)


def public_profiles(private_profiles, definition):
    frame, _ = population_weights(private_profiles.drop(columns='player_id'))
    frame = frame.loc[:, list(PROFILE_AUDIENCE_COLUMNS)]
    frame.attrs['family_affinity'] = affinity_metadata(definition)
    return frame


def business_source():
    base = {column: None for column in BUSINESS_PUBLIC_COLUMNS}
    base.update(scenario_id='frozen', as_of_date='2026-09-29', snapshot_date='2026-09-29',
                purchase_window_start='2026-08-01', purchase_window_end='2026-09-29',
                tier='SILVER', main_role='Support', lifetime_mastery_points=50000,
                queue='RANKED_SOLO_5x5')
    return pd.DataFrame([dict(base, player_id=key, cash_spent_usd_60d=cash, cash_purchase_count_60d=count)
                         for key, cash, count in [('actual-A', 10., 1), ('missing', 0., 0), ('actual-B', 20., 2)]])


def test_joint_profiles_keep_actual_association_with_duplicate_dataframe_indices(private_source, private_profiles, definition):
    assert private_profiles.player_id.tolist() == ['actual-B', 'actual-A', 'actual-empty']
    assert private_profiles.active_pool_mastery_points.tolist() == [30000, 60000, 0]
    frame = public_profiles(private_profiles, definition)
    validate_public_frame('players', frame)
    assert 'player_id' not in frame and '_active_members' not in frame
    assert set(frame) == set(PROFILE_AUDIENCE_COLUMNS)
    assert len(private_source) == len(frame)


def test_business_matches_actual_keys_not_input_row_position_and_retains_frozen_traits(private_profiles, definition):
    original = business_source()
    result = attach_business_audience(original, private_profiles, definition)
    assert len(result) == 3 and result.cash_spent_usd_60d.sum() == 30
    assert result.cash_purchase_count_60d.eq(0).sum() == 1  # nonbuyer retained
    assert result.tier.tolist() == ['SILVER'] * 3
    assert result.audience_tier.iloc[0] == 'GOLD'
    assert result.main_role.iloc[0] == 'Support' and result.audience_main_role.iloc[0] == 'Middle'
    assert result.as_of_date.iloc[0] == '2026-09-29' and result.audience_as_of_date.iloc[0] == '2026-10-20'
    assert result.active_pool_mastery_points.iloc[0] == 60000
    assert result.active_pool_mastery_points.iloc[2] == 30000
    assert result.family_state.iloc[1] == 'unavailable_pool'
    assert result.family_affinity.iloc[1] is None
    assert 'player_id' not in result and set(result) == set(BUSINESS_AUDIENCE_COLUMNS)
    validate_public_frame('business_players', result)
    reordered = attach_business_audience(original, private_profiles.iloc[::-1], definition)
    pd.testing.assert_frame_equal(result, reordered)


@pytest.mark.parametrize('kind', ['duplicate_profile', 'missing_key', 'blank_key', 'duplicate_member', 'missing_points', 'future_history'])
def test_bad_source_grain_values_or_history_fail_before_anonymization(private_source, definition, kind):
    source = private_source.reset_index(drop=True).copy(deep=True)
    if kind == 'duplicate_profile':
        source.loc[1, 'player_id'] = source.loc[0, 'player_id']
    elif kind == 'missing_key':
        source.loc[1, 'player_id'] = None
    elif kind == 'blank_key':
        source.loc[1, 'player_id'] = ''
    elif kind == 'duplicate_member':
        source.at[0, '_active_members'] = source.at[0, '_active_members'] * 2
    elif kind == 'missing_points':
        source.at[0, '_active_members'] = [{'key': 1, 'points': None}]
    else:
        source.loc[0, 'oldest_retained_play_at'] = pd.Timestamp('2030-01-01', tz='UTC')
    with pytest.raises((ValueError, TypeError)):
        prepare_private_profiles(source, definition)


def test_duplicate_business_key_is_not_silently_deduplicated(private_profiles, definition):
    source = business_source()
    with pytest.raises(ValueError, match='private keys'):
        attach_business_audience(pd.concat([source, source.iloc[[0]]]), private_profiles, definition)


@pytest.mark.parametrize('change', ['hash', 'metric', 'order', 'gap', 'vector', 'mass', 'unknown_column', 'label', 'availability'])
def test_export_validation_rejects_version_or_numerical_corruption(private_profiles, definition, change):
    frame = public_profiles(private_profiles, definition)
    metadata = copy.deepcopy(frame.attrs['family_affinity'])
    if change == 'hash':
        metadata['family_definition_sha256'] = 'b' * 64
    elif change == 'metric':
        metadata['metric_id'] = 'unreviewed'
    elif change == 'order':
        metadata['family_order'].reverse()
    elif change == 'gap':
        frame.loc[0, 'family_gap'] = 100
    elif change == 'vector':
        frame.at[0, 'family_affinity'] = [float('nan')] * 25
    elif change == 'mass':
        frame.loc[0, 'below_cutoff_mastery_share'] = 1
    elif change == 'unknown_column':
        frame['unreviewed'] = 'do not publish'
    elif change == 'label':
        frame.loc[2, 'family_category'] = 'a made up family'
    else:
        frame.loc[2, 'active_pool_available'] = False
    with pytest.raises(ValueError):
        validate_family_frame(frame, metadata)


def test_family_public_allowlist_rejects_accidental_private_fields(private_profiles, definition):
    frame = public_profiles(private_profiles, definition)
    for column in ['player_id', 'puuid', '_active_members', 'join_token']:
        with pytest.raises(ValueError):
            validate_public_frame('players', frame.assign(**{column: 'private'}))


def test_exported_nullable_vectors_roundtrip_and_loader_checks_manifest_hash(tmp_path, private_profiles, definition):
    frame = public_profiles(private_profiles, definition)
    path = tmp_path / 'player_profiles.parquet'
    frame.to_parquet(path, index=False)
    item = {'rows': len(frame), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'family_affinity': affinity_metadata(definition)}
    with patch.object(data, 'DATA_DIR', tmp_path), patch.object(data, 'load_manifest', return_value={'datasets': {'players': item}}):
        restored = data._validate_dataset('players', data._read_snapshot('players'))
        assert restored.family_state.tolist() == frame.family_state.tolist()
        assert restored.family_affinity.iloc[2] is None
        np.testing.assert_allclose(restored.family_affinity.iloc[0], frame.family_affinity.iloc[0])
        item['sha256'] = 'bad'
        with pytest.raises(data.DashboardDataError, match='hash/metadata'):
            data._read_snapshot('players')


def test_manifest_family_fields_must_match_the_data(private_profiles, definition):
    frame = public_profiles(private_profiles, definition)
    frame.attrs = {}
    with pytest.raises(data.DashboardDataError, match='metadata differs'):
        data._validate_dataset('players', frame)


def test_shared_schema_matches_every_helper_output(private_profiles):
    assert set(AFFINITY_COLUMNS).issubset(private_profiles)
    assert json.loads(json.dumps(list(AFFINITY_COLUMNS))) == list(AFFINITY_COLUMNS)


def test_real_export_orchestration_reuses_one_private_profile_query_and_strips_keys(tmp_path, private_source):
    class Cursor:
        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    def fetch(cursor, query):
        return private_source if 'active_members as' in query else business_source()

    metadata = {'scenario_id': 'frozen', 'player_count': 3}
    with patch.object(export_data, 'get_connection', return_value=Connection()), \
            patch.object(export_data, 'warehouse_metadata', return_value=metadata), \
            patch.object(export_data, 'fetch_frame', side_effect=fetch) as requests:
        manifest = export_data.export_snapshots(tmp_path, ['players', 'business_players'], family_audience=True)
    assert requests.call_count == 2
    for name, item in manifest['datasets'].items():
        file = tmp_path / item['file']
        assert item['sha256'] == hashlib.sha256(file.read_bytes()).hexdigest()
        frame = pd.read_parquet(file)
        assert 'player_id' not in frame and '_active_members' not in frame
        assert frame.attrs['family_affinity'] == item['family_affinity']
        validate_public_frame(name, frame)
    assert manifest['datasets']['business_players']['current_audience_matched_rows'] == 2
    assert manifest['datasets']['players']['population_reference']['sha256'] == export_data.reference_fingerprint(
        export_data.load_reference())
