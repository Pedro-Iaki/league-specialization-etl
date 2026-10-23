from __future__ import annotations

import itertools
import math
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

pytest.importorskip('scipy')

from app_core.family_cover import compact_audience_cover, coverage_metrics
from app_core.family_cover import SCORE_OBJECTIVE, collection_costs, compare_cover_quality, _validated_solution


def catalog(n):
    return pd.DataFrame({'character_key': range(n), 'character': [str(i) for i in range(n)]})


def candidates(groups):
    return pd.DataFrame([
        dict(family_id=name, scenario='test', family=name, basis='Full family',
             member_keys=keys, included_characters=len(keys), qualifying_consistency=consistency)
        for name, keys, consistency in groups], columns=[
            'family_id', 'scenario', 'family', 'basis', 'member_keys', 'included_characters', 'qualifying_consistency'])


def objective(groups, low=2, high=3, preference=.5):
    metrics = coverage_metrics([row.member_keys for row in groups])
    cost = sum(2 - row.qualifying_consistency + 10 * preference * max(
        math.log2(low / len(row.member_keys)), math.log2(len(row.member_keys) / high), 0) for row in groups)
    return metrics['extra_memberships'], -metrics['covered'], len(groups), round(cost, 8)


@pytest.mark.parametrize('target', [1., .65, .34])
def test_compact_objectives_match_exhaustive_search_and_preserve_evidence(target):
    pool = candidates([
        ('A', [0, 1, 2], .95), ('B', [2, 3, 4], .99), ('C', [0, 1], .85),
        ('D', [2, 3], .9), ('E', [4, 5], .86), ('F', [0, 1, 2, 3, 4, 5], .8)])
    original = pool.copy(deep=True)
    result = compact_audience_cover(pool, catalog(7), ideal_minimum=2, ideal_maximum=3, coverage_target=target)
    required = math.ceil(target * 6)
    options = []
    for mask in itertools.product([False, True], repeat=len(pool)):
        groups = list(pool.loc[list(mask)].itertuples())
        if coverage_metrics([row.member_keys for row in groups])['covered'] >= required:
            options.append(objective(groups))
    assert objective(list(result['families'].itertuples())) == min(options)
    assert result['optimal'] and result['feasible']
    assert result['eligible_characters'] == 6 and result['total'] == 7
    assert result['required_characters'] == required and not result['complete']
    assert result['zero_exclusive_families'] == 0
    assert result['characters'].iloc[-1].coverage_status == 'No eligible family'
    pd.testing.assert_frame_equal(pool, original)
    reordered = compact_audience_cover(pool.iloc[::-1], catalog(7), ideal_minimum=2, ideal_maximum=3, coverage_target=target)
    assert result['families'].family_id.tolist() == reordered['families'].family_id.tolist()


def test_global_cover_replaces_overlapping_combination_and_preserves_duplicate_provenance():
    pool = candidates([('A', [0, 1, 2], 1.), ('B', [2, 3, 4], 1.), ('C', [0, 1], .9),
                       ('D', [2, 3], .9), ('E', [4, 5], .9), ('F', [5, 0], 1.),
                       ('C weak', [0, 1], .8)])
    result = compact_audience_cover(pool, catalog(6), ideal_minimum=2, ideal_maximum=3)
    assert result['complete'] and result['extra_memberships'] == 0
    assert set(result['families'].family) == {'C', 'D', 'E'}
    assert result['families'].set_index('family').loc['C', 'alternative_family_ids'] == ['C', 'C weak']
    assert result['families'].exclusive_share.eq(1).all()


def test_cost_filter_empty_pool_and_partial_target():
    pool = candidates([('A', [0, 1], 1.), ('B', [2, 3, 4, 5], 1.)])
    result = compact_audience_cover(pool, catalog(6), ideal_minimum=2, ideal_maximum=2, max_family_cost=1.1)
    assert result['eligible_characters'] == 2 and result['covered'] == 2
    assert set(result['characters'].iloc[2:].coverage_status) == {'Family cost ceiling'}
    for empty in [pool.iloc[:0], pool]:
        result = compact_audience_cover(empty, catalog(6), max_family_cost=.5)
        assert result['families'].empty and result['eligible_characters'] == 0
        assert result['covered'] == 0 and result['feasible']
    result = compact_audience_cover(pool, catalog(6), coverage_target=.5)
    assert result['covered'] >= 3


