from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app_core.families import FamilySettings, discover_families, prepare_membership, scenario_payload, stability_check
from app_core.family_batch import aggregate_coverage, evaluate_scenario, scenario_evidence, smallest_family_cover, target_size_cover
from app_core.family_batch_view import _evidence
from app_core.family_cohort import cohort_payload

pytest.importorskip('leidenalg', reason='Install requirements-families.txt for the optional local laboratory')
APP_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scenarios():
    rows = []
    for names in [('A', 'B', 'C'), ('D', 'E', 'F')]:
        for _ in range(40):
            rows.append({'region': 'na1', 'queue': 'RANKED_SOLO_5x5', 'tier': 'GOLD', 'days_tracked': 5,
                         'as_of_date': '2026-10-20',
                         'members': [{'key': ord(name), 'name': name, 'points': 20000} for name in names]})
    base, characters, points, reference = prepare_membership(pd.DataFrame(rows))
    source = dict(reference, membership_sha256='batch-test-source', exported_at_utc='2026-10-20',
                  tiers=['GOLD'], maturity='All', excluded_keys=[], profiles=len(base))
    settings = FamilySettings()
    automatic = discover_families(points, characters, base.population_weight.to_numpy(), settings)['assignments']
    payload = scenario_payload(settings, source, automatic, {f: {'title': f} for f in automatic.family.unique()}, '')
    return base, characters, points, reference, payload


def test_cohesion_bands_match_full_and_retained_scores_without_separation_gating():
    automatic = pd.DataFrame({'character_key': range(10), 'character': list('ABCDEFGHIJ'),
                              'family': ['A']*4 + ['B']*3 + ['C']*2 + ['D']})
    rates = np.zeros((10, 10))
    rates[:3, :3] = .95
    rates[3, :3] = rates[:3, 3] = .1
    rates[4:7, 4:7] = .9
    rates[7:9, 7:9] = .3
    np.fill_diagonal(rates, 1)
    evidence = {'automatic': automatic, 'co_membership': {'character_keys': list(range(10)), 'rates': rates.tolist()}}
    result = evaluate_scenario(evidence)
    assert result['summary']['Full family meets target'] == 1
    assert result['summary']['Retained members only'] == 1
    assert result['summary']['Below target'] == 1
    assert result['summary']['No peer score'] == 1
    assert result['summary']['Primary only'] == 3
    assert result['summary']['Indecisive'] == 7
    assert result['families'].set_index('family').loc['A', 'removed_members'] == 'D'
    # High pair cohesion still counts as full even if every original group merges.
    evidence['co_membership']['rates'] = np.ones((10, 10)).tolist()
    result = evaluate_scenario(evidence)
    assert result['summary']['Full family meets target'] == 3
    assert result['families'].iloc[0].pattern == 'Overlaps alternatives'


def test_matching_saved_evidence_reused_and_different_seed_or_repeats_recomputed(scenarios):
    base, characters, points, _, payload = scenarios
    computed = scenario_evidence(payload, base, characters, points, 'batch-test-source', 2, 42)
    signature = hashlib.sha256(json.dumps([payload['settings'], payload['source']], sort_keys=True).encode()).hexdigest()
    payload['stability_checks'] = {'bootstrap': {'mode': 'Whole-player bootstrap', 'signature': signature,
                                               'repetitions': 2, 'co_membership': computed['co_membership']}}
    with patch('app_core.family_batch.stability_check', wraps=stability_check) as check:
        reused = scenario_evidence(payload, base, characters, points, 'batch-test-source', 2, 42)
        assert reused['evidence_origin'] == 'Matching saved bootstrap'
        assert check.call_count == 0
        scenario_evidence(payload, base, characters, points, 'batch-test-source', 3, 42)
        scenario_evidence(payload, base, characters, points, 'batch-test-source', 2, 77)
        assert check.call_count == 2
        assert check.call_args.args[3].seed == 77
        assert payload['settings']['seed'] == 42
        payload['stability_checks']['bootstrap']['co_membership'] = {'character_keys': [], 'rates': []}
        repaired = scenario_evidence(payload, base, characters, points, 'batch-test-source', 2, 42)
        assert repaired['evidence_origin'] == 'Computed bootstrap'
        assert check.call_count == 3


