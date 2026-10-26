from __future__ import annotations

import copy
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app_core.family_cohort import (
    candidate_library, cohort_payload, edit_draft, edit_members, fingerprint, new_draft, overlap_table,
    policy_metrics, score_candidates, subset_scores, summarize_cohort, validate_cohort,
)


@pytest.fixture
def library():
    universe = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF')})
    automatic = universe.assign(family=['A'] * 4 + ['B', 'C'])
    matrix = np.zeros((6, 6))
    matrix[:3, :3] = .95
    matrix[3, :3] = matrix[:3, 3] = .1
    np.fill_diagonal(matrix, .6)  # self-rates must never enter peer scores
    scenario = {'source': {'membership_sha256': 'snapshot', 'reference_sha256': 'reference',
                            'tiers': ['GOLD'], 'maturity': 'All'},
                'families': {key: {'title': key} for key in ['A', 'B', 'C']}, 'software': {'test': '1'}}
    source_id = fingerprint(scenario)
    sources = {source_id: {'name': 'original.json', 'scenario': scenario, 'automatic': automatic.to_dict('records'),
                           'co_membership': {'character_keys': list(range(6)), 'rates': matrix.tolist()},
                           'repetitions': 20, 'repeat_seed': 42, 'profiles': 100}}
    policy = {'family_target': .8, 'trim_fraction': .25, 'single_threshold': .8, 'shared_threshold': .4,
              'separation_target': .2, 'selection_approach': 'Target-size cover',
              'ideal_minimum': 2, 'ideal_maximum': 3, 'size_preference': .5,
              'minimum_family_size': 1, 'maximum_family_size': 0, 'cover_basis': 'Full + retained',
              'max_family_cost': None, 'max_cost_per_character': None}
    candidates = candidate_library(sources, policy)
    return universe, sources, policy, candidates


def test_subset_fit_recomputed_after_trimming_excludes_diagonal_and_maps_keys(library):
    _, sources, _, candidates = library
    source = next(iter(sources.values()))
    full = next(row for row in candidates if row['family'] == 'A' and row['basis'] == 'Full family')
    retained = next(row for row in candidates if row['basis'] == 'Retained members only')
    fits, mean = subset_scores(source, full['member_keys'])
    assert mean == pytest.approx(.525)
    assert fits.set_index('character_key').loc[0, 'member_fit'] == pytest.approx(2 / 3)
    fits, mean = subset_scores(source, retained['member_keys'])
    assert retained['member_keys'] == [0, 1, 2] and 3 not in retained['member_keys']
    assert mean == pytest.approx(.95) and fits.member_fit.tolist() == pytest.approx([.95] * 3)
    changed = copy.deepcopy(source)
    changed['automatic'] = list(reversed(source['automatic']))
    permutation = [4, 2, 0, 5, 3, 1]
    changed['co_membership'] = {'character_keys': permutation,
                               'rates': np.asarray(source['co_membership']['rates'])[np.ix_(permutation, permutation)].tolist()}
    fits, mean = subset_scores(changed, [2, 0, 1])
    assert fits.character.tolist() == ['C', 'A', 'B'] and mean == pytest.approx(.95)
    assert subset_scores(changed, [4])[0].member_fit.isna().all()
    with pytest.raises(ValueError, match='unique'):
        subset_scores(source, [0, 0])


def test_v2_manual_membership_changes_recompute_saved_scoring_context(library):
    from app_core.family_cover import base_family_cost
    universe, sources, policy, candidates = library
    chosen = [copy.deepcopy(row) for row in candidates if row['family'] == 'A']
    assert len(chosen) == 2
    draft = new_draft(sources, universe, policy, 'snapshot', 'reference', chosen)
    scoring = dict(policy, selection_approach='Compact audience cover', compact_objective='coverage_score_v2',
                   overlap_penalty=2., size_preference=.3)
    draft['origin_suggestion'] = dict(method='Compact audience cover', policy=scoring)
    report = summarize_cohort(draft)
    families = report['families']
    assert sorted(families.exclusive_share) == [0., .25]
    assert families.overlap_cost.sum() == pytest.approx(3.5)
    for row in families.itertuples():
        expected = base_family_cost(row.size, row.family_mean, 2, 3, .3)
        assert row.selection_cost == pytest.approx(expected)
        assert row.adjusted_cost == pytest.approx(expected + 2 * (1 - row.exclusive_share))
    # Removing the retained family removes the remaining family's overlap penalty.
    draft['selected'] = [row for row in chosen if row['basis'] == 'Full family']
    assert summarize_cohort(draft)['families'].overlap_cost.sum() == 0
    restored = validate_cohort(cohort_payload(draft), universe, 'snapshot', 'reference')
    assert restored['origin_suggestion']['policy']['overlap_penalty'] == 2.
    draft['origin_suggestion']['policy']['compact_objective'] = 'unsupported'
    with pytest.raises(ValueError, match='objective'):
        validate_cohort(cohort_payload(draft), universe, 'snapshot', 'reference')


