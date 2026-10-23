"""Global selection of existing families with versioned coverage and cost objectives."""
from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd


LEGACY_OBJECTIVE = 'legacy_min_overlap'
SCORE_OBJECTIVE = 'coverage_score_v2'
SCORE_ABS_TOL = 1e-6
SCORE_REL_TOL = 1e-9


def base_family_cost(size, consistency, ideal_minimum=10, ideal_maximum=15, size_preference=.5):
    """Shared base cost; the optional ceiling never includes overlap penalties."""
    sizes = np.asarray(size, dtype=float)
    distance = np.maximum(np.maximum(np.log2(ideal_minimum / sizes), np.log2(sizes / ideal_maximum)), 0)
    return 2 - consistency + 10 * size_preference * distance


def collection_costs(families: pd.DataFrame, overlap_penalty: float = 0.) -> pd.DataFrame:
    """Recompute collection-dependent exclusivity and additive costs from memberships."""
    scored = families.copy()
    counts = {}
    for keys in scored.member_keys:
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    scored['exclusive_characters'] = [sum(counts[key] == 1 for key in keys) for keys in scored.member_keys]
    scored['exclusive_share'] = scored.exclusive_characters / scored.member_keys.map(len)
    scored['overlap_cost'] = overlap_penalty * (1 - scored.exclusive_share)
    scored['adjusted_cost'] = scored.selection_cost + scored.overlap_cost
    return scored


def score_tolerance(value):
    return SCORE_ABS_TOL + SCORE_REL_TOL * abs(value)


def compare_cover_quality(first, second):
    """Compare retry incumbents within one policy; return -1 when first is better."""
    if first.get('compact_objective', LEGACY_OBJECTIVE) != second.get('compact_objective', LEGACY_OBJECTIVE):
        raise ValueError('Cannot compare covers with different objective versions.')
    if first.get('compact_objective', LEGACY_OBJECTIVE) == SCORE_OBJECTIVE:
        left = (not first['feasible'], -first['covered'], first['adjusted_cost'], len(first['families']))
        right = (not second['feasible'], -second['covered'], second['adjusted_cost'], len(second['families']))
        if left[:2] != right[:2]:
            return -1 if left[:2] < right[:2] else 1
        if not math.isclose(left[2], right[2], abs_tol=SCORE_ABS_TOL, rel_tol=SCORE_REL_TOL):
            return -1 if left[2] < right[2] else 1
        return (left[3] > right[3]) - (left[3] < right[3])
    def legacy(cover):
        return (not cover['feasible'], cover['extra_memberships'], -cover['covered'], len(cover['families']),
                cover['families'].selection_cost.sum())
    left, right = legacy(first), legacy(second)
    return (left > right) - (left < right)


def coverage_metrics(member_sets: list[list]) -> dict:
    counts = {}
    for members in member_sets:
        for key in members:
            counts[key] = counts.get(key, 0) + 1
    covered = len(counts)
    memberships = sum(counts.values())
    return {'covered': covered, 'families': len(member_sets),
            'extra_memberships': memberships - covered,
            'repeated_characters': sum(value > 1 for value in counts.values()),
            'memberships_per_character': memberships / covered if covered else None,
            'zero_exclusive_families': sum(not any(counts[key] == 1 for key in group) for group in member_sets)}