def test_coverage_unions_character_ids_and_excludes_removed_outliers():
    universe = pd.DataFrame({'character_key': range(8), 'character': ['A', 'B', 'C', 'D', 'E', 'F', 'Comma, character', 'H']})
    first = universe.assign(family=['A']*4 + ['B']*3 + ['Unassigned'])
    rates = np.zeros((8, 8))
    rates[:4, :4] = .9
    rates[4:6, 4:6] = .95
    rates[6, 4:6] = rates[4:6, 6] = .1
    np.fill_diagonal(rates, 1)
    rates[7, 7] = 0
    result = evaluate_scenario({'automatic': first, 'co_membership': {'character_keys': list(range(8)), 'rates': rates.tolist()}})
    second = universe.assign(family=['A', 'B', 'B', 'B', 'A', 'B', 'B', 'Unassigned'])
    rates = np.zeros((8, 8))
    rates[np.ix_([0, 4], [0, 4])] = .9
    rates[np.ix_([1, 2, 3, 5, 6], [1, 2, 3, 5, 6])] = .2
    np.fill_diagonal(rates, 1)
    rates[7, 7] = 0
    other = evaluate_scenario({'automatic': second, 'co_membership': {'character_keys': list(range(8)), 'rates': rates.tolist()}})
    cases = [{'name': 'same-name.json', 'id': 'first', 'result': result},
             {'name': 'same-name.json', 'id': 'second', 'result': other}]
    coverage = aggregate_coverage(cases, universe)
    assert coverage['total_characters'] == 8
    assert coverage['full_characters'] == 5  # the second family's key 4 adds one, not two
    assert coverage['combined_characters'] == 6
    assert coverage['retained_adds'] == 1
    assert set(coverage['coverage'].loc[~coverage['coverage'].covered_full_or_retained, 'character_key']) == {6, 7}
    assert coverage['coverage'].set_index('character_key').loc[4, 'coverage_status'] == 'Full family'
    assert coverage['coverage'].set_index('character_key').loc[5, 'coverage_status'] == 'Retained only'
    assert coverage['contributions'].full_characters.tolist() == [4, 2]
    retained = coverage['families'].loc[coverage['families'].basis.eq('Retained members only')].iloc[0]
    assert set(retained.member_keys) == {4, 5} and retained.included_characters == 2
    assert aggregate_coverage(cases + [cases[0]], universe)['combined_characters'] == 6
    # The size limit applies to retained size, and the full catalog stays the denominator.
    limited = aggregate_coverage(cases, universe, 2)
    assert limited['full_characters'] == 2
    assert limited['combined_characters'] == 3
    assert limited['total_characters'] == 8
    assert aggregate_coverage(cases, universe, 1)['combined_characters'] == 0
    no_pairs = aggregate_coverage(cases, universe, minimum_family_size=3)
    assert no_pairs['full_characters'] == 4 and no_pairs['combined_characters'] == 4
    assert no_pairs['families'].included_characters.ge(3).all()
    assert no_pairs['total_characters'] == 8
    assert aggregate_coverage(cases, universe, 2, 3)['families'].empty
    with pytest.raises(ValueError, match='positive minimum'):
        aggregate_coverage(cases, universe, minimum_family_size=0)
    assert aggregate_coverage([], universe)['uncovered_characters'] == 8