def test_lower_target_can_leave_eligible_characters_out_to_avoid_repeat_memberships():
    pool = candidates([('A', [0, 1], 1.), ('B', [1, 2], 1.)])
    partial = compact_audience_cover(pool, catalog(4), coverage_target=.66)
    full = compact_audience_cover(pool, catalog(4), coverage_target=.67)
    assert partial['required_characters'] == 2 and partial['covered'] == 2
    assert partial['extra_memberships'] == 0
    reasons = partial['characters'].coverage_status.tolist()
    assert reasons.count('Not selected under coverage target') == 1
    assert reasons.count('No eligible family') == 1
    assert full['required_characters'] == 3 and full['covered'] == 3
    assert full['extra_memberships'] == 1


@pytest.mark.parametrize('target', [1., .8])
@pytest.mark.parametrize('exclusive', [.25, .5, 1.])
def test_exclusive_share_constraint_matches_exhaustive_search(target, exclusive):
    pool = candidates([('A', [0, 1, 2], .95), ('B', [2, 3, 4], .99),
                       ('C', [4, 5], .85), ('D', [0, 1, 3], .9)])
    required = math.ceil(target * 6)
    valid = []
    for mask in itertools.product([False, True], repeat=len(pool)):
        groups = list(pool.loc[list(mask)].itertuples())
        counts = {}
        for group in groups:
            for key in group.member_keys:
                counts[key] = counts.get(key, 0) + 1
        if len(counts) < required:
            continue
        if all(sum(counts[key] == 1 for key in group.member_keys) >= math.ceil(exclusive * len(group.member_keys))
               for group in groups):
            valid.append(objective(groups))
    result = compact_audience_cover(pool, catalog(6), ideal_minimum=2, ideal_maximum=3,
                                    coverage_target=target, minimum_exclusive_share=exclusive)
    assert result['minimum_exclusive_share'] == exclusive
    if valid:
        assert result['feasible'] and result['optimal'] and not result['infeasible']
        assert objective(list(result['families'].itertuples())) == min(valid)
        assert result['families'].exclusive_share.ge(exclusive).all()
    else:
        assert result['infeasible'] and not result['feasible']
        assert result['solver']['stages'][0]['status'] == 2


def test_exclusive_share_rounds_up_and_reports_infeasibility_distinct_from_timeout():
    pool = candidates([('A', [0, 1, 2], 1.), ('B', [2, 3], 1.)])
    boundary = compact_audience_cover(pool, catalog(4), minimum_exclusive_share=.5)
    impossible = compact_audience_cover(pool, catalog(4), minimum_exclusive_share=.51)
    assert boundary['complete'] and boundary['families'].exclusive_share.min() == .5
    assert impossible['infeasible'] and not impossible['feasible']
    limited = SimpleNamespace(status=1, x=None, message='Time limit reached')
    with patch('scipy.optimize.milp', return_value=limited):
        unknown = compact_audience_cover(pool, catalog(4), minimum_exclusive_share=.51)
    assert not unknown['infeasible'] and not unknown['feasible']
    from streamlit.testing.v1 import AppTest
    for result, expected in [(impossible, 'infeasible'), (unknown, 'not been proven')]:
        app = AppTest.from_string("""
import streamlit as st
from app_core.family_cohort_view import _compact_solver_status
_compact_solver_status(st.session_state['cover'])
""")
        app.session_state['cover'] = result
        app.run()
        assert not app.exception
        messages = [message.value for message in app.error] + [message.value for message in app.warning]
        assert any(expected in message for message in messages)


