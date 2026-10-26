from __future__ import annotations

import copy
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

pytest.importorskip('leidenalg')

from app_core.families import FamilySettings, scenario_payload
from app_core.family_cohort import candidate_library, fingerprint, merge_sources, new_draft, subset_scores, suggest_from_library
from app_core.family_hunter import (
    agreement_matrix, build_schedule, consensus_ensemble, hunt_step, library_payload, save_library, sweep_graph_settings, validate_library,
)
from app_core.population import WEIGHT, load_reference, reference_fingerprint


def test_library_names_increase_without_overwriting_existing_files(tmp_path):
    from app_core.family_hunter import next_library_path

    assert next_library_path(tmp_path, 'anchored').name == 'anchored-1.json'
    (tmp_path / 'anchored-2.json.gz').touch()
    (tmp_path / 'anchored-10.json.sources').mkdir()
    (tmp_path / 'anchored-abcdef123456.json').touch()
    assert next_library_path(tmp_path, 'anchored').name == 'anchored-11.json'
    first = save_library(tmp_path, {'value': 1})
    second = save_library(tmp_path, {'value': 2})
    assert (first.name, second.name) == ('hunter-1.json', 'hunter-2.json')
    assert json.loads(first.read_text()) == {'value': 1}


@pytest.fixture
def hunter_data():
    characters = pd.DataFrame({'character_key': list(range(10, 18)), 'character': list('ABCDEFGH')})
    points = np.zeros((40, 8))
    points[:20, :4] = 20000
    points[20:, 4:] = 20000
    base = pd.DataFrame({'tier': ['GOLD'] * 40, 'days_tracked': [60] * 40, WEIGHT: np.ones(40)})
    context = {'membership_sha256': 'snapshot', 'reference_sha256': reference_fingerprint(load_reference()),
               'tiers': ['GOLD'], 'maturity': 'All', 'excluded_keys': []}
    automatic = characters.assign(family=['AR01'] * 4 + ['AR02'] * 4)
    settings = FamilySettings(minimum_players=1, minimum_shared=1, minimum_similarity=.01, neighbors=3)
    scenario = scenario_payload(settings, context, automatic,
                                 {family: {'title': family} for family in ['AR01', 'AR02']}, '')
    step = {'name': 'Tight', 'presets': [{'name': 'good.json', 'scenario': scenario}],
            'anchors': characters.character_key.tolist(), 'runs': 4, 'resolution_spread': 0., 'neighbor_spread': 0}
    return base, characters, points, step, context


def test_seeded_schedule_preserves_presets_and_only_varies_requested_parameters(hunter_data):
    _, _, _, step, _ = hunter_data
    before = copy.deepcopy(step)
    fixed = build_schedule(step, 42)
    assert fixed == build_schedule(step, 42)
    assert len({row['settings']['seed'] for row in fixed}) == 4
    assert {row['settings']['resolution'] for row in fixed} == {1.}
    step.update(runs=100, resolution_spread=.2, neighbor_spread=2)
    varied = build_schedule(step, 42)
    assert all(np.exp(-.2) <= row['settings']['resolution'] <= np.exp(.2) for row in varied)
    assert set(row['settings']['neighbors'] for row in varied) == {1, 2, 3, 4, 5}
    assert step['presets'] == before['presets']


def test_fractional_graph_neighbors_scale_to_actual_window_and_leave_reference_unchanged(hunter_data):
    _, _, _, step, _ = hunter_data
    step = copy.deepcopy(step)
    step['neighbor_mode'] = 'fraction'
    scenario = step['presets'][0]['scenario']
    scenario['settings']['neighbors'] = 70
    scenario['assignments'] = [{}] * 173
    draw = build_schedule(step, 42)[0]
    assert draw['neighbor_fraction'] == pytest.approx(70 / 173)
    assert [sweep_graph_settings(draw, n + 1).neighbors for n in [15, 30, 60]] == [6, 12, 24]
    assert sweep_graph_settings(draw, 173).neighbors == 70
    assert sweep_graph_settings(draw, 2).neighbors == 1
    assert scenario['settings']['neighbors'] == 70
    assert sweep_graph_settings(dict(draw, neighbor_fraction=1.), 16).neighbors == 15
    legacy = dict(draw)
    legacy.pop('neighbor_fraction')
    assert sweep_graph_settings(legacy, 16).neighbors == 70


