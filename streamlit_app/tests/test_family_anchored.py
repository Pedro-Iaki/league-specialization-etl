from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

pytest.importorskip('leidenalg')

from app_core.families import FamilySettings, scenario_payload
from app_core.family_anchored import (
    PairStatisticsPool, anchor_members, boundary_retention, candidate_neighborhood,
    hunt_anchor, run_anchored_sweep, stable_seed, sweep_request, validate_anchored_step, validate_resume,
)
from app_core.family_cohort import (
    candidate_library, cohort_payload, edit_members, new_draft,
    source_matrix, subset_scores, summarize_cohort, validate_cohort,
)
from app_core.family_hunter import build_schedule, decode_library, read_library_file, save_library, validate_library
from app_core.population import WEIGHT, load_reference, reference_fingerprint


@pytest.fixture
def anchored_data():
    characters = pd.DataFrame({'character_key': list(range(10, 18)), 'character': list('ABCDEFGH')})
    points = np.zeros((40, 8))
    points[:20, :4] = 20000
    points[20:, 4:] = 20000
    base = pd.DataFrame({'tier': ['GOLD'] * 40, 'days_tracked': [60] * 40, WEIGHT: np.ones(40)})
    reference = reference_fingerprint(load_reference())
    context = {'membership_sha256': 'snapshot', 'reference_sha256': reference,
               'tiers': ['GOLD'], 'maturity': 'All', 'excluded_keys': []}
    automatic = characters.assign(family=['AR01'] * 4 + ['AR02'] * 4)
    settings = FamilySettings(minimum_players=1, minimum_shared=1, minimum_similarity=.01, neighbors=3)
    scenario = scenario_payload(settings, context, automatic, {family: {'title': family} for family in ['AR01', 'AR02']}, '')
    step = {'id': 'tight', 'name': 'Tight', 'presets': [{'name': 'good.json', 'scenario': scenario}],
            'anchors': [10, 11, 14], 'runs': 3, 'resolution_spread': 0., 'neighbor_spread': 0,
            'candidate_neighbors': 3, 'second_degree_fraction': 0., 'core_connections': 2}
    return base, characters, points, step, reference


def request_for(step, reference, **overrides):
    return sweep_request([step], 'snapshot', reference, overrides.get('seed', 42),
                          overrides.get('repeats', 2), .5, 2, 1.)


def test_window_ranks_before_top_k_and_expansion_requires_multiple_core_links():
    weights = np.zeros((7, 7))
    for a, b, value in [(0, 1, .9), (0, 2, .8), (0, 3, .7), (1, 4, .8), (2, 4, .7), (1, 5, .9), (0, 6, .95)]:
        weights[a, b] = weights[b, a] = value
    raw = np.where(weights > 0, 10., 0.)
    np.fill_diagonal(raw, 100)
    raw[6, 6] = 0
    stats = {'raw': raw, 'jaccard': weights, 'adjusted': weights * 2}
    settings = FamilySettings(minimum_players=1, minimum_shared=1, minimum_similarity=.01, neighbors=1)
    direct = candidate_neighborhood(stats, np.arange(7), settings, [], 0, 3)
    assert direct['indices'] == [0, 1, 2, 3]  # graph top-K=1 did not truncate the input window
    expanded = candidate_neighborhood(stats, np.arange(7), settings, [], 0, 6, .5, 2)
    assert set(expanded['indices']) == {0, 1, 2, 3, 4}
    assert 5 not in expanded['indices'] and 6 not in expanded['indices']
    rows = pd.DataFrame(expanded['rows']).set_index('character_key')
    assert rows.loc[4, 'route'] == 'Second degree' and rows.loc[4, 'supporting_core'] == [1, 2]
    assert rows.loc[6, 'route'] == 'Below support / excluded'
    excluded = candidate_neighborhood(stats, np.arange(7), settings, [0], 0, 3)
    assert excluded['status'] == 'Unsupported / excluded' and excluded['indices'] == [0]