def test_smallest_cover_preserves_each_characters_finest_option_rather_than_fewest_families():
    universe = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF')})
    candidates = pd.DataFrame([
        {'family_id': name, 'scenario': 'example', 'family': name, 'member_keys': keys,
         'included_characters': len(keys), 'qualifying_consistency': score, 'basis': basis}
        for name, keys, score, basis in [
            ('Broad', list(range(6)), .99, 'Full family'),
            ('Left', [0, 1, 2], .9, 'Retained members only'),
            ('Right', [3, 4, 5], .9, 'Retained members only'),
            ('Pair A', [0, 3], .85, 'Retained members only'),
            ('Pair B', [1, 4], .85, 'Retained members only'),
            ('Weaker duplicate', [0, 3], .8, 'Retained members only'),
        ]])
    full = smallest_family_cover(candidates, universe, False)
    assert full['complete'] and full['minimum_size_cap'] == 6
    assert full['families'].family.tolist() == ['Broad']
    fine = smallest_family_cover(candidates, universe)
    assert fine['complete'] and fine['minimum_size_cap'] == 3
    assert set(fine['families'].family) == {'Left', 'Right', 'Pair A', 'Pair B'}
    options = fine['characters'].set_index('character_key').sort_index()
    assert options.smallest_family_size.tolist() == [2, 2, 3, 2, 2, 3]
    for character in options.itertuples():
        group = candidates.set_index('family_id').loc[character.suggested_family_id]
        assert character.Index in group.member_keys
        assert len(group.member_keys) == character.smallest_family_size
    # Every smaller cap leaves gaps, establishing that the complete-coverage cap is exact.
    smaller = candidates.loc[candidates.included_characters.lt(fine['minimum_size_cap'])]
    incomplete = smallest_family_cover(smaller, universe)
    assert not incomplete['complete'] and incomplete['covered'] == 4
    assert incomplete['minimum_size_cap'] == 2
    assert incomplete['characters'].loc[incomplete['characters'].smallest_family_size.isna(), 'character'].tolist() == ['C', 'F']
    empty = smallest_family_cover(candidates.iloc[:0], universe)
    assert empty['covered'] == 0 and empty['minimum_size_cap'] is None
    assert empty['families'].empty and empty['characters'].suggested_family_id.isna().all()


def test_target_cover_balances_granularity_and_count_keeps_fallbacks_and_reports_gaps():
    universe = pd.DataFrame({'character_key': range(13), 'character': [f'C{i}' for i in range(13)]})
    candidates = pd.DataFrame([
        {'family_id': name, 'scenario': 'example', 'family': name, 'member_keys': keys,
         'included_characters': len(keys), 'qualifying_consistency': score, 'basis': basis}
        for name, keys, score, basis in [
            ('Broad', list(range(13)), 1., 'Full family'),
            ('Left', list(range(6)), .95, 'Full family'),
            ('Right', list(range(6, 12)), .95, 'Full family'),
            ('Fallback', [0, 1, 12], .9, 'Retained members only'),
            ('Weaker left', list(range(6)), .8, 'Full family'),
        ]])
    compact = target_size_cover(candidates, universe, ideal_minimum=5, ideal_maximum=6, size_preference=0)
    assert compact['complete'] and compact['families'].family.tolist() == ['Broad']
    fine = target_size_cover(candidates, universe, ideal_minimum=5, ideal_maximum=6, size_preference=1)
    assert fine['complete'] and set(fine['families'].family) == {'Left', 'Right', 'Fallback'}
    assert fine['ideal_characters'] == 12 and fine['outside_ideal_characters'] == 1
    options = fine['characters'].set_index('character_key')
    assert options.loc[12, 'suggested_family'] == 'Fallback'
    assert options.loc[12, 'target_distance'] == 2 and not options.loc[12, 'ideal_option_available']
    assert options.loc[0, 'suggested_family'] == 'Left'  # fallback membership does not replace its ideal option
    exclusive = target_size_cover(candidates, universe, False, 5, 6, 1)
    assert exclusive['complete'] and 'Fallback' not in set(exclusive['families'].family)
    assert exclusive['characters'].set_index('character_key').loc[12, 'suggested_family'] == 'Broad'
    reordered = target_size_cover(candidates.iloc[::-1], universe, ideal_minimum=5, ideal_maximum=6, size_preference=1)
    assert reordered['families'].family.tolist() == fine['families'].family.tolist()
    incomplete = target_size_cover(candidates.loc[candidates.family.eq('Left')], universe)
    assert incomplete['covered'] == 6 and not incomplete['complete']
    assert incomplete['characters'].suggested_family_id.isna().sum() == 7
    empty = target_size_cover(candidates.iloc[:0], universe)
    assert empty['families'].empty and empty['covered'] == 0 and empty['outside_ideal_characters'] == 0
    with pytest.raises(ValueError, match='ordered ideal'):
        target_size_cover(candidates, universe, ideal_minimum=15, ideal_maximum=10)