def compact_audience_cover(candidates: pd.DataFrame, universe: pd.DataFrame,
                           include_retained: bool = True, ideal_minimum: int = 10,
                           ideal_maximum: int = 15, size_preference: float = .5,
                           max_family_cost: float | None = None,
                           coverage_target: float = 1., time_limit: float = 30.,
                           minimum_exclusive_share: float = 0.,
                           compact_objective: str = LEGACY_OBJECTIVE, overlap_penalty: float = 0.) -> dict:
    """Legacy minimizes repeats first; v2 maximizes coverage, then minimizes adjusted cost.

    Each completed objective is fixed before the next solve. A timed-out result
    is feasible evidence, not a claim of optimality. Coverage targets refer to
    eligible characters; the full roster remains the reporting denominator.
    """
    if (not np.isfinite(coverage_target) or not 0 < coverage_target <= 1
            or not np.isfinite(time_limit) or time_limit <= 0):
        raise ValueError('Use a coverage target in (0, 1] and a positive finite time limit.')
    if (not 1 <= ideal_minimum <= ideal_maximum or not np.isfinite(size_preference)
            or not 0 <= size_preference <= 1):
        raise ValueError('Use an ordered positive preferred size range and preference in [0, 1].')
    if max_family_cost is not None and (not np.isfinite(max_family_cost) or max_family_cost <= 0):
        raise ValueError('Maximum family cost must be positive and finite.')
    if not np.isfinite(minimum_exclusive_share) or not 0 <= minimum_exclusive_share <= 1:
        raise ValueError('Minimum exclusive share must be a finite number between 0 and 1.')
    if compact_objective not in {LEGACY_OBJECTIVE, SCORE_OBJECTIVE}:
        raise ValueError('Unknown Compact objective version.')
    if isinstance(overlap_penalty, bool) or not np.isfinite(overlap_penalty) or overlap_penalty < 0:
        raise ValueError('Overlap penalty must be nonnegative and finite.')
    if compact_objective == LEGACY_OBJECTIVE and overlap_penalty:
        raise ValueError('Legacy Compact does not support an overlap penalty.')
    v2 = compact_objective == SCORE_OBJECTIVE
    started = time.perf_counter()
    catalog = universe[['character_key', 'character']].copy().reset_index(drop=True)
    if catalog.character_key.duplicated().any():
        raise ValueError('Character catalog keys must be unique.')
    pool = (candidates if include_retained else candidates.loc[candidates.basis.eq('Full family')]).copy()
    pool = pool.drop_duplicates('family_id').sort_values('family_id').reset_index(drop=True)
    catalog_keys = set(catalog.character_key)
    for family in pool.itertuples():
        if (not family.member_keys or len(set(family.member_keys)) != len(family.member_keys)
                or not set(family.member_keys).issubset(catalog_keys)
                or family.included_characters != len(family.member_keys)
                or not np.isfinite(family.qualifying_consistency)
                or not 0 <= family.qualifying_consistency <= 1):
            raise ValueError('Invalid candidate membership, size or consistency.')
    raw_keys = set().union(*(set(keys) for keys in pool.member_keys))
    sizes = pool.included_characters.to_numpy(dtype=float)
    pool['proportional_distance'] = np.maximum(
        np.maximum(np.log2(ideal_minimum / sizes), np.log2(sizes / ideal_maximum)), 0)
    pool['selection_cost'] = base_family_cost(sizes, pool.qualifying_consistency.to_numpy(),
                                             ideal_minimum, ideal_maximum, size_preference)
    if max_family_cost is not None:
        pool = pool.loc[pool.selection_cost.le(max_family_cost + 1e-12)].copy()
    # Equal memberships provide the same coverage decision. Preserve their separate
    # provenance, but optimize with the cheapest eligible evidence representative.
    pool['_members'] = pool.member_keys.map(lambda keys: tuple(sorted(keys)))
    alternatives = pool.groupby('_members').family_id.agg(list).to_dict()
    pool = pool.sort_values(['selection_cost', 'family_id']).drop_duplicates('_members')
    pool = pool.sort_values('family_id').reset_index(drop=True)
    pool['alternative_family_ids'] = pool['_members'].map(alternatives)
    pool = pool.drop(columns='_members')
    eligible_keys = set().union(*(set(keys) for keys in pool.member_keys))
    eligible = catalog.character_key.isin(eligible_keys)
    eligible_catalog = catalog.loc[eligible]
    required = math.ceil(coverage_target * len(eligible_keys))
    stages, selected, removed = [], [], []
    feasible = not eligible_keys
    optimal = not eligible_keys
    infeasible = False
    message = 'No eligible characters under the current family filters.'
    solver_version = None
    if eligible_keys:
        from scipy import __version__ as solver_version
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import csc_matrix, diags, hstack, vstack

        key_index = {key: index for index, key in enumerate(eligible_catalog.character_key)}
        positions = [(key_index[key], column) for column, keys in enumerate(pool.member_keys) for key in keys]
        rows, columns = zip(*positions, strict=True)
        n, m = len(pool), len(eligible_keys)
        incidence = csc_matrix((np.ones(len(rows)), (rows, columns)), shape=(m, n))
        degrees = np.asarray(incidence.sum(axis=1)).ravel()
        matrix = vstack([hstack([incidence, -diags(np.ones(m))]),
                         hstack([incidence, -diags(degrees)]),
                         csc_matrix(np.r_[np.zeros(n), np.ones(m)][None, :])], format='csc')
        lower = np.r_[np.zeros(m), np.full(m, -np.inf), required]
        upper = np.r_[np.full(m, np.inf), np.zeros(m), np.inf]
        extra = m if minimum_exclusive_share > 0 or overlap_penalty > 0 else 0
        if extra:
            # z is exactly one when a character belongs to one selected family.
            # Enforce the minimum on each selected family's actual exclusive count.
            matrix = hstack([matrix, csc_matrix((matrix.shape[0], m))], format='csc')
            identity = diags(np.ones(m))
            exclusive_required = np.ceil(minimum_exclusive_share * pool.included_characters.to_numpy() - 1e-9)
            matrix = vstack([matrix,
                hstack([csc_matrix((m, n)), -identity, identity]),
                hstack([incidence, csc_matrix((m, m)), diags(degrees - 1)]),
                hstack([incidence, -2 * identity, identity]),
                hstack([-diags(exclusive_required), csc_matrix((n, m)), incidence.T])], format='csc')
            lower = np.r_[lower, np.full(2 * m, -np.inf), np.zeros(m + n)]
            upper = np.r_[upper, np.zeros(m), degrees, np.full(m + n, np.inf)]
        integrality = np.ones(n + m + extra)
        objectives = [
            ('Extra memberships', np.r_[pool.included_characters.to_numpy(dtype=float), -np.ones(m), np.zeros(extra)]),
            ('Covered characters', np.r_[np.zeros(n), -np.ones(m), np.zeros(extra)]),
            ('Family count', np.r_[np.ones(n), np.zeros(m + extra)]),
            ('Size and consistency cost', np.r_[pool.selection_cost.to_numpy(dtype=float), np.zeros(m + extra)]),
        ]
        if v2:
            score = np.r_[pool.selection_cost.to_numpy() + overlap_penalty, np.zeros(m + extra)]
            if overlap_penalty:
                # w_ij = selected_family_j * exclusive_character_i, only on actual memberships.
                edges = len(rows)
                family_selector = csc_matrix((np.ones(edges), (np.arange(edges), columns)), shape=(edges, n))
                exclusive_selector = csc_matrix((np.ones(edges), (np.arange(edges), rows)), shape=(edges, m))
                edge_identity = diags(np.ones(edges))
                matrix = hstack([matrix, csc_matrix((matrix.shape[0], edges))], format='csc')
                matrix = vstack([matrix,
                    hstack([-family_selector, csc_matrix((edges, m + extra)), edge_identity]),
                    hstack([csc_matrix((edges, n + m)), -exclusive_selector, edge_identity]),
                    hstack([-family_selector, csc_matrix((edges, m)), -exclusive_selector, edge_identity])], format='csc')
                lower = np.r_[lower, np.full(2 * edges, -np.inf), -np.ones(edges)]
                upper = np.r_[upper, np.zeros(3 * edges)]
                score = np.r_[score, -overlap_penalty / pool.included_characters.to_numpy()[list(columns)]]
                integrality = np.r_[integrality, np.zeros(edges)]
            padding = len(integrality) - n
            objectives = [
                ('Covered characters', np.r_[np.zeros(n), -np.ones(m), np.zeros(padding - m)]),
                ('Adjusted collection cost', score),
                ('Family count', np.r_[np.ones(n), np.zeros(padding)]),
            ]
        incumbent = None
        for name, objective in objectives:
            remaining = time_limit - (time.perf_counter() - started)
            if remaining <= 0:
                message = 'Time budget reached; later objectives were not solved.'
                break
            result = milp(objective, integrality=integrality, bounds=Bounds(0, 1),
                          constraints=LinearConstraint(matrix, lower, upper),
                          options={'time_limit': remaining, 'mip_rel_gap': 0.})
            candidate = _validated_solution(result.x, matrix, lower, upper, integrality)
            if candidate is not None and (incumbent is None or objective @ candidate <= objective @ incumbent + 1e-6):
                incumbent = candidate
            proven = result.status == 0 and candidate is not None
            infeasible = result.status == 2 and incumbent is None and not stages
            stages.append({'objective': name, 'optimal': proven, 'status': int(result.status),
                           'value': float(objective @ incumbent) if incumbent is not None else None,
                           'lower_bound': _finite(getattr(result, 'mip_dual_bound', None)),
                           'gap': _finite(getattr(result, 'mip_gap', None)), 'message': str(result.message)})
            message = str(result.message)
            if not proven:
                break
            optimum = float(objective @ incumbent)
            matrix = vstack([matrix, csc_matrix(objective[None, :])], format='csc')
            tolerance = score_tolerance(optimum) if name == 'Adjusted collection cost' else 0.
            lower = np.r_[lower, optimum - tolerance]
            upper = np.r_[upper, optimum + tolerance]
        feasible = incumbent is not None
        optimal = len(stages) == len(objectives) and all(stage['optimal'] for stage in stages)
        if feasible:
            selected = np.flatnonzero(incumbent[:n]).tolist()
            if v2:
                actual_cost = collection_costs(pool.iloc[selected], overlap_penalty).adjusted_cost.sum()
                if not math.isclose(actual_cost, float(score @ incumbent), abs_tol=1e-5, rel_tol=SCORE_REL_TOL):
                    raise ValueError('Linear score differs from selected collection cost.')
            if not optimal:
                selected, removed = _remove_redundant(pool, selected, overlap_penalty if v2 else None)
    families = collection_costs(pool.iloc[selected], overlap_penalty)
    counts = {}
    for keys in families.member_keys:
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    if feasible and (len(counts) < required or not families.exclusive_share.ge(minimum_exclusive_share - 1e-9).all()):
        raise ValueError('Selected collection violates coverage or exclusivity.')
    catalog['family_count'] = catalog.character_key.map(counts).fillna(0).astype(int)
    catalog['coverage_status'] = [
        'Covered' if key in counts else
        'Family cost ceiling' if key in raw_keys and key not in eligible_keys else
        'No eligible family' if key not in eligible_keys else
        'Not selected under coverage target' if feasible else
        'Coverage and exclusive-share constraints infeasible' if infeasible else 'No feasible solution returned'
        for key in catalog.character_key]
    metrics = coverage_metrics(families.member_keys.tolist())
    return dict(metrics, total=len(catalog), complete=metrics['covered'] == len(catalog),
                eligible_characters=len(eligible_keys), required_characters=required,
                coverage_target=coverage_target, minimum_exclusive_share=minimum_exclusive_share,
                compact_objective=compact_objective, overlap_penalty=overlap_penalty,
                base_cost=float(families.selection_cost.sum()), overlap_cost=float(families.overlap_cost.sum()),
                adjusted_cost=float(families.adjusted_cost.sum()),
                feasible=feasible, optimal=optimal, infeasible=infeasible,
                solver={'name': 'SciPy MILP / HiGHS', 'version': solver_version, 'stages': stages,
                        'message': message, 'time_limit': time_limit,
                        'elapsed_seconds': time.perf_counter() - started,
                        'compact_objective': compact_objective, 'overlap_penalty': overlap_penalty,
                        'objective_count': 3 if v2 else 4,
                        'removed_redundant_family_ids': removed},
                families=families, characters=catalog)