def test_anchor_changes_graph_and_has_independent_order_stable_draws(anchored_data):
    base, chars, points, step, _ = anchored_data
    pool = PairStatisticsPool(base, points, 42)
    from app_core.family_anchored import _partition_families as actual
    seen = []
    def record(graph, weights, keys, settings, seed):
        seen.append((tuple(keys), seed))
        return actual(graph, weights, keys, settings, seed)
    with patch('app_core.family_anchored._partition_families', side_effect=record):
        first = hunt_anchor(pool, chars, step, 10, 42, 2, .5, 2, 1.)['source']
        second = hunt_anchor(pool, chars, step, 14, 42, 2, .5, 2, 1.)['source']
    assert set(seen[0][0]) == set(range(10, 14))
    assert set(seen[9][0]) == set(range(14, 18))
    assert len(seen) == 2 * 3 * 3  # two independent anchors × three draws × discovery plus two samples
    assert set(first['co_membership']['character_keys']) == set(range(10, 14))
    assert set(second['co_membership']['character_keys']) == set(range(14, 18))
    assert pool.computations == 3  # aggregate matrices reused, searches were not skipped
    seed = stable_seed(42, 'search', step['id'], 10)
    original = build_schedule(step, seed)
    reordered = dict(step, anchors=[14, 10, 11])
    assert original == build_schedule(reordered, stable_seed(42, 'search', reordered['id'], 10))
    assert first['scenario']['anchored']['schedule'] != second['scenario']['anchored']['schedule']
    assert all(10 in family['member_keys'] for family in first['candidate_families'])


def test_bootstrap_rebuilds_window_and_recovery_cannot_match_an_unrelated_group(anchored_data):
    base, chars, points, step, _ = anchored_data
    pool = PairStatisticsPool(base, points, 42)
    from app_core.family_anchored import candidate_neighborhood as actual
    windows = []
    def record(*args, **kwargs):
        window = actual(*args, **kwargs)
        windows.append(window)
        return window
    with patch('app_core.family_anchored.candidate_neighborhood', side_effect=record):
        hunt_anchor(pool, chars, step, 10, 42, 3, .5, 2, 1.)
    assert len(windows) == 4
    result = {'keys': np.array([10, 11, 12, 13]), 'labels': np.array([-1, 0, 0, 0])}
    assert anchor_members(result) == set()
    result['labels'] = np.array([0, 1, 1, 1])
    assert anchor_members(result) == {10}


def test_anchored_policy_rejects_incompatible_relationship_definitions(anchored_data):
    _, chars, _, step, _ = anchored_data
    other = copy.deepcopy(step['presets'][0])
    other['scenario']['settings']['association'] = 'breadth_adjusted'
    with pytest.raises(ValueError, match='share mastery'):
        validate_anchored_step(dict(step, presets=step['presets'] + [other]), chars, 'snapshot')
    other['scenario']['settings']['association'] = 'jaccard'
    other['scenario']['settings']['resolution'] = 2.
    validate_anchored_step(dict(step, presets=step['presets'] + [other]), chars, 'snapshot')
    overridden = dict(step, resolution_override=.65)
    draws = build_schedule(overridden, 42)
    assert all(draw['settings']['resolution'] == .65 for draw in draws)
    assert step['presets'][0]['scenario']['settings']['resolution'] == 1.


def test_changing_bootstrap_boundary_counts_as_lost_recovery_not_unknown(anchored_data):
    _, chars, _, step, _ = anchored_data
    def stats_for(members):
        values = np.zeros((8, 8))
        values[np.ix_(members, members)] = .8
        np.fill_diagonal(values, 0)
        return {'raw': np.full((8, 8), 100.), 'jaccard': values, 'adjusted': values}
    original = stats_for([0, 1, 2])
    changed = stats_for([0, 1, 4])
    class Pool:
        def get(self, step, repeat):
            return (original if repeat == -1 else changed), 40
    source = hunt_anchor(Pool(), chars, dict(step, candidate_neighbors=2, resolution_override=.1), 10, 42, 2, .5, 2, 1.)['source']
    assert source['neighborhood_eligibility']['12'] == 0
    assert source['candidate_families'][0]['mean_recovery'] == .5
    fits, mean = subset_scores(source, [10, 11, 12])
    assert fits.set_index('character_key').loc[12, 'member_fit'] == 0
    assert mean == pytest.approx(1 / 3)
    assert np.isnan(source_matrix(source, [10, 17])[0, 1])