def test_overlap_penalty_trades_repetition_against_size_without_losing_coverage():
    universe = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF')})
    candidates = pd.DataFrame([
        {'family_id': name, 'scenario': 'example', 'family': name, 'member_keys': keys,
         'included_characters': len(keys), 'qualifying_consistency': consistency, 'basis': 'Full family'}
        for name, keys, consistency in [('A', [0, 1, 2, 3], 1.), ('B', [2, 3, 4, 5], 1.), ('C', [4, 5], .9)]])
    options = dict(ideal_minimum=4, ideal_maximum=4, size_preference=.05)
    baseline = target_size_cover(candidates, universe, **options)
    reduced = target_size_cover(candidates, universe, overlap_penalty=3., **options)
    assert baseline['complete'] and reduced['complete']
    assert set(baseline['families'].family) == {'A', 'B'}
    assert set(reduced['families'].family) == {'A', 'C'}
    assert reduced['families'].included_characters.sum() == 6
    assert reduced['families'].set_index('family').loc['C', 'qualifying_consistency'] == .9
    reversed_result = target_size_cover(candidates.iloc[::-1], universe, overlap_penalty=3., **options)
    assert reversed_result['families'].family.tolist() == reduced['families'].family.tolist()
    # The ceiling applies before overlap; it must not reintroduce the excluded C.
    limited = target_size_cover(candidates, universe, overlap_penalty=3., max_family_cost=1.05, **options)
    assert limited['complete'] and set(limited['families'].family) == {'A', 'B'}
    stopped = target_size_cover(candidates, universe, overlap_penalty=3., max_cost_per_character=.6, **options)
    assert stopped['covered'] == 4
    for invalid in [-1., np.nan, np.inf]:
        with pytest.raises(ValueError, match='Overlap penalty'):
            target_size_cover(candidates, universe, overlap_penalty=invalid)


def test_target_cover_refinement_replaces_a_greedy_broad_choice_without_losing_coverage():
    universe = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF')})
    candidates = pd.DataFrame([
        {'family_id': name, 'scenario': 'example', 'family': name, 'member_keys': keys,
         'included_characters': len(keys), 'qualifying_consistency': 1., 'basis': 'Full family'}
        for name, keys in [('A broad', list(range(6))), ('B left', [0, 1, 2]), ('C right', [3, 4, 5])]])
    # All greedy values tie at 3; the broad family's ID wins initially. Additions
    # improve per-character fit, then removal discards the now-redundant broad group.
    result = target_size_cover(candidates, universe, ideal_minimum=3, ideal_maximum=3, size_preference=.1)
    assert result['complete'] and result['ideal_characters'] == 6
    assert set(result['families'].family) == {'B left', 'C right'}


def test_target_cost_uses_equal_penalties_for_equal_proportional_size_changes():
    universe = pd.DataFrame({'character_key': range(40), 'character': [str(i) for i in range(40)]})
    costs = {}
    for size in [4, 8, 10, 15, 20, 40]:
        candidate = pd.DataFrame([{'family_id': 'only', 'scenario': 'test', 'family': 'A',
            'member_keys': list(range(size)), 'included_characters': size,
            'qualifying_consistency': 1., 'basis': 'Full family'}])
        result = target_size_cover(candidate, universe, size_preference=.1)
        costs[size] = result['families'].iloc[0].selection_cost
        assert result['no_eligible_characters'] == 40 - size
    assert costs[4] - costs[8] == pytest.approx(1)
    assert costs[40] - costs[20] == pytest.approx(1)
    assert costs[10] == costs[15] == 1