def test_manual_membership_is_local_rescored_and_survives_portable_roundtrip(library):
    universe, sources, policy, candidates = library
    core = next(row for row in candidates if row['basis'] == 'Retained members only')
    draft = new_draft(sources, universe, policy, 'snapshot', 'reference', [core])
    before = copy.deepcopy(draft)
    changed = edit_members(draft, core['id'], [0, 1, 2, 5], 'Gameplay similarity despite weak observed audience fit')
    assert draft == before
    family = changed['selected'][0]
    assert family['basis'] == 'Manual variant' and family['base_member_keys'] == [0, 1, 2]
    assert family['member_keys'] == [0, 1, 2, 5] and 'retained_consistency' not in family
    report = summarize_cohort(changed)
    assert report['summary']['covered'] == 4
    assert report['families'].iloc[0].family_mean == pytest.approx(.475)
    links = report['memberships'].set_index('character_key')
    assert links.loc[5, 'manual_assignment'] and links.loc[5, 'member_fit'] == 0
    assert not links.loc[0, 'manual_assignment']
    assert links.manual_variant.all()
    restored = validate_cohort(cohort_payload(changed), universe, 'snapshot', 'reference')
    assert restored['selected'][0] == family
    edited_again = edit_members(changed, family['id'], [0, 1, 2, 4], 'Another deliberate assignment')
    assert edited_again['selected'][0]['base_member_keys'] == [0, 1, 2]
    with pytest.raises(ValueError, match='reason'):
        edit_members(draft, core['id'], [0, 1, 2, 5], '')
    with pytest.raises(ValueError, match='at least two'):
        edit_members(draft, core['id'], [0], 'Too small')
    assert candidate_library(sources, policy) == candidates


