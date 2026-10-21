from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from app_core import families as family_analysis

from app_core.families import (
    FamilySettings, discover_families, family_affinities, pair_statistics,
    scenario_payload, stability_check, summarize_stability, validate_membership, validate_scenario,
)
from app_core.population import load_reference, reference_fingerprint

pytest.importorskip('leidenalg', reason='Install requirements-families.txt for the optional local laboratory')


@pytest.fixture
def two_families():
    points = np.array([[20000, 25000, 30000, 0, 0, 0]] * 8
                      + [[0, 0, 0, 20000, 25000, 30000]] * 8, dtype=float)
    characters = pd.DataFrame({'character_key': range(1, 7), 'character': list('ABCDEF')})
    settings = FamilySettings(minimum_players=2, minimum_shared=2, minimum_family_size=3)
    return points, characters, np.ones(16), settings


def test_shared_audiences_form_two_families_and_excluded_characters_stay_unassigned(two_families):
    points, characters, weights, settings = two_families
    result = discover_families(points, characters, weights, settings)
    families = result['assignments'].family
    assert families.iloc[:3].nunique() == 1
    assert families.iloc[3:].nunique() == 1
    assert families.iloc[0] != families.iloc[3]
    assert len(result['edges']) == 6
    excluded = discover_families(points, characters, weights, settings, (1,))
    assert excluded['assignments'].iloc[0].family == 'Unassigned'
    assert not excluded['edges'][['key_a', 'key_b']].isin([1]).any().any()


def test_weighted_jaccard_preserves_raw_support_and_cutoff():
    points = np.array([[20000, 20000], [20000, 0], [0, 14999]], dtype=float)
    result = pair_statistics(points, np.array([2., 1., 7.]), FamilySettings())
    assert result['raw'][0, 1] == 1
    assert result['shared'][0, 1] == 2
    assert result['jaccard'][0, 1] == pytest.approx(2 / 3)
    assert result['direction'][0, 1] == pytest.approx(2 / 3)
    assert result['direction'][1, 0] == 1


def test_family_affinity_keeps_below_cutoff_unmapped_and_missing_mass():
    points = np.array([[20000., 10000., 30000.], [0., 0., 0.]])
    assignments = pd.DataFrame({'family': ['AR01', 'AR01', 'Unassigned']})
    affinity = family_affinities(points, assignments, 15000)
    assert affinity.iloc[0].to_dict() == pytest.approx({'AR01': 1/3, 'Below cutoff': 1/6, 'Unmapped': 1/2})
    assert affinity.iloc[1].isna().all()


def test_seed_and_whole_profile_bootstrap_checks_are_label_independent(two_families):
    points, characters, weights, settings = two_families
    baseline = discover_families(points, characters, weights, settings)['assignments']
    for bootstrap in (False, True):
        stability = stability_check(points, characters, weights, settings, baseline, (), 3, bootstrap)
        assert stability.mean_comember_jaccard.eq(1).all()
        assert stability.assigned_rate.eq(1).all()


def test_scenario_roundtrip_keeps_manual_assignments_and_rejects_other_sources(two_families):
    points, characters, weights, settings = two_families
    assignments = discover_families(points, characters, weights, settings)['assignments']
    assignments.loc[0, 'family'] = 'Manual-cross-type'
    source = {'membership_sha256': 'source', 'reference_sha256': reference_fingerprint(load_reference()),
              'tiers': ['GOLD'], 'maturity': 'All', 'excluded_keys': []}
    titles = {family: {'title': family} for family in assignments.family.unique()}
    payload = scenario_payload(settings, source, assignments, titles, 'Needs review')
    restored = json.loads(json.dumps(payload))
    validate_scenario(restored, characters, 'source')
    assert restored['assignments'][0]['family'] == 'Manual-cross-type'
    with pytest.raises(ValueError, match='different membership'):
        validate_scenario(restored, characters, 'other')
    restored['assignments'][1]['character_key'] = 1
    with pytest.raises(ValueError, match='keys/names'):
        validate_scenario(restored, characters, 'source')