def test_cost_limits_stop_dynamic_coverage_and_explain_both_types_of_gap():
    universe = pd.DataFrame({'character_key': range(7), 'character': list('ABCDEFG')})
    candidates = pd.DataFrame([
        {'family_id': name, 'scenario': 'test', 'family': name, 'member_keys': keys,
         'included_characters': len(keys), 'qualifying_consistency': 1., 'basis': 'Full family'}
        for name, keys in [('Core', list(range(5))), ('Tail', [4, 5])]])
    capped = target_size_cover(candidates, universe, ideal_minimum=5, ideal_maximum=5,
                               size_preference=.1, max_cost_per_character=1.5)
    assert capped['covered'] == 5 and not capped['complete']
    assert capped['no_eligible_characters'] == 1 and capped['cost_limited_characters'] == 1
    rows = capped['characters'].set_index('character_key')
    assert rows.loc[5, 'coverage_status'] == 'Marginal cost limit'
    assert rows.loc[6, 'coverage_status'] == 'No eligible family'
    assert rows.loc[5, 'cheapest_remaining_family'] == 'Tail'
    remaining = capped['remaining_options'].iloc[0]
    assert remaining.new_characters == 1  # its other character was already covered
    assert remaining.cost_per_new_character == pytest.approx(1 + np.log2(5/2))
    assert remaining.blocked_by == 'Cost per additional character limit'
    relaxed = target_size_cover(candidates, universe, ideal_minimum=5, ideal_maximum=5,
                                size_preference=.1, max_cost_per_character=remaining.cost_per_new_character)
    assert relaxed['covered'] == 6 and relaxed['cost_limited_characters'] == 0
    excluded = target_size_cover(candidates, universe, ideal_minimum=5, ideal_maximum=5,
                                 size_preference=.1, max_family_cost=2)
    assert excluded['covered'] == 5 and excluded['family_cost_excluded_characters'] == 1
    assert excluded['characters'].set_index('character_key').loc[5, 'coverage_reason'] == 'Family cost ceiling'
    assert excluded['remaining_options'].iloc[0].blocked_by == 'Family cost ceiling'
    none = target_size_cover(candidates, universe, max_family_cost=.5)
    assert none['families'].empty and none['no_eligible_characters'] == 7
    stopped = target_size_cover(candidates, universe, max_cost_per_character=.001)
    assert stopped['covered'] == 0 and stopped['cost_limited_characters'] == 6
    assert stopped['no_eligible_characters'] == 1 and len(stopped['remaining_options']) == 2
    for argument in ['max_family_cost', 'max_cost_per_character']:
        with pytest.raises(ValueError, match='positive finite'):
            target_size_cover(candidates, universe, **{argument: -1})


def test_marginal_limit_cannot_be_bypassed_by_fit_only_refinement_additions():
    universe = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF')})
    candidates = pd.DataFrame([
        {'family_id': name, 'scenario': 'test', 'family': name, 'member_keys': keys,
         'included_characters': len(keys), 'qualifying_consistency': 1., 'basis': 'Full family'}
        for name, keys in [('A broad', list(range(6))), ('B left', [0, 1, 2]), ('C right', [3, 4, 5])]])
    result = target_size_cover(candidates, universe, ideal_minimum=3, ideal_maximum=3,
                               size_preference=.1, max_cost_per_character=.5)
    assert result['complete'] and result['families'].family.tolist() == ['A broad']
    assert result['ideal_characters'] == 0  # refinement cannot add zero-gain ideal families


@pytest.fixture
def batch_page(tmp_path, scenarios):
    base, characters, points, reference, payload = scenarios
    directory = tmp_path / 'scenarios'
    directory.mkdir()
    (directory / '!two-families.json').write_text(json.dumps(payload), encoding='utf-8')
    empty = dict(payload, settings=asdict(replace(FamilySettings(), minimum_shared=1000)))
    (directory / '!empty-families.json').write_text(json.dumps(empty), encoding='utf-8')
    bad = dict(payload, source=dict(payload['source'], membership_sha256='other-source'))
    (directory / 'bad-source.json').write_text(json.dumps(bad), encoding='utf-8')
    manifest = {'sha256': 'batch-test-source', 'max_as_of_date': '2026-10-20'}
    (tmp_path / 'membership.parquet').write_bytes(b'handled by prepared fixture')
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    _evidence.clear()
    with patch('app_core.family_batch_view.LOCAL_DIR', tmp_path), \
            patch('app_core.family_batch_view._prepared', return_value=(base, characters, points, reference, manifest)):
        yield AppTest.from_file(str(APP_ROOT / 'pages/6_Batch_Scenario_Viewer.py'), default_timeout=30)
    _evidence.clear()