def test_manual_membership_ui_preview_apply_and_undo_do_not_recompute_evidence(library, tmp_path):
    universe, sources, policy, candidates = library
    core = next(row for row in candidates if row['basis'] == 'Retained members only')
    script = '''
import streamlit as st
from app_core.family_cohort_view import render_cohort_builder
render_cohort_builder([], st.session_state['catalog'], None, st.session_state['policy'], 'snapshot', 'reference')
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['catalog'] = universe
    app.session_state['policy'] = policy
    app.session_state['family_cohort'] = new_draft(sources, universe, policy, 'snapshot', 'reference', [core])
    with patch('app_core.family_cohort_view.LOCAL_DIR', tmp_path), \
         patch('app_core.family_batch.stability_check', side_effect=AssertionError('Unexpected bootstrap')):
        app.run()
        assert not app.exception
        next(widget for widget in app.multiselect if widget.label == 'Included characters').set_value([0, 1, 2, 5]).run()
        next(widget for widget in app.text_input if widget.label == 'Reason for manual membership').set_value('Shared gameplay role').run()
        app.button(key='cohort_apply_members').click().run()
        assert not app.exception
        assert app.session_state['family_cohort']['selected'][0]['basis'] == 'Manual variant'
        assert app.session_state['family_cohort']['selected'][0]['member_keys'] == [0, 1, 2, 5]
        app.button(key='cohort_undo_button').click().run()
        assert not app.exception
        assert app.session_state['family_cohort']['selected'][0] == core


def test_collection_edits_overlap_and_removal_are_exact_and_inputs_are_preserved(library):
    universe, sources, policy, candidates = library
    full = next(row for row in candidates if row['family'] == 'A' and row['basis'] == 'Full family')
    retained = next(row for row in candidates if row['basis'] == 'Retained members only')
    singleton = next(row for row in candidates if row['family'] == 'B')
    empty = new_draft(sources, universe, policy, 'snapshot', 'reference')
    assert summarize_cohort(empty)['summary']['missing'] == 6
    draft = edit_draft(edit_draft(edit_draft(empty, full), retained), singleton)
    report = summarize_cohort(draft)
    assert empty['selected'] == []
    assert report['summary'] == {'families': 3, 'covered': 5, 'missing': 1, 'repeated': 3,
                                  'extra_memberships': 3, 'membership_rows': 8, 'weak_fit': 1,
                                  'unscored': 1, 'ideal_characters': 3}
    contributions = report['families'].set_index('id')
    assert contributions.loc[full['id'], 'exclusive_characters'] == 1
    assert contributions.loc[retained['id'], 'exclusive_characters'] == 0
    overlap = overlap_table(draft).set_index(['row_id', 'column_id'])
    assert overlap.loc[(full['id'], retained['id']), 'jaccard'] == .75
    assert overlap.loc[(retained['id'], full['id']), 'containment'] == 1
    assert overlap.loc[(full['id'], retained['id']), 'containment'] == .75
    removed = edit_draft(draft, remove_id=full['id'])
    assert summarize_cohort(removed)['summary']['covered'] == 4
    assert len(draft['selected']) == 3
    with pytest.raises(ValueError, match='already selected'):
        edit_draft(draft, full)
    swap = edit_draft(edit_draft(empty, full), retained, full['id'])
    assert summarize_cohort(swap)['summary']['covered'] == 3


def test_policy_lists_all_reasons_and_zero_gain_is_not_infinite(library):
    _, _, policy, candidates = library
    retained = next(row for row in candidates if row['basis'] == 'Retained members only')
    policy = dict(policy, cover_basis='Full families only', minimum_family_size=4, maximum_family_size=2,
                  family_target=.99, max_family_cost=.5, max_cost_per_character=.1)
    metrics = policy_metrics(retained, .95, set(), policy)
    assert set(metrics['policy_flags'].split(' | ')) == {
        'Below family-consistency target', 'Excluded by full-only basis', 'Below minimum size',
        'Above maximum size', 'Above family-cost ceiling', 'Above current marginal-cost limit'}
    zero = policy_metrics(retained, .95, {0, 1, 2}, policy)
    assert np.isnan(zero['cost_per_new_character'])
    assert 'marginal' not in zero['policy_flags']


def test_character_filter_excludes_trimmed_members_and_keeps_group_mean_distinct(library):
    _, sources, policy, candidates = library
    scores = score_candidates(candidates, sources, set(), policy, character_key=3)
    assert len(scores) == 1 and scores.iloc[0].basis == 'Full family'
    assert scores.iloc[0].member_fit == pytest.approx(.1)
    assert scores.iloc[0].family_mean == pytest.approx(.525)


def test_duplicate_member_sets_keep_distinct_source_evidence_and_stable_identity(library):
    universe, sources, policy, candidates = library
    first = next(row for row in candidates if row['basis'] == 'Retained members only')
    other_source = copy.deepcopy(next(iter(sources.values())))
    other_source['scenario']['software']['test'] = '2'
    second_id = fingerprint(other_source['scenario'])
    sources[second_id] = other_source
    library_rows = candidate_library(sources, policy)
    second = next(row for row in library_rows if row['source_id'] == second_id and row['basis'] == 'Retained members only')
    draft = new_draft(sources, universe, policy, 'snapshot', 'reference', [first])
    both = edit_draft(draft, second)
    assert summarize_cohort(both)['summary']['covered'] == 3
    assert summarize_cohort(both)['summary']['repeated'] == 3
    assert first['id'] != second['id']
    # Only registry display names/order change; candidate identity and memberships are unchanged.
    renamed = dict(reversed(list(sources.items())))
    for source in renamed.values():
        source['name'] = 'renamed source.json'
    assert {row['id'] for row in candidate_library(renamed, policy)} == {row['id'] for row in library_rows}


def test_portable_roundtrip_freezes_members_and_rejects_modified_evidence(library):
    universe, sources, policy, candidates = library
    retained = next(row for row in candidates if row['basis'] == 'Retained members only')
    draft = new_draft(sources, universe, policy, 'snapshot', 'reference', [retained])
    draft['selected'][0].update(title='Reviewed core', exception_note='Keep these members')
    draft['character_notes']['5'] = 'No suitable option'
    payload = json.loads(json.dumps(cohort_payload(draft), allow_nan=False))
    restored = validate_cohort(payload, universe, 'snapshot', 'reference')
    assert restored['selected'][0]['member_keys'] == [0, 1, 2]
    assert restored['character_notes']['5'] == 'No suitable option'
    restored['policy']['trim_fraction'] = .4
    assert summarize_cohort(restored)['summary']['covered'] == 3
    # Renaming files does not affect candidate identity; evidence remains in the payload.
    next(iter(restored['sources'].values()))['name'] = 'renamed.json'
    assert validate_cohort(cohort_payload(restored), universe, 'snapshot', 'reference')['selected'][0]['id'] == retained['id']
    payload['sources'][next(iter(sources))]['co_membership']['rates'][0][1] = .2
    with pytest.raises(ValueError, match='checksum'):
        validate_cohort(payload, universe, 'snapshot', 'reference')
    with pytest.raises(ValueError, match='different snapshot'):
        validate_cohort(cohort_payload(draft), universe, 'another', 'reference')
    corrupted = copy.deepcopy(draft)
    next(iter(corrupted['sources'].values()))['co_membership']['rates'][0][1] = .2
    with pytest.raises(ValueError, match='symmetric'):
        validate_cohort(cohort_payload(corrupted), universe, 'snapshot', 'reference')
    invalid = copy.deepcopy(draft)
    invalid['policy']['ideal_minimum'] = -1
    with pytest.raises(ValueError, match='size preferences'):
        validate_cohort(cohort_payload(invalid), universe, 'snapshot', 'reference')


def test_library_suggestion_submits_overlap_and_cost_controls_without_editing_draft(library):
    from app_core.family_cohort import suggest_from_library

    universe, sources, policy, _ = library
    script = '''