def test_rejects_impossible_size_constraints_and_duplicate_membership():
    with pytest.raises(ValueError, match='Maximum family size'):
        replace(FamilySettings(), minimum_family_size=10, maximum_family_size=3)
    row = {'region': 'na1', 'queue': 'solo', 'tier': 'GOLD', 'days_tracked': 5,
           'as_of_date': '2026-10-20', 'members': [{'key': 1, 'name': 'A', 'points': 100}] * 2}
    with pytest.raises(ValueError, match='duplicate'):
        validate_membership(pd.DataFrame([row]))


def test_empty_graph_and_adjusted_associations_are_valid(two_families):
    points, characters, weights, settings = two_families
    result = discover_families(points, characters, weights, replace(settings, minimum_shared=100))
    assert result['assignments'].family.eq('Unassigned').all()
    assert result['edges'].empty
    adjusted = discover_families(points, characters, weights, replace(settings, association='breadth_adjusted'))
    assert not adjusted['edges'].empty
    assert np.isfinite(adjusted['edges'].breadth_log2_ratio).all()


def test_stability_summary_separates_unassigned_missing_and_zero_scores():
    baseline = pd.DataFrame({'character_key': [1, 2, 3, 4, 5],
                             'family': ['AR01', 'AR01', 'AR02', 'AR02', 'Unassigned']})
    report = pd.DataFrame({'character_key': [5, 4, 3, 2, 1], 'character': list('EDCBA'),
                           'mean_comember_jaccard': [None, None, 0, .7, .9],
                           'assigned_rate': [1., .5, 0., .5, 1.]})
    summary = summarize_stability(report, baseline, .8)
    assert summary['mean_jaccard'] == pytest.approx(1.6 / 3)
    assert summary['median_jaccard'] == .7
    assert summary['p10_jaccard'] == pytest.approx(.14)
    assert summary['below_target_share'] == pytest.approx(2/3)
    assert summary['mean_assigned_rate'] == .5
    assert summary['initial_coverage'] == .8
    assert summary['scored_characters'] == 3
    assert summary['assignment_scored_characters'] == 4
    assert summary['families'].set_index('family').loc['AR02', 'mean_comember_jaccard'] == 0


def test_all_unassigned_summary_is_unavailable_rather_than_zero():
    baseline = pd.DataFrame({'character_key': [1, 2], 'family': ['Unassigned'] * 2})
    report = pd.DataFrame({'character_key': [1, 2], 'mean_comember_jaccard': [None, None], 'assigned_rate': [1., 0.]})
    summary = summarize_stability(report, baseline)
    assert summary['mean_jaccard'] is None
    assert summary['mean_assigned_rate'] is None
    assert summary['below_target_share'] is None
    assert summary['initial_coverage'] == 0
    assert summary['families'].empty


def test_initially_unassigned_characters_have_measured_repeat_assignment_rates(two_families):
    points, characters, weights, settings = two_families
    baseline = characters.assign(family='Unassigned')
    with patch('app_core.families._partition_families', return_value=np.zeros(len(characters), dtype=int)):
        report = stability_check(points, characters, weights, settings, baseline, (), 2, False)
    assert report.assigned_rate.eq(1).all()
    assert report.mean_comember_jaccard.isna().all()


@pytest.mark.parametrize('bootstrap,expected_builds', [(False, 0), (True, 3)])
def test_stability_reuses_seed_graph_and_rebuilds_bootstrap_evidence(two_families, bootstrap, expected_builds):
    points, characters, weights, settings = two_families
    discovery = discover_families(points, characters, weights, settings)
    with patch('app_core.families.pair_statistics', wraps=pair_statistics) as statistics, \
            patch('app_core.families._family_graph', wraps=family_analysis._family_graph) as graphs:
        stability_check(points, characters, weights, settings, discovery['assignments'], (), 3, bootstrap,
                        discovery=discovery)
    assert statistics.call_count == expected_builds
    assert graphs.call_count == expected_builds