def test_exclusive_constraint_is_preserved_by_timeout_redundancy_cleanup():
    pool = candidates([('A', [0, 1, 2], 1.), ('B', [1, 2, 3], 1.), ('C', [1, 2], 1.)])
    # Counts are 1,3,3,1: only A and B have exclusive characters. A feasible
    # constrained timeout cannot accept the redundant C; validate its rejection.
    values = np.r_[np.ones(3), np.ones(4), [1, 0, 0, 1]]
    limited = SimpleNamespace(status=1, x=values, message='Time limit reached')
    with patch('scipy.optimize.milp', return_value=limited):
        result = compact_audience_cover(pool, catalog(4), minimum_exclusive_share=.25)
    assert not result['feasible']
    # Without C, both families meet the constraint even in a limited result.
    limited.x = np.r_[[1, 1, 0], np.ones(4), [1, 0, 0, 1]]
    with patch('scipy.optimize.milp', return_value=limited):
        result = compact_audience_cover(pool, catalog(4), minimum_exclusive_share=.25)
    assert result['feasible'] and not result['optimal']
    assert result['families'].exclusive_share.ge(.25).all()


def test_time_limit_cleanup_is_sequential_and_no_incumbent_is_explicit():
    pool = candidates([('A', [0, 1], 1.), ('B', [1, 2], 1.), ('C', [0, 2], 1.)])
    limited = SimpleNamespace(status=1, x=np.ones(6), message='Time limit reached', mip_gap=.8, mip_dual_bound=0.)
    with patch('scipy.optimize.milp', return_value=limited):
        result = compact_audience_cover(pool, catalog(3))
    assert result['feasible'] and not result['optimal']
    assert result['covered'] == 3 and result['families'].shape[0] == 2
    assert result['zero_exclusive_families'] == 0
    assert len(result['solver']['removed_redundant_family_ids']) == 1
    for values in [None, np.full(6, .5), np.zeros(6)]:
        limited.x = values
        with patch('scipy.optimize.milp', return_value=limited):
            result = compact_audience_cover(pool, catalog(3))
        assert not result['feasible'] and not result['optimal']
        assert result['families'].empty


def test_later_timeout_keeps_validated_previous_stage():
    pool = candidates([('A', [0, 1], 1.)])
    first = SimpleNamespace(status=0, x=np.ones(3), message='Optimal', mip_gap=0., mip_dual_bound=0.)
    later = SimpleNamespace(status=1, x=None, message='Time limit reached')
    with patch('scipy.optimize.milp', side_effect=[first, later]):
        result = compact_audience_cover(pool, catalog(2))
    assert result['feasible'] and not result['optimal'] and result['complete']
    assert [stage['optimal'] for stage in result['solver']['stages']] == [True, False]


@pytest.mark.parametrize('kwargs', [dict(coverage_target=0), dict(coverage_target=np.nan), dict(coverage_target=1.1),
                                  dict(time_limit=0), dict(time_limit=np.inf), dict(max_family_cost=-1),
                                  dict(ideal_minimum=3, ideal_maximum=2), dict(size_preference=np.nan),
                                  dict(minimum_exclusive_share=-.1), dict(minimum_exclusive_share=1.1),
                                  dict(minimum_exclusive_share=np.nan)])
def test_invalid_controls(kwargs):
    with pytest.raises(ValueError):
        compact_audience_cover(candidates([]), catalog(3), **kwargs)


def v2_objective(groups, low, high, preference, penalty):
    """Independent subset oracle, without the solver's cost or exclusivity helpers."""
    counts = {}
    for family in groups:
        for key in family.member_keys:
            counts[key] = counts.get(key, 0) + 1
    cost = 0.
    for family in groups:
        size = len(family.member_keys)
        base = 2 - family.qualifying_consistency + 10 * preference * max(math.log2(low / size), math.log2(size / high), 0)
        exclusive = sum(counts[key] == 1 for key in family.member_keys) / size
        cost += base + penalty * (1 - exclusive)
    return -len(counts), cost, len(groups)


