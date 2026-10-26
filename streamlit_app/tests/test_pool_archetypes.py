"""Contracts for pool archetype features, masking and deterministic fitting."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from app_core.pool_archetypes import (
    ROLE_COLUMNS,
    ArchetypeSettings,
    assign_archetypes,
    champion_presence,
    design_matrix,
    eligible_mask,
    family_weights,
    fit_archetypes,
    fit_nmf,
    group_prevalence,
    inspect_families,
    pair_lift,
    pool_concentration,
    pool_role_mix,
    pool_size_bands,
    profile_archetypes,
    profile_similarity,
    sweep_components,
    tier_prevalence,
)

FAMILIES = ['F01', 'F02', 'F03']


def test_pool_concentration_matches_hand_values():
    result = pool_concentration([{'points': 50}, {'points': 50}])
    assert result == pytest.approx({'top1_share': 0.5, 'normalized_entropy': 1.0})
    single = pool_concentration([{'points': 10}])
    assert single == {'top1_share': 1.0, 'normalized_entropy': 0.0}
    assert pool_concentration([{'points': 0}, {'points': 0}])['top1_share'] == 0.5
    assert np.isnan(pool_concentration([])['top1_share'])


def test_eligibility_masks_small_and_uncovered_pools():
    frame = pd.DataFrame({'pool_size': [0, 2, 3, 5], 'F01': [0, .5, .5, 0], 'F02': [0, 0, 0, 0], 'F03': [0, 0, 0, 0]})
    assert eligible_mask(frame, FAMILIES, 3).tolist() == [False, False, True, False]


def test_design_matrix_appends_weighted_concentration():
    frame = pd.DataFrame({'F01': [1.0], 'F02': [0.0], 'F03': [.5], 'top1_share': [.8], 'normalized_entropy': [.5]})
    assert design_matrix(frame, FAMILIES, False, .4).shape == (1, 3)
    assert design_matrix(frame, FAMILIES, True, .5)[0, 3:].tolist() == [.4, .25]


def two_group_matrix():
    rng = np.random.default_rng(0)
    first = np.clip(rng.normal([.9, .1, .1], .05, (60, 3)), 0, 1)
    second = np.clip(rng.normal([.1, .9, .8], .05, (60, 3)), 0, 1)
    return np.vstack([first, second])


def test_nmf_recovers_groups_deterministically():
    matrix = two_group_matrix()
    loadings, profiles, _ = fit_nmf(matrix, 2, 0.0, 7)
    again, _, _ = fit_nmf(matrix, 2, 0.0, 7)
    np.testing.assert_allclose(loadings, again)
    assert profiles.max(axis=1) == pytest.approx([1, 1])
    labels = assign_archetypes(loadings, .25).archetype.to_numpy()
    assert len(set(labels[:60])) == 1 and len(set(labels[60:])) == 1 and labels[0] != labels[-1]


def test_assignment_separates_breadth_from_mixing():
    loadings = np.array([[.9, .1], [.6, .5], [.2, .1], [.05, .0]])
    result = assign_archetypes(loadings, .25)
    assert result.kind.tolist() == ['Single', 'Blend', 'Diffuse', 'Diffuse']
    assert result.active_archetypes.tolist() == [1, 2, 0, 0] and result.archetype.tolist() == [0, 0, 0, 0]
    assert result.top_share.iloc[0] == pytest.approx(.9) and result.strength.iloc[1] == .6
    assert assign_archetypes(np.array([[0., 0.]]), .25).top_share.tolist() == [0.]


def test_broad_pool_with_thin_even_loadings_is_diffuse_not_a_blend():
    result = assign_archetypes(np.array([[.2, .2, .2, .2]]), .25)
    assert result.top_share.iloc[0] == pytest.approx(.25) and result.kind.tolist() == ['Diffuse']


def test_family_weights_downweight_common_families_and_skip_concentration():
    matrix = np.array([[.9, .1, .5], [.8, .0, .5], [.7, .1, .5]])
    weights = family_weights(matrix, 1.0, 2)
    assert weights[0] < weights[1] and weights[:2].mean() == pytest.approx(1.0) and weights[2] == 1.0
    assert family_weights(matrix, 0.0, 2).tolist() == [1., 1., 1.]


def test_fit_archetypes_returns_profiles_in_affinity_units():
    matrix = two_group_matrix()
    loadings, profiles, _ = fit_archetypes(matrix, ArchetypeSettings(components=2, family_weighting=1.0), 3)
    assert profiles.max(axis=1) == pytest.approx([1, 1])
    assert np.abs(loadings @ profiles - matrix).mean() < .1


def test_profile_similarity_is_one_on_the_diagonal():
    similarity = profile_similarity(np.array([[1., 0.], [1., 1.], [0., 2.]]))
    assert np.diag(similarity) == pytest.approx([1, 1, 1]) and similarity[0, 2] == pytest.approx(0)


def test_pool_size_bands_have_equal_counts_and_range_labels():
    bands = pool_size_bands(pd.Series([3, 3, 4, 5, 8, 9, 20, 30]), 4)
    assert list(bands.categories) == ['3-3', '4-5', '8-9', '20-30'] and pd.Series(bands).value_counts().eq(2).all()


def test_sweep_reports_stable_components_and_held_out_error():
    sweep = sweep_components(two_group_matrix(), [2], 0.0, 1, bootstraps=2)
    assert sweep.stability.iloc[0] > .95 and sweep.held_out_error.iloc[0] < .1


def test_settings_validate_ranges():
    with pytest.raises(ValueError):
        ArchetypeSettings(components=1)
    with pytest.raises(ValueError):
        ArchetypeSettings(active_loading=0)
    with pytest.raises(ValueError):
        ArchetypeSettings(family_weighting=3)


ROLES = pd.DataFrame({'role_top': [1., 0.], 'role_jungle': [0., 0.], 'role_middle': [0., .5],
                      'role_bottom': [0., 0.], 'role_support': [0., .5]}, index=[10, 20])


def test_pool_role_mix_is_mastery_weighted_and_skips_unknown_champions():
    mix = pool_role_mix([{'key': 10, 'points': 75}, {'key': 20, 'points': 25}, {'key': 99, 'points': 1000}], ROLES)
    assert mix['role_top'] == pytest.approx(.75) and mix['role_middle'] == pytest.approx(.125)
    assert sum(mix.values()) == pytest.approx(1)
    assert np.isnan(pool_role_mix([{'key': 99, 'points': 5}], ROLES)['role_top'])
    assert list(mix) == list(ROLE_COLUMNS.values())


def inspection_frame():
    return pd.DataFrame({'F01': [1., .6, .2, 0.], 'F02': [0., .4, .9, .8], 'tier': ['GOLD', 'GOLD', 'IRON', 'IRON']})


def test_inspect_families_reach_median_and_lift_over_passing_players():
    frame, weights = inspection_frame(), pd.Series([1., 1., 1., 1.])
    definitions = pd.DataFrame({'title': ['a', 'b']}, index=pd.Index(['F01', 'F02'], name='family'))
    inside = np.array([True, True, False, False])
    result = inspect_families(frame, ['F01', 'F02'], definitions, inside, .5, weights).set_index('family')
    assert result.loc['F01', ['players_passing', 'reach', 'all_players_reach']].tolist() == [2, 1., .5]
    assert result.loc['F01', 'median_affinity'] == pytest.approx(.8) and result.loc['F01', 'lift'] == pytest.approx(2)
    assert result.loc['F02', 'players_passing'] == 0 and np.isnan(result.loc['F02', 'median_affinity'])
    heavy = inspect_families(frame, ['F01', 'F02'], definitions, inside, .5, pd.Series([1., 3., 1., 1.]))
    assert heavy.set_index('family').loc['F01', 'median_affinity'] == pytest.approx(.7)


def test_profile_archetypes_uses_weights_for_share_and_role_means():
    frame = inspection_frame().assign(pool_size=[3, 3, 4, 4], top1_share=.5, normalized_entropy=.5,
                                      **{column: [1., 1., 0., 0.] if column == 'role_top' else [0., 0., 1., 1.]
                                         if column == 'role_support' else 0. for column in ROLE_COLUMNS.values()})
    assignment = pd.DataFrame({'archetype': [0, 0, 1, 1], 'kind': ['Single', 'Blend', 'Diffuse', 'Diffuse'],
                               'strength': [.9, .8, .1, .2]})
    profiles = np.array([[1., 0.], [0., 1.]])
    summary = profile_archetypes(frame, ['F01', 'F02'], profiles, assignment, {}, pd.Series([1., 1., 3., 3.]))
    assert summary.share.tolist() == pytest.approx([.25, .75]) and summary.players.tolist() == [2, 2]
    assert summary.loc[1, 'Support'] == 1.0 and summary.loc[0, 'Top'] == 1.0
    assert summary.loc[0, ['single_share', 'blend_share', 'diffuse_share']].tolist() == [.5, .5, 0.]
    assert summary.loc[1, 'diffuse_share'] == 1.0 and summary.loc[1, 'median_strength'] == pytest.approx(.15)


def test_champion_presence_and_prevalence():
    pools = pd.Series([[{'key': 1, 'name': 'A'}, {'key': 2, 'name': 'B'}], [{'key': 2, 'name': 'B'}], []])
    presence, names = champion_presence(pools)
    assert names == {1: 'A', 2: 'B'} and presence.to_numpy().tolist() == [[True, True], [False, True], [False, False]]
    result = group_prevalence(presence, np.array([True, False, False]))
    assert result.loc[2, ['players', 'inside_reach', 'outside_reach', 'lift']].tolist() == [1, 1., .5, 2.]
    assert result.loc[1, 'lift'] == 0 or np.isnan(result.loc[1, 'lift'])


def test_pair_lift_ranks_excess_and_marks_shared_groups():
    flags = pd.DataFrame({'A': [1, 1, 1, 0, 0, 0], 'B': [1, 1, 1, 0, 0, 1], 'C': [1, 0, 0, 1, 1, 1]}).astype(bool)
    inside = np.array([True, True, True, False, False, False])
    result = pair_lift(flags, inside, 2, {'A': frozenset({'F1'}), 'B': frozenset({'F1', 'F2'}), 'C': frozenset({'F3'})})
    assert result.iloc[0][['first', 'second', 'players']].tolist() == ['A', 'B', 3]
    assert result.iloc[0].inside_share == 1.0 and result.iloc[0].outside_share == 0.0 and np.isnan(result.iloc[0].lift)
    assert result.iloc[0].shared == 'F1' and len(result) == 1
    assert len(pair_lift(flags, inside, 1, None)) == 3


def test_tier_prevalence_reports_share_and_distance_from_included_baseline():
    tiers = pd.Series(['GOLD', 'GOLD', 'IRON', 'IRON', 'MASTER', 'MASTER'])
    inside = np.array([True, False, False, False, True, True])
    result = tier_prevalence(tiers, inside, ['IRON', 'GOLD'])
    assert result.share_of_tier.to_dict() == {'GOLD': .5, 'IRON': 0.} and result.players.to_dict() == {'GOLD': 2, 'IRON': 2}
    assert result.over_under.to_dict() == {'GOLD': .25, 'IRON': -.25}
    assert tier_prevalence(tiers, inside).baseline.iloc[0] == pytest.approx(.5)