def test_graph_neighbor_ties_keep_character_key_order():
    keys = np.array([40, 10, 30, 20])
    similarity = np.ones((4, 4)) - np.eye(4)
    stats = {'raw': np.full((4, 4), 10), 'jaccard': similarity, 'adjusted': similarity}
    settings = FamilySettings(minimum_players=1, minimum_shared=1, neighbors=1)
    graph, _, _ = family_analysis._family_graph(stats, keys, settings, ())
    assert graph.get_edgelist() == [(0, 1), (1, 2), (1, 3)]


@pytest.mark.parametrize('bootstrap', [False, True])
def test_optimized_stability_matches_repeated_full_discovery(bootstrap):
    rng = np.random.default_rng(7)
    points = rng.choice([0., 10000., 25000., 40000.], size=(80, 9))
    weights = rng.uniform(.2, 3., size=80)
    characters = pd.DataFrame({'character_key': range(9), 'character': list('ABCDEFGHI')})
    settings = FamilySettings(minimum_players=1, minimum_shared=1, minimum_family_size=2, neighbors=3)
    discovery = discover_families(points, characters, weights, settings)
    baseline = discovery['assignments']
    actual = stability_check(points, characters, weights, settings, baseline, (), 5, bootstrap, discovery=discovery)
    sample_rng = np.random.default_rng(settings.seed)
    expected_scores = np.zeros(9)
    expected_assigned = np.zeros(9)
    for repeat in range(5):
        sample = sample_rng.integers(0, len(points), len(points)) if bootstrap else np.arange(len(points))
        candidate = discover_families(points[sample], characters, weights[sample],
                                      replace(settings, seed=settings.seed + repeat + 1))['assignments']
        for i in range(9):
            expected_assigned[i] += candidate.iloc[i].family != 'Unassigned'
            if baseline.iloc[i].family == 'Unassigned':
                expected_scores[i] = np.nan
                continue
            original = set(baseline.index[baseline.family.eq(baseline.iloc[i].family)]) - {i}
            peers = (set(candidate.index[candidate.family.eq(candidate.iloc[i].family)]) - {i}
                     if candidate.iloc[i].family != 'Unassigned' else set())
            expected_scores[i] += len(original & peers) / len(original | peers) if original | peers else 0
    np.testing.assert_allclose(actual.mean_comember_jaccard, expected_scores / 5, rtol=0, atol=0)
    np.testing.assert_allclose(actual.assigned_rate, expected_assigned / 5, rtol=0, atol=0)


def test_repeat_pairs_exclude_shared_unassigned_and_score_original_groups(two_families):
    points, characters, weights, settings = two_families
    baseline = characters.assign(family=['A', 'A', 'A', 'B', 'B', 'Unassigned'])
    repeats = [np.array([0, 0, 1, 1, -1, -1]), np.array([2, 2, 2, 3, 3, -1])]
    with patch('app_core.families._partition_families', side_effect=repeats):
        report = stability_check(points, characters, weights, settings, baseline, (), 2, True)
    # Reverse stored key order to verify that diagnostics align by identity.
    pair_info = report.attrs['co_membership']
    pair_info['character_keys'] = pair_info['character_keys'][::-1]
    pair_info['rates'] = np.asarray(pair_info['rates'])[::-1, ::-1].tolist()
    rows, rates = family_analysis.family_consistency(pair_info, baseline)
    assert rows.iloc[0].own_consistency == .75
    assert rows.iloc[0].alternative_family == 'B'
    assert rows.iloc[0].alternative_consistency == 0
    assert rows.iloc[2].own_consistency == .5
    assert rows.iloc[2].alternative_consistency == .25
    assert rows.iloc[2].separation == .25
    assert rows.iloc[3].alternative_consistency == pytest.approx(1/6)
    assert rows.iloc[4].own_consistency == .5  # all repeats, not just assigned repeats
    assert rows.iloc[4].assigned_rate == .5
    assert pd.isna(rows.iloc[5].own_consistency)
    assert rates[4, 5] == 0  # two unassigned characters are never companions
    np.testing.assert_array_equal(np.diag(rates), report.assigned_rate)


