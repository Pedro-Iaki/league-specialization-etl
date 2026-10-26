"""Frozen inference, keyed association and anonymous candidate boundaries."""
import copy
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core.archetype_serving import (
    IDS,
    coverage,
    describe_loadings,
    infer_loadings,
    load_model,
    model_metadata,
    pool_features,
    score_pools,
    select_archetype,
    validate_archetypes,
)
from app_core.family_affinity import load_family_definition
from app_core.family_exports import attach_business_audience, prepare_private_profiles
from test_family_exports import business_source, definition, private_source  # noqa: F401


def test_features_all_mastery_overlap_zero_and_unknown():
    definition = load_family_definition()  # noqa: F811
    keys = list(definition.champion_families)[:4]
    members = [{'key': k, 'points': p} for k, p in zip(keys, [60000, 10000, 0, 30000])]
    x, state, count = pool_features(members, definition)
    expected = np.zeros(25)
    for m in members:
        for f in definition.champion_families[m['key']]:
            expected[f] += m['points'] / 100000
    np.testing.assert_allclose(x, expected)
    assert (state, count) == ('scored', 4)
    zero = [{'key': k, 'points': 0} for k in keys]
    assert pool_features(zero, definition)[0].sum() > 0
    unknown = [{'key': 100000+i, 'points': 1} for i in range(4)]
    assert pool_features(unknown, definition)[1] == 'uncovered_pool'
    with pytest.raises(ValueError):
        pool_features(members + members, definition)


def test_fixed_inference_independent_of_cohort_and_no_fitting():
    model = load_model()
    x = np.array(model['profiles'])[[1, 5, 2]] * .7
    with patch('app_core.pool_archetypes.fit_archetypes', side_effect=AssertionError('No fitting')):
        together = infer_loadings(x, model)
        separately = np.concatenate([infer_loadings(row[None], model) for row in x])
    np.testing.assert_allclose(together, separately, rtol=0, atol=1e-12)


def test_ties_threshold_and_diffuse():
    model = load_model()
    tied = describe_loadings([.2,.2,0,0,0,0,0,0], model)
    assert tied['archetype_kind'] == 'Blend'
    assert tied['archetype_best_ids'] == ['A1','A2']
    assert tied['archetype_primary_id'] is None and tied['archetype_gap'] == 0
    diffuse = describe_loadings([.199,0,0,0,0,0,0,0], model)
    assert diffuse['archetype_kind'] == 'Diffuse' and diffuse['archetype_primary_id'] is None
    assert describe_loadings([1.1,0,0,0,0,0,0,0], model)['archetype_strength'] == 1.1


def test_null_states_roundtrip_and_selection(tmp_path):
    model = load_model()
    keys = list(load_family_definition().champion_families)[:4]
    pools = [None, [], [{'key': keys[0], 'points': 0}], [{'key': k, 'points': 0} for k in keys]]
    frame = score_pools(pools, model)
    assert frame.archetype_state.tolist() == ['unavailable_pool','empty_pool','below_minimum_pool','scored']
    frame.to_parquet(tmp_path / 'rows.parquet', index=False)
    restored = pd.read_parquet(tmp_path / 'rows.parquet')
    validate_archetypes(restored, model_metadata(model))
    for aid in IDS:
        assert select_archetype(restored, aid, 'expressed').sum() <= 1
    assert coverage(restored).share.sum() == 1
    restored['weight'] = [1.,2.,3.,4.]
    weighted = coverage(restored, 'weight').set_index('state')
    assert weighted.loc['scored', 'share'] == .4
    assert coverage(pd.DataFrame(index=range(2))).state.iloc[0] == 'unavailable_snapshot'
    broken = restored.copy()
    broken.at[3, 'archetype_kind'] = 'Diffuse'
    with pytest.raises(ValueError):
        validate_archetypes(broken, model_metadata(model))


def test_keyed_business_association(private_source, definition):  # noqa: F811
    model = load_model()
    private_source = private_source.reset_index(drop=True)
    keys = list(definition.champion_families)[:4]
    private_source.at[private_source.index[0], '_active_members'] = [
        {'key': k, 'name': str(k), 'points': 10000} for k in keys]
    profiles = prepare_private_profiles(private_source, definition, model)
    business = attach_business_audience(business_source(), profiles.iloc[::-1], definition)
    assert 'player_id' not in business
    assert business.archetype_state.tolist() == ['below_minimum_pool','unavailable_pool','scored']
    np.testing.assert_array_equal(business.archetype_loadings.iloc[2], profiles.archetype_loadings.iloc[0])
    validate_archetypes(business, model_metadata(model))
    assert business.cash_spent_usd_60d.tolist() == [10.,0.,20.]


def test_model_rejects_feature_and_name_drift(tmp_path):
    model = copy.deepcopy(load_model())
    for key, value in [('family_order', list(reversed(model['family_order']))), ('names', ['changed']*8)]:
        broken = dict(model, **{key: value})
        path = tmp_path / 'model.json'
        path.write_text(json.dumps(broken))
        with pytest.raises(ValueError):
            load_model(path)


def test_export_manifest_loader_and_tampering(tmp_path, private_source):  # noqa: F811
    from app_core import data
    from scripts import export_data

    class Connection:
        def cursor(self):
            return self

        def close(self):
            pass

    (tmp_path / 'manifest.json').write_text(json.dumps({'audience_segments_reference': {'retained': True}}))
    with patch.object(export_data, 'get_connection', return_value=Connection()), \
            patch.object(export_data, 'warehouse_metadata', return_value={'scenario_id': 'frozen', 'player_count': 3}), \
            patch.object(export_data, 'fetch_frame', side_effect=[private_source, business_source()]):
        manifest = export_data.export_snapshots(tmp_path, ['players','business_players'], pool_archetypes=True)
    assert manifest['audience_segments_reference'] == {'retained': True}
    with patch.object(data, 'DATA_DIR', tmp_path), patch.object(data, 'MANIFEST_PATH', tmp_path / 'manifest.json'):
        for name in ['players','business_players']:
            frame = data._validate_dataset(name, data._read_snapshot(name))
            assert 'player_id' not in frame and '_active_members' not in frame
        model_path = tmp_path / manifest['pool_archetypes']['file']
        model_path.write_text('{}')
        with pytest.raises(data.DashboardDataError, match='Archetype snapshot/model'):
            data._read_snapshot('players')