def _validated_solution(values, matrix, lower, upper, integrality=None):
    if values is None:
        return None
    values = np.asarray(values, dtype=float)
    integers = np.ones(matrix.shape[1], dtype=bool) if integrality is None else np.asarray(integrality, dtype=bool)
    if (values.shape != (matrix.shape[1],) or not np.isfinite(values).all()
            or np.max(np.abs(values[integers] - np.rint(values[integers])), initial=0) > 1e-5):
        return None
    rounded = values.copy()
    rounded[integers] = np.rint(rounded[integers])
    if (rounded < -1e-6).any() or (rounded > 1 + 1e-6).any():
        return None
    rounded = np.clip(rounded, 0, 1)
    evaluated = matrix @ rounded
    if ((evaluated < np.asarray(lower) - 1e-6).any() or (evaluated > np.asarray(upper) + 1e-6).any()):
        return None
    return rounded


def _remove_redundant(pool, selected, overlap_penalty=None):
    """Remove one redundant family at a time; overlapping groups can cover each other."""
    selected = selected.copy()
    removed = []
    for index in sorted(selected, key=lambda i: (-pool.loc[i, 'selection_cost'], pool.loc[i, 'family_id'])):
        others = set().union(*(set(pool.loc[i, 'member_keys']) for i in selected if i != index))
        if set(pool.loc[index, 'member_keys']).issubset(others):
            if overlap_penalty is not None:
                before = collection_costs(pool.iloc[selected], overlap_penalty).adjusted_cost.sum()
                after = collection_costs(pool.iloc[[i for i in selected if i != index]], overlap_penalty).adjusted_cost.sum()
                if after > before + score_tolerance(before):
                    continue
            selected.remove(index)
            removed.append(pool.loc[index, 'family_id'])
    return selected, removed


def _finite(value):
    return float(value) if value is not None and np.isfinite(value) else None