import streamlit as st
from app_core.family_cohort_view import _library_suggestion
_library_suggestion(st.session_state['draft'])
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['draft'] = new_draft(sources, universe, policy, 'snapshot', 'reference')
    with patch('app_core.family_cohort_view.suggest_from_library', wraps=suggest_from_library) as calculate:
        app.run()
        assert not app.exception and calculate.call_count == 0
        app.slider(key='cohort_suggest_overlap').set_value(2.)
        app.checkbox(key='cohort_suggest_limit_cost').check()
        app.number_input(key='cohort_suggest_max_cost').set_value(2.)
        app.number_input(key='cohort_suggest_min').set_value(2)
        app.number_input(key='cohort_suggest_low').set_value(2)
        app.number_input(key='cohort_suggest_high').set_value(3)
        app.button(key='cohort_suggest_calculate').click().run()
        assert not app.exception and calculate.call_count == 1
        submitted = calculate.call_args.args[1]
        assert submitted['overlap_penalty'] == 2. and submitted['max_family_cost'] == 2.
        assert next(metric.value for metric in app.metric if metric.label == 'Suggested coverage') == '3/6'
        assert next(metric.value for metric in app.metric if metric.label == 'Extra memberships') == '0'
        assert app.session_state['draft']['selected'] == []
        app.number_input(key='cohort_suggest_max_cost').set_value(.5)
        app.button(key='cohort_suggest_calculate').click().run()
        assert not app.exception and calculate.call_count == 2
        assert next(metric.value for metric in app.metric if metric.label == 'Suggested coverage') == '0/6'