@pytest.mark.parametrize('penalty', [0., .5, 1., 2.])
@pytest.mark.parametrize('exclusive', [0., .25, .5, 1.])
@pytest.mark.parametrize('target', [.6, 1.])
def test_v2_score_matches_exhaustive_subsets(penalty, exclusive, target):
    pool = candidates([('A', [0, 1, 2], .95), ('B', [2, 3, 4], .99), ('C', [4, 5], .85),
                       ('D', [0, 1, 3], .9), ('E', [0, 1, 2, 3, 4, 5], .8)])
    options = []
    for mask in itertools.product([False, True], repeat=len(pool)):
        groups = list(pool.loc[list(mask)].itertuples())
        counts = {key: sum(key in g.member_keys for g in groups) for g in groups for key in g.member_keys}
        if len(counts) >= math.ceil(target * 6) and all(
                sum(counts[k] == 1 for k in g.member_keys) >= math.ceil(exclusive * len(g.member_keys) - 1e-9)
                for g in groups):
            options.append(v2_objective(groups, 2, 3, .1, penalty))
    result = compact_audience_cover(pool, catalog(7), ideal_minimum=2, ideal_maximum=3, size_preference=.1,
        compact_objective=SCORE_OBJECTIVE, overlap_penalty=penalty, minimum_exclusive_share=exclusive, coverage_target=target)
    assert result['optimal'] and result['feasible']
    actual = v2_objective(list(result['families'].itertuples()), 2, 3, .1, penalty)
    expected = min(options)
    assert actual[0] == expected[0] and actual[2] == expected[2]
    assert actual[1] == pytest.approx(expected[1], abs=2e-6)
    assert result['adjusted_cost'] == pytest.approx(actual[1])
    assert result['adjusted_cost'] == pytest.approx(result['base_cost'] + result['overlap_cost'])
    assert result['solver']['objective_count'] == 3
    assert result['families'].exclusive_share.ge(exclusive - 1e-9).all()


def test_v2_active_penalty_can_trade_size_and_consistency_for_exclusivity():
    pool = candidates([('backbone', [0, 1, 2, 4], .99), ('shared', [0, 1, 2, 3], .99), ('exclusive', [3], .85)])
    results = []
    for penalty in [.25, 1.]:
        results.append(compact_audience_cover(pool, catalog(5), ideal_minimum=4, ideal_maximum=4,
            size_preference=.03, compact_objective=SCORE_OBJECTIVE, overlap_penalty=penalty, minimum_exclusive_share=.25))
    weak_penalty, strong_penalty = results
    assert set(weak_penalty['families'].family_id) == {'backbone', 'shared'}
    assert weak_penalty['families'].exclusive_share.eq(.25).all()
    assert set(strong_penalty['families'].family_id) == {'backbone', 'exclusive'}
    assert strong_penalty['families'].exclusive_share.eq(1.).all()
    # Exclusivity remains calculated and penalized even with the hard floor disabled.
    without_floor = compact_audience_cover(pool, catalog(5), ideal_minimum=4, ideal_maximum=4,
        size_preference=.03, compact_objective=SCORE_OBJECTIVE, overlap_penalty=1.)
    assert set(without_floor['families'].family_id) == {'backbone', 'exclusive'}


def test_v2_coverage_has_priority_over_arbitrarily_high_penalty():
    pool = candidates([('A', [0, 1], .9), ('B', [1, 2], .9)])
    legacy = compact_audience_cover(pool, catalog(3), coverage_target=.6)
    result = compact_audience_cover(pool, catalog(3), coverage_target=.6,
                                   compact_objective=SCORE_OBJECTIVE, overlap_penalty=1000.)
    assert legacy['covered'] == 2 and result['covered'] == 3
    assert result['adjusted_cost'] > 1000