def test_full_network_boundary_retention_sees_external_connections():
    values = np.array([[0., .8, 0.], [.8, 0., 0.], [0., 0., 0.]])
    stats = {'raw': np.full((3, 3), 100.), 'jaccard': values, 'adjusted': values}
    settings = FamilySettings(minimum_players=1, minimum_shared=1)
    assert boundary_retention(stats, np.arange(3), settings, [], [0, 1]) == 1
    values[1, 2] = values[2, 1] = .8
    assert boundary_retention(stats, np.arange(3), settings, [], [0, 1]) == pytest.approx(2 / 3)


def test_compact_evidence_manual_unknowns_and_roundtrip(anchored_data, tmp_path):
    base, chars, points, step, reference = anchored_data
    result, path = run_anchored_sweep(base, chars, points, request_for(dict(step, anchors=[10]), reference), 'Test', tmp_path)
    assert len(result['sources']) == 1
    validate_library(read_library_file(path), chars, 'snapshot', reference)
    compressed = save_library(tmp_path, result, tmp_path / 'portable.json.gz')
    assert decode_library(compressed.read_bytes())['sources'] == result['sources']
    evidence = next(Path(str(path) + '.sources').glob('*.json'))
    original_bytes = evidence.read_bytes()
    evidence.write_bytes(original_bytes + b' ')
    with pytest.raises(ValueError, match='evidence checksum'):
        read_library_file(path)
    evidence.write_bytes(original_bytes)
    policy = {'family_target': .8, 'trim_fraction': .2, 'single_threshold': .8, 'shared_threshold': .4, 'separation_target': .2}
    candidates = candidate_library(result['sources'], policy)
    source = next(iter(result['sources'].values()))
    assert subset_scores(source, [10, 11, 12, 13])[1] == 1
    assert np.isnan(source_matrix(source, [10, 17])[0, 1])
    draft = new_draft(result['sources'], chars, policy, 'snapshot', reference, [candidates[0]])
    edited = edit_members(draft, candidates[0]['id'], candidates[0]['member_keys'] + [17], 'Gameplay rationale outside the evaluated window')
    assert np.isnan(summarize_cohort(edited)['families'].iloc[0].family_mean)
    validate_cohort(cohort_payload(edited), chars, 'snapshot', reference)
    assert not np.isnan(subset_scores(source, candidates[0]['member_keys'])[1])


def test_duplicate_families_do_not_skip_jobs_and_resume_preserves_completed_work(anchored_data, tmp_path):
    base, chars, points, step, reference = anchored_data
    request = request_for(dict(step, anchors=[10, 11]), reference)
    from app_core.family_anchored import hunt_anchor as actual
    calls = []
    def interrupt(*args, **kwargs):
        calls.append(args[3])
        if len(calls) == 2:
            raise KeyboardInterrupt()
        return actual(*args, **kwargs)
    with patch('app_core.family_anchored.hunt_anchor', side_effect=interrupt), pytest.raises(KeyboardInterrupt):
        run_anchored_sweep(base, chars, points, request, 'Interrupted', tmp_path)
    path = next(tmp_path.glob('anchored-*.json'))
    prior = read_library_file(path)
    assert prior['jobs']['tight:10']['status'] == 'Completed' and prior['jobs']['tight:11']['status'] == 'Pending'
    with patch('app_core.family_anchored.hunt_anchor', wraps=actual) as work:
        result, _ = run_anchored_sweep(base, chars, points, request, 'Resumed', tmp_path, prior, path)
    assert work.call_count == 1 and result['run_status']['complete'] and len(result['sources']) == 2
    assert len({tuple(f['member_keys']) for source in result['sources'].values() for f in source['candidate_families']}) == 1
    changed = request_for(dict(step, anchors=[10, 11]), reference, seed=43)
    with pytest.raises(ValueError, match='differs'):
        validate_resume(result, changed, chars)