@pytest.mark.parametrize('basis', [None, 'Full families only'])
def test_library_suggestion_accepts_minimal_review_policy(library, basis):
    pytest.importorskip('scipy')
    universe, sources, policy, _ = library
    minimal = {field: policy[field] for field in ['family_target', 'trim_fraction', 'single_threshold',
                                                'shared_threshold', 'separation_target']}
    if basis is not None:
        minimal['cover_basis'] = basis
    script = '''
import streamlit as st
from app_core.family_cohort_view import _library_suggestion
_library_suggestion(st.session_state['draft'])
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['draft'] = new_draft(sources, universe, minimal, 'snapshot', 'reference')
    app.run()
    assert not app.exception
    app.radio(key='cohort_suggest_method').set_value('Compact audience cover')
    app.number_input(key='cohort_suggest_low').set_value(2)
    app.number_input(key='cohort_suggest_high').set_value(3)
    app.button(key='cohort_suggest_calculate').click().run()
    assert not app.exception
    suggestion = app.session_state['cohort_library_suggestion']
    assert suggestion['policy']['cover_basis'] == (basis or 'Full + retained')
    assert suggestion['covered'] == (0 if basis == 'Full families only' else 3)
    assert app.session_state['draft']['selected'] == []


def test_compact_library_preview_apply_undo_and_provenance(library, tmp_path):
    pytest.importorskip('scipy')
    from app_core.family_cohort import prepare_library_candidates

    universe, sources, policy, _ = library
    script = '''
import streamlit as st
from app_core.family_cohort_view import render_cohort_builder
render_cohort_builder([], st.session_state['catalog'], None, st.session_state['policy'], 'snapshot', 'reference')
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['catalog'] = universe
    app.session_state['policy'] = policy
    app.session_state['family_cohort'] = new_draft(sources, universe, policy, 'snapshot', 'reference')
    with patch('app_core.family_cohort_view.LOCAL_DIR', tmp_path), \
         patch('app_core.family_cohort.prepare_library_candidates', wraps=prepare_library_candidates) as prepare, \
         patch('app_core.family_batch.stability_check', side_effect=AssertionError('Unexpected bootstrap')):
        app.run()
        assert not app.exception and prepare.call_count == 0
        assert not any(widget.key == 'cohort_suggest_coverage' for widget in app.slider)
        app.radio(key='cohort_suggest_method').set_value('Compact audience cover').run()
        assert not app.exception and prepare.call_count == 0
        assert app.radio(key='cohort_suggest_objective').value == 'coverage_score_v2'
        app.slider(key='cohort_suggest_overlap').set_value(2.)
        assert app.slider(key='cohort_suggest_coverage').value == 100
        assert app.slider(key='cohort_suggest_exclusive').value == 0
        app.slider(key='cohort_suggest_exclusive').set_value(25)
        app.number_input(key='cohort_suggest_low').set_value(2)
        app.number_input(key='cohort_suggest_high').set_value(3)
        app.number_input(key='cohort_suggest_max').set_value(3)
        app.button(key='cohort_suggest_calculate').click().run()
        assert not app.exception and prepare.call_count == 1
        result = app.session_state['cohort_library_suggestion']['cover']
        assert result['optimal'] and result['eligible_characters'] == 3 and result['covered'] == 3
        assert result['minimum_exclusive_share'] == .25
        assert result['compact_objective'] == 'coverage_score_v2' and result['overlap_penalty'] == 2.
        assert result['adjusted_cost'] == pytest.approx(result['base_cost'] + result['overlap_cost'])
        assert result['families'].exclusive_share.ge(.25).all()
        assert app.session_state['family_cohort']['selected'] == []
        # Cover-only settings reuse candidate evidence, rather than rebuilding scores.
        app.slider(key='cohort_suggest_coverage').set_value(90)
        app.button(key='cohort_suggest_calculate').click().run()
        assert not app.exception and prepare.call_count == 1
        app.button(key='cohort_suggest_apply').click().run()
        assert not app.exception
        draft = app.session_state['family_cohort']
        assert len(draft['selected']) == 1
        assert draft['origin_suggestion']['method'] == 'Compact audience cover'
        assert draft['origin_suggestion']['policy']['minimum_exclusive_share'] == .25
        restored = validate_cohort(cohort_payload(draft), universe, 'snapshot', 'reference')
        assert restored['origin_suggestion']['solver']['stages'][0]['optimal']
        assert restored['origin_suggestion']['policy']['compact_objective'] == 'coverage_score_v2'
        assert restored['origin_suggestion']['policy']['overlap_penalty'] == 2.
        app.button(key='cohort_undo_button').click().run()
        assert not app.exception and app.session_state['family_cohort']['selected'] == []
        app.radio(key='cohort_suggest_objective').set_value('legacy_min_overlap').run()
        assert app.slider(key='cohort_suggest_overlap').disabled
        app.button(key='cohort_suggest_calculate').click().run()
        assert not app.exception
        legacy = app.session_state['cohort_library_suggestion']['cover']
        assert legacy['compact_objective'] == 'legacy_min_overlap' and legacy['overlap_penalty'] == 0
        assert legacy['solver']['objective_count'] == 4