def test_consensus_threshold_removes_weak_links_and_unassigned_never_agree(hunter_data):
    from app_core.family_hunter import _partition_families as actual_partition
    base, _, points, step, _ = hunter_data
    labels = [np.array([0, 0, 1, 1, -1, -1, -1, -1]), np.array([5, 5, 2, -1, -1, -1, -1, -1])]
    matrix = agreement_matrix(labels)
    assert matrix[0, 1] == 1 and matrix[2, 3] == .5 and matrix[6, 7] == 0 and matrix[6, 6] == 0
    calls = []
    def partition(graph, weights, keys, settings, seed):
        calls.append(graph)
        if len(calls) <= 2:
            return labels[len(calls) - 1]
        assert graph.get_edgelist() == [(0, 1)]
        return actual_partition(graph, weights, keys, settings, seed)
    with patch('app_core.family_hunter._partition_families', side_effect=partition):
        result = consensus_ensemble(points, base[WEIGHT].to_numpy(), np.arange(8), build_schedule(dict(step, runs=2), 42), .75, 2, 1., 42)
    assert result['converged']
    assert result['labels'][0] == result['labels'][1] >= 0
    assert (result['labels'][2:] == -1).all()


def test_hunt_harvests_all_anchors_once_and_bootstraps_the_frozen_pipeline(hunter_data):
    base, characters, points, step, context = hunter_data
    from app_core.family_hunter import consensus_ensemble as actual
    inputs = []
    def traced(data, weights, keys, schedule, *args):
        inputs.append((data.copy(), copy.deepcopy(schedule)))
        return actual(data, weights, keys, schedule, *args)
    with patch('app_core.family_hunter.consensus_ensemble', side_effect=traced):
        source = hunt_step(base, characters, points, step, 'snapshot', bootstrap_repeats=3)
    assert len(inputs) == 4  # one discovery plus three whole-player resamples, not 8 anchor searches
    assert all(schedule == inputs[0][1] for _, schedule in inputs)
    assert any(not np.array_equal(data, points) for data, _ in inputs[1:])
    assert len(source['candidate_families']) == 2
    assert {tuple(row['member_keys']) for row in source['candidate_families']} == {tuple(range(10, 14)), tuple(range(14, 18))}
    assert all(row['ensemble_frequency'] == 1 and row['mean_recovery'] == 1 for row in source['candidate_families'])
    assert all(row['bootstrap_consistency'] == 1 for row in source['candidate_families'])
    reference = context['reference_sha256']
    payload = library_payload({fingerprint(source['scenario']): source}, 'snapshot', reference, 'Test')
    assert validate_library(json.loads(json.dumps(payload)), characters, 'snapshot', reference)['name'] == 'Test'


def test_anchor_scope_and_audience_validation(hunter_data):
    base, characters, points, step, _ = hunter_data
    restricted = dict(step, anchors=[10])
    source = hunt_step(base, characters, points, restricted, 'snapshot', bootstrap_repeats=2)
    assert len(source['candidate_families']) == 1
    assert source['candidate_families'][0]['anchors'] == [10]
    incompatible = copy.deepcopy(step)
    preset = copy.deepcopy(incompatible['presets'][0])
    preset['scenario']['source']['maturity'] = 'Under 30 days'
    incompatible['presets'].append(preset)
    with pytest.raises(ValueError, match='same rank tiers'):
        hunt_step(base, characters, points, incompatible, 'snapshot', bootstrap_repeats=2)