def test_builder_accepts_compact_sources_and_renders_unknown_manual_members(anchored_data, tmp_path):
    base, chars, points, step, reference = anchored_data
    result, _ = run_anchored_sweep(base, chars, points, request_for(dict(step, anchors=[10]), reference), 'Test', tmp_path)
    policy = {'family_target': .8, 'trim_fraction': .2, 'single_threshold': .8, 'shared_threshold': .4, 'separation_target': .2}
    candidates = candidate_library(result['sources'], policy)
    draft = new_draft(result['sources'], chars, policy, 'snapshot', reference, [candidates[0]])
    draft = edit_members(draft, candidates[0]['id'], candidates[0]['member_keys'] + [17], 'Manual outside-window member')
    script = '''
import streamlit as st
from app_core.family_cohort_view import render_cohort_builder
render_cohort_builder([], st.session_state['catalog'], None, st.session_state['policy'], 'snapshot', st.session_state['reference'])
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['catalog'] = chars
    app.session_state['policy'] = policy
    app.session_state['reference'] = reference
    app.session_state['family_cohort'] = draft
    with patch('app_core.family_cohort_view.LOCAL_DIR', tmp_path):
        app.run()
        assert not app.exception
        app.checkbox(key='cohort_show_selected_plots').set_value(True).run()
        assert not app.exception
        app.radio(key='cohort_workspace').set_value('Family library').run()
        app.checkbox(key='library_show_heatmap').set_value(True).run()
        assert not app.exception


def test_anchored_page_preview_run_filter_resume_and_builder_handoff(anchored_data, tmp_path):
    base, chars, points, step, _ = anchored_data
    (tmp_path / 'scenarios').mkdir()
    (tmp_path / 'scenarios' / 'good.json').write_text(json.dumps(step['presets'][0]['scenario']))
    (tmp_path / 'membership.parquet').touch()
    (tmp_path / 'manifest.json').write_text('{}')
    script = 'from app_core.family_anchored_view import render_anchored_sweep\nrender_anchored_sweep()'
    app = AppTest.from_string(script, default_timeout=30)
    with patch('app_core.family_anchored_view.LOCAL_DIR', tmp_path), \
         patch('app_core.family_anchored_view._prepared', return_value=(base, chars, points, {}, {'sha256': 'snapshot'})):
        app.run()
        assert not app.exception
        app.number_input(key='as_count').set_value(1).run()
        app.radio(key='as_mode').set_value('Selected characters').run()
        app.multiselect(key='as_anchors').set_value([10, 11]).run()
        app.number_input(key='as_budget_0').set_value(3)
        app.number_input(key='as_runs_0').set_value(3)
        app.number_input(key='as_repeats').set_value(2)
        app.button(key='as_preview').click().run()
        assert not app.exception
        app.button(key='as_run').click().run()
        assert not app.exception
        assert len(app.session_state['as_result']['payload']['jobs']) == 2
        app.multiselect(key='as_result_anchors').set_value([10]).run()
        app.checkbox(key='as_heatmap').set_value(True).run()
        app.button(key='as_use_library').click().run()
        assert not app.exception and len(app.session_state['hunter_sources']) == 2
        filename = next((tmp_path / 'hunter').glob('anchored-*.json')).name
        app.selectbox(key='as_checkpoint').set_value(filename).run()
        app.button(key='as_restore_checkpoint').click().run()
        assert not app.exception and app.selectbox(key='as_checkpoint').value == filename
        with patch('app_core.family_anchored.hunt_anchor', side_effect=AssertionError('Completed job was rerun')):
            app.button(key='as_resume').click().run()
            assert not app.exception