def test_builder_resolves_edits_and_roundtrips_without_bootstrap(library, tmp_path):
    universe, sources, policy, candidates = library
    script = '''
import streamlit as st
from app_core.family_cohort_view import render_cohort_builder
render_cohort_builder([], st.session_state['catalog'], None, st.session_state['policy'], 'snapshot', 'reference')
'''
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state['catalog'] = universe
    app.session_state['policy'] = policy
    app.session_state['family_cohort'] = new_draft(sources, universe, policy, 'snapshot', 'reference')
    scenario_dir = tmp_path / 'scenarios'
    scenario_dir.mkdir()
    original = scenario_dir / 'untouched.json'
    original.write_text('source unchanged')
    with patch('app_core.family_cohort_view.LOCAL_DIR', tmp_path), \
            patch('app_core.family_batch.stability_check', side_effect=AssertionError('Unexpected bootstrap')), \
            patch('app_core.family_batch.scenario_evidence', side_effect=AssertionError('Unexpected evidence rebuild')):
        app.run()
        assert not app.exception
        # The three-member retained core is first by character fit, not the weak full group.
        assert app.selectbox(key='resolve_candidate').value == next(row['id'] for row in candidates if row['basis'] == 'Retained members only')
        app.text_input(key='resolve_exception_note').set_value('Reviewed the retained peers')
        app.button(key='resolve_add').click().run()
        assert not app.exception
        assert app.session_state['family_cohort']['selected'][0]['member_keys'] == [0, 1, 2]
        assert app.session_state['family_cohort']['selected'][0]['exception_note'] == 'Reviewed the retained peers'
        app.radio(key='cohort_workspace').set_value('Overlap and coverage').run()
        assert not app.exception
        app.button(key='cohort_save').click().run()
        assert not app.exception
        saved = list((tmp_path / 'cohorts').glob('*.json'))
        assert len(saved) == 1
        valid = validate_cohort(json.loads(saved[0].read_bytes()), universe, 'snapshot', 'reference')
        assert len(valid['selected']) == 1
        app.button(key='cohort_undo_button').click().run()
        assert not app.exception and not app.session_state['family_cohort']['selected']
        # Load with embedded evidence and restore all selections without the batch page.
        app.selectbox(key='cohort_load_file').select(saved[0].name).run()
        app.button(key='cohort_load').click().run()
        assert not app.exception and len(app.session_state['family_cohort']['selected']) == 1
        assert original.read_text() == 'source unchanged'
        app.radio(key='cohort_workspace').set_value('Resolve characters').run()
        app.button(key='cohort_next_missing').click().run()
        assert not app.exception and app.selectbox(key='cohort_resolve_character').value == 4
        app.button(key='cohort_next_missing').click().run()
        assert not app.exception and app.selectbox(key='cohort_resolve_character').value == 5
        app.button(key='cohort_next_missing').click().run()
        assert not app.exception and app.selectbox(key='cohort_resolve_character').value == 3
        app.checkbox(key='cohort_resolve_below').set_value(True).run()
        assert app.button(key='resolve_add').label == 'Add as manual exception'
        app.button(key='resolve_add').click().run()
        assert not app.exception
        assert app.session_state['family_cohort']['selected'][-1]['added_as_exception']
        assert summarize_cohort(app.session_state['family_cohort'])['summary']['repeated'] == 3
        app.button(key='cohort_undo_button').click().run()
        assert not app.exception and len(app.session_state['family_cohort']['selected']) == 1