def test_batch_comparison_thresholds_reuse_bootstrap_and_partial_errors_are_visible(batch_page):
    app = batch_page
    with patch('app_core.family_batch_view.scenario_evidence', wraps=scenario_evidence) as compute:
        app.run()
        next(x for x in app.number_input if x.key == 'batch_repetitions').set_value(2).run()
        next(x for x in app.button if x.key == 'batch_run').click().run()
        assert not app.exception
        assert compute.call_count == 2
        comparison = next(x.value for x in app.dataframe if 'Primary only' in x.value.columns)
        assert comparison.set_index('Scenario').loc['!two-families.json', 'Primary only'] == 6
        assert comparison.set_index('Scenario').loc['!empty-families.json', 'Indecisive'] == 6
        assert next(x for x in app.metric if x.label == 'Full families only').value == '6/6'
        assert next(x for x in app.metric if x.label == 'Full + retained').value == '6/6'
        assert next(x for x in app.metric if x.label == 'Smallest size limit for full coverage').value == '3'
        assert next(x for x in app.metric if x.label == 'Suggested families').value == '2'
        assert len(next(x.value for x in app.dataframe if 'family_id' in x.value.columns)) == 2
        next(x for x in app.radio if x.key == 'batch_cover_approach').set_value('Target-size cover').run()
        assert not app.exception
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '6/6'
        assert next(x for x in app.metric if x.label == 'Covered outside ideal range').value == '6'
        next(x for x in app.checkbox if x.key == 'batch_limit_family_cost').set_value(True).run()
        assert not app.exception
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '0/6'
        assert next(x for x in app.metric if x.label == 'No eligible family').value == '6'
        next(x for x in app.number_input if x.key == 'batch_max_family_cost').set_value(20.).run()
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '6/6'
        next(x for x in app.checkbox if x.key == 'batch_limit_family_cost').set_value(False).run()
        next(x for x in app.checkbox if x.key == 'batch_limit_marginal_cost').set_value(True).run()
        assert not app.exception
        assert next(x for x in app.metric if x.label == 'Left uncovered by marginal limit').value == '6'
        assert next(x for x in app.metric if x.label == 'No eligible family').value == '0'
        next(x for x in app.number_input if x.key == 'batch_max_marginal_cost').set_value(10.).run()
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '6/6'
        next(x for x in app.checkbox if x.key == 'batch_limit_marginal_cost').set_value(False).run()
        assert compute.call_count == 2
        next(x for x in app.number_input if x.key == 'batch_coverage_minimum').set_value(4).run()
        assert next(x for x in app.metric if x.label == 'Full + retained').value == '0/6'
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '6/6'
        next(x for x in app.checkbox if x.key == 'batch_target_hard_limits').set_value(True).run()
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '0/6'
        next(x for x in app.checkbox if x.key == 'batch_target_hard_limits').set_value(False).run()
        next(x for x in app.number_input if x.key == 'batch_ideal_minimum').set_value(3).run()
        next(x for x in app.number_input if x.key == 'batch_ideal_maximum').set_value(3).run()
        assert next(x for x in app.metric if x.label == 'Covered in ideal-sized families').value == '6'
        next(x for x in app.number_input if x.key == 'batch_ideal_maximum').set_value(2).run()
        assert any('ideal maximum must be at least' in x.value for x in app.warning)
        assert not app.exception
        next(x for x in app.number_input if x.key == 'batch_ideal_maximum').set_value(3).run()
        next(x for x in app.slider if x.key == 'batch_size_preference').set_value(.8).run()
        assert compute.call_count == 2  # soft size settings never rerun bootstrap
        next(x for x in app.radio if x.key == 'batch_cover_approach').set_value('Smallest available').run()
        next(x for x in app.number_input if x.key == 'batch_coverage_minimum').set_value(2).run()
        next(x for x in app.number_input if x.key == 'batch_coverage_minimum').set_value(4).run()
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '0/6'
        assert len([x.value for x in app.dataframe if 'family_id' in x.value.columns][-1]) == 2
        assert compute.call_count == 2
        next(x for x in app.number_input if x.key == 'batch_coverage_minimum').set_value(2).run()
        next(x for x in app.number_input if x.key == 'batch_coverage_maximum').set_value(2).run()
        assert next(x for x in app.metric if x.label == 'Full + retained').value == '0/6'
        assert next(x for x in app.metric if x.label == 'Smallest size limit for full coverage').value == 'Unavailable'
        assert any('Complete coverage is unavailable' in x.value for x in app.warning)
        # All viable alternatives remain browseable even when the coverage size limit excludes them.
        browser = [x.value for x in app.dataframe if 'family_id' in x.value.columns][-1]
        assert len(browser) == 2
        next(x for x in app.multiselect if x.key == 'batch_candidate_search').set_value(['A']).run()
        browser = [x.value for x in app.dataframe if 'family_id' in x.value.columns][-1]
        assert len(browser) == 1 and 'A' in browser.iloc[0].member_names
        next(x for x in app.multiselect if x.key == 'batch_candidate_search').set_value([]).run()
        assert compute.call_count == 2
        next(x for x in app.number_input if x.key == 'batch_coverage_maximum').set_value(0).run()
        next(x for x in app.slider if x.key == 'batch_shared').set_value(.5).run()
        next(x for x in app.slider if x.key == 'batch_trim').set_value(.3).run()
        next(x for x in app.radio if x.key == 'batch_cover_basis').set_value('Full families only').run()
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '6/6'
        next(x for x in app.selectbox if x.key == 'batch_candidate_basis').set_value('Retained only').run()
        assert any('No viable families match' in x.value for x in app.info)
        next(x for x in app.selectbox if x.key == 'batch_candidate_basis').set_value('Full + retained').run()
        next(x for x in app.checkbox if x.key == 'batch_show_details').set_value(True).run()
        next(x for x in app.selectbox if x.label == 'Heatmap family').set_value('Unassigned').run()
        next(x for x in app.checkbox if x.key == 'batch_expand_all').set_value(True).run()
        assert not app.exception
        assert not any('!two-families.json' in x.label for x in app.expander)
        assert compute.call_count == 2
        next(x for x in app.multiselect if x.key == 'batch_selected_scenarios').set_value(['!empty-families.json']).run()
        next(x for x in app.button if x.key == 'batch_run').click().run()
        assert not app.exception
        assert next(x for x in app.metric if x.label == 'Suggested coverage').value == '0/6'
        assert compute.call_count == 2
        next(x for x in app.button if x.label == 'Select all saved scenarios').click().run()
        assert any('Selection, scenario files' in x.value for x in app.info)
        next(x for x in app.button if x.key == 'batch_run').click().run()
        assert not app.exception
        assert compute.call_count == 3  # prior valid cases reused, only the bad source is new
        errors = next(x.value for x in app.dataframe if 'Error' in x.value.columns)
        assert errors.Scenario.tolist() == ['bad-source.json']
        next(x for x in app.number_input if x.key == 'batch_repetitions').set_value(3).run()
        assert any('repeat count or repeat seed changed' in x.value for x in app.info)