def test_v2_base_ceiling_and_duplicate_evidence_provenance():
    pool = candidates([('large', list(range(28)), .9), ('large_weaker', list(range(28)), .8), ('small', list(range(12)), .75)])
    uncapped = compact_audience_cover(pool, catalog(28), ideal_minimum=9, ideal_maximum=16, size_preference=.3,
        compact_objective=SCORE_OBJECTIVE, overlap_penalty=2)
    capped = compact_audience_cover(pool, catalog(28), ideal_minimum=9, ideal_maximum=16, size_preference=.3,
        max_family_cost=3, compact_objective=SCORE_OBJECTIVE, overlap_penalty=2)
    assert uncapped['covered'] == 28 and capped['covered'] == 12
    assert uncapped['families'].iloc[0].alternative_family_ids == ['large', 'large_weaker']
    shared = candidates([('A', [0, 1], .9), ('B', [1, 2], .9)])
    result = compact_audience_cover(shared, catalog(3), ideal_minimum=2, ideal_maximum=2,
        max_family_cost=1.2, compact_objective=SCORE_OBJECTIVE, overlap_penalty=2)
    assert result['covered'] == 3 and result['families'].adjusted_cost.gt(1.2).all()


@pytest.mark.parametrize('limited_stage', [1, 2, 3])
def test_v2_stage_timeouts_keep_valid_incumbents_and_reconciled_cost(limited_stage):
    from scipy.optimize import milp
    calls = []
    def limited(*args, **kwargs):
        result = milp(*args, **kwargs)
        calls.append(result)
        if len(calls) == limited_stage:
            result.status = 1
            result.message = 'Test timeout with incumbent'
        return result
    with patch('scipy.optimize.milp', side_effect=limited):
        result = compact_audience_cover(candidates([('A', [0, 1], .9), ('B', [1, 2], .95), ('C', [0, 2], .8)]),
            catalog(3), ideal_minimum=2, ideal_maximum=2, compact_objective=SCORE_OBJECTIVE, overlap_penalty=1.)
    assert result['feasible'] and not result['optimal'] and result['covered'] == 3
    assert sum(s['optimal'] for s in result['solver']['stages']) == limited_stage - 1
    scored = collection_costs(result['families'], 1.)
    assert scored.adjusted_cost.sum() == pytest.approx(result['adjusted_cost'])


def test_v2_mixed_variable_validation_and_retry_comparison():
    from scipy.sparse import eye
    assert _validated_solution([1., .25], eye(2), [0., 0.], [1., 1.], [1, 0]) is not None
    assert _validated_solution([.25, 1.], eye(2), [0., 0.], [1., 1.], [1, 0]) is None
    def cover(covered, cost, extra):
        return dict(feasible=True, covered=covered, adjusted_cost=cost, extra_memberships=extra,
                    families=pd.DataFrame([1, 2]), compact_objective=SCORE_OBJECTIVE)
    assert compare_cover_quality(cover(5, 10, 5), cover(4, 1, 0)) < 0
    assert compare_cover_quality(cover(5, 2, 5), cover(5, 3, 0)) < 0
    assert compare_cover_quality(cover(5, 2 + 1e-8, 5), cover(5, 2, 0)) == 0


@pytest.mark.parametrize('kwargs', [dict(overlap_penalty=-1), dict(overlap_penalty=np.nan),
    dict(overlap_penalty=np.inf), dict(overlap_penalty=True), dict(compact_objective='typo')])
def test_v2_invalid_controls(kwargs):
    with pytest.raises(ValueError):
        compact_audience_cover(candidates([]), catalog(3), **{'compact_objective': SCORE_OBJECTIVE, **kwargs})


def test_v2_empty_pool_infeasibility_and_missing_incumbent():
    empty = compact_audience_cover(candidates([]), catalog(3), compact_objective=SCORE_OBJECTIVE, overlap_penalty=1.)
    assert empty['feasible'] and empty['covered'] == 0 and empty['adjusted_cost'] == 0
    pool = candidates([('A', [0, 1], .9), ('B', [1, 2], .95)])
    impossible = compact_audience_cover(pool, catalog(3), compact_objective=SCORE_OBJECTIVE,
                                       overlap_penalty=1., minimum_exclusive_share=1.)
    assert impossible['infeasible'] and not impossible['feasible']
    with patch('scipy.optimize.milp', return_value=SimpleNamespace(status=1, x=None, message='Timeout')):
        limited = compact_audience_cover(pool, catalog(3), compact_objective=SCORE_OBJECTIVE, overlap_penalty=1.)
    assert not limited['infeasible'] and not limited['feasible']