def test_consistency_handles_single_family_singletons_and_invalid_matrix():
    baseline = pd.DataFrame({'character_key': [1, 2], 'character': ['A', 'B'], 'family': ['Solo', 'Unassigned']})
    pairs = {'character_keys': [1, 2], 'rates': [[1., 0.], [0., 0.]]}
    rows, _ = family_analysis.family_consistency(pairs, baseline)
    assert rows.own_consistency.isna().all()
    assert pd.isna(rows.iloc[0].alternative_family)
    assert rows.iloc[1].alternative_family == 'Solo'
    assert rows.iloc[1].alternative_consistency == 0
    pairs['rates'][0][1] = .5
    with pytest.raises(ValueError, match='symmetric probability'):
        family_analysis.family_consistency(pairs, baseline)


def test_family_review_distinguishes_outliers_from_diffuse_families_and_merges():
    baseline = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF'), 'family': ['A']*4 + ['B']*2})
    rates = np.full((6, 6), .01)
    np.fill_diagonal(rates, 1)
    rates[:3, :3] = .95
    rates[3, :3] = rates[:3, 3] = .1
    rates[4, 5] = rates[5, 4] = .9
    np.fill_diagonal(rates, 1)
    pairs = {'character_keys': list(range(6)), 'rates': rates.tolist()}
    families, _ = family_analysis.summarize_family_consistency(pairs, baseline)
    group = families.set_index('family').loc['A']
    assert group.mean_consistency == pytest.approx(.525)
    assert group.retained_consistency == pytest.approx(.95)
    assert group.uplift_pp == pytest.approx(42.5)
    assert group.removed_members == 'D'
    assert group.pattern == 'Sensitive to weakest members'
    assert families.set_index('family').loc['B', 'removed_count'] == 0
    assert families.set_index('family').loc['B', 'pattern'] == 'Cohesive throughout'
    # Two persistent pairs inside one family stay diffuse after removing one member.
    rates[:4, :4] = np.eye(4)
    rates[0, 1] = rates[1, 0] = rates[2, 3] = rates[3, 2] = 1
    pairs['rates'] = rates.tolist()
    families, _ = family_analysis.summarize_family_consistency(pairs, baseline)
    assert families.set_index('family').loc['A', 'pattern'] == 'Loose or possible subgroups'
    # Repeated merges do not become a claim of separately solid families.
    pairs['rates'] = np.ones((6, 6)).tolist()
    families, _ = family_analysis.summarize_family_consistency(pairs, baseline)
    assert families.mean_consistency.eq(1).all()
    assert families.pattern.eq('Overlaps alternatives').all()


def test_refinement_four_states_promotes_stronger_alternative_and_prioritizes_both():
    rows = pd.DataFrame({'character_key': range(8), 'character': list('ABCDEFGH'),
                         'family': ['A'] * 7 + ['Unassigned'], 'alternative_family': ['B'] * 8,
                         'own_consistency': [.9, .2, .6, .2, .5, .9, 0, np.nan],
                         'alternative_consistency': [.1, .9, .7, .3, .9, .4, 0, .85], 'assigned_rate': [1.] * 8})
    result = family_analysis.refine_memberships(rows)
    assert result.state.tolist() == ['Primary only', 'Secondary only', 'Both', 'Indecisive', 'Both', 'Both', 'Indecisive', 'Secondary only']
    assert result.iloc[1].final_primary == 'B'
    assert result.iloc[2].final_primary == 'B'
    assert result.iloc[2].final_secondary == 'A'
    assert result.iloc[5].final_primary == 'A'
    assert result.iloc[5].final_secondary == 'B'
    assert pd.isna(result.iloc[3].final_primary)
    assert family_analysis.refine_memberships(rows, 0, 0).iloc[6].state == 'Indecisive'
    with pytest.raises(ValueError, match='Thresholds'):
        family_analysis.refine_memberships(rows, .4, .8)