def test_library_merges_without_resetting_draft_and_rejects_tampered_evidence(hunter_data, tmp_path):
    base, characters, points, step, context = hunter_data
    source = hunt_step(base, characters, points, step, 'snapshot', bootstrap_repeats=2)
    source_id = fingerprint(source['scenario'])
    policy = {'family_target': .8, 'trim_fraction': .2, 'single_threshold': .8, 'shared_threshold': .4, 'separation_target': .2}
    sources = {source_id: source}
    candidates = candidate_library(sources, policy)
    assert len(candidates) == 2
    draft = new_draft(sources, characters, policy, 'snapshot', context['reference_sha256'], [candidates[0]])
    other = copy.deepcopy(source)
    other['scenario']['notes'] = 'Another definition'
    merged = merge_sources(draft, {fingerprint(other['scenario']): other})
    assert len(merged['sources']) == 2 and merged['selected'] == draft['selected'] and len(draft['sources']) == 1
    assert subset_scores(source, candidates[0]['member_keys'])[1] == 1
    for method in ['Target-size cover', 'Smallest available']:
        cover, selected = suggest_from_library(draft, dict(policy, selection_approach=method))
        assert cover['covered'] == 8 and len(selected) == 2
        cover, selected = suggest_from_library(draft, dict(policy, selection_approach=method, minimum_family_size=10))
        assert cover['covered'] == 0 and selected == []
    payload = library_payload(sources, 'snapshot', context['reference_sha256'], 'Test')
    path = save_library(tmp_path, payload)
    assert save_library(tmp_path, payload, path) == path and len(list(tmp_path.glob('*.json'))) == 1
    assert not list(tmp_path.glob('*.tmp'))
    altered = copy.deepcopy(payload)
    altered['sources'][source_id]['co_membership']['rates'][0][1] = .1
    with pytest.raises(ValueError, match='checksum'):
        validate_library(altered, characters, 'snapshot', context['reference_sha256'])


def test_hunter_ui_runs_then_reuses_saved_library_on_filter_changes(hunter_data, tmp_path):
    base, characters, points, step, context = hunter_data
    from app_core.family_hunter import hunt_step as actual
    (tmp_path / 'scenarios').mkdir()
    (tmp_path / 'membership.parquet').touch()
    (tmp_path / 'manifest.json').write_text('{}')
    scenario_path = tmp_path / 'scenarios' / 'good.json'
    scenario_path.write_text(json.dumps(step['presets'][0]['scenario']))
    before = scenario_path.read_bytes()
    script = 'from app_core.family_hunter_view import render_family_hunter\nrender_family_hunter()'
    app = AppTest.from_string(script, default_timeout=30)
    with patch('app_core.family_hunter_view.LOCAL_DIR', tmp_path), \
         patch('app_core.family_hunter_view._prepared', return_value=(base, characters, points, {}, {'sha256': 'snapshot'})), \
         patch('app_core.family_hunter.hunt_step', wraps=actual) as calls:
        app.run()
        assert not app.exception
        app.number_input(key='hunter_step_count').set_value(1).run()
        app.number_input(key='hunter_runs_0').set_value(3)
        app.number_input(key='hunter_bootstraps').set_value(2)
        app.button(key='hunter_run').click().run()
        assert not app.exception and calls.call_count == 1
        assert len(list((tmp_path / 'hunter').glob('*.json'))) == 1
        app.multiselect(key='hunter_result_characters').set_value([10]).run()
        app.selectbox(key='hunter_sort').set_value('size').run()
        app.button(key='hunter_use_library').click().run()
        assert not app.exception and calls.call_count == 1
        assert app.session_state['hunter_sources']
        assert scenario_path.read_bytes() == before


def test_completed_steps_are_saved_when_a_later_step_fails(hunter_data, tmp_path):
    base, characters, points, step, _ = hunter_data
    (tmp_path / 'scenarios').mkdir()
    (tmp_path / 'membership.parquet').touch()
    (tmp_path / 'manifest.json').write_text('{}')
    (tmp_path / 'scenarios' / 'good.json').write_text(json.dumps(step['presets'][0]['scenario']))
    source = hunt_step(base, characters, points, step, 'snapshot', bootstrap_repeats=2)
    app = AppTest.from_string('from app_core.family_hunter_view import render_family_hunter\nrender_family_hunter()', default_timeout=30)
    with patch('app_core.family_hunter_view.LOCAL_DIR', tmp_path), \
         patch('app_core.family_hunter_view._prepared', return_value=(base, characters, points, {}, {'sha256': 'snapshot'})), \
         patch('app_core.family_hunter.hunt_step', side_effect=[source, ValueError('deliberate failure'), ValueError('deliberate failure')]):
        app.run()
        app.button(key='hunter_run').click().run()
        assert not app.exception
        paths = list((tmp_path / 'hunter').glob('*.json'))
        assert len(paths) == 1
        payload = json.loads(paths[0].read_bytes())
        assert len(payload['sources']) == 1 and len(app.session_state['hunter_result']['errors']) == 2
        assert not payload['run_status']['complete'] and len(payload['run_status']['errors']) == 2
        assert any('partial' in warning.value for warning in app.warning)