def test_cohort_draft_survives_changed_suggestions_trim_and_pending_batch(batch_page):
    app = batch_page
    with patch('app_core.family_batch_view.scenario_evidence', wraps=scenario_evidence) as compute:
        app.run()
        app.number_input(key='batch_repetitions').set_value(2).run()
        app.button(key='batch_run').click().run()
        app.button(key='cohort_start_suggestion').click().run()
        assert not app.exception
        selected = app.session_state['family_cohort']['selected']
        frozen = [(row['id'], row['member_keys'].copy()) for row in selected]
        assert len(frozen) == 2
        app.number_input(key='batch_coverage_minimum').set_value(4).run()
        assert not app.exception
        assert next(x.value for x in app.metric if x.label == 'Suggested coverage') == '0/6'
        assert next(x.value for x in app.metric if x.label == 'Cohort coverage') == '6/6'
        app.slider(key='batch_trim').set_value(.4).run()
        app.slider(key=f'cohort_member_target_{app.session_state["cohort_revision"]}').set_value(.95).run()
        assert not app.exception
        assert [(row['id'], row['member_keys']) for row in app.session_state['family_cohort']['selected']] == frozen
        app.number_input(key='batch_repetitions').set_value(3).run()
        assert not app.exception
        assert next(x.value for x in app.metric if x.label == 'Cohort coverage') == '6/6'
        assert compute.call_count == 2


def test_loading_cohort_restores_saved_review_controls_before_widgets(batch_page, tmp_path):
    app = batch_page
    with patch('app_core.family_cohort_view.LOCAL_DIR', tmp_path):
        app.run()
        app.number_input(key='batch_repetitions').set_value(2).run()
        app.slider(key='batch_target').set_value(.75).run()
        app.button(key='batch_run').click().run()
        app.button(key='cohort_start_suggestion').click().run()
        payload = cohort_payload(app.session_state['family_cohort'])
        directory = tmp_path / 'cohorts'
        directory.mkdir()
        (directory / 'saved.json').write_text(json.dumps(payload))
        app.slider(key='batch_target').set_value(.95).run()
        app.selectbox(key='cohort_load_file').select('saved.json').run()
        app.button(key='cohort_load').click().run()
        assert not app.exception
        assert app.slider(key='batch_target').value == .75
        assert app.session_state['family_cohort']['policy']['family_target'] == .75
