"""Comparable bootstrap evidence and final memberships for saved family scenarios."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from importlib.metadata import version

import numpy as np
import pandas as pd

from app_core.families import (
    FamilySettings, discover_families, family_consistency, refine_memberships,
    split_weakest_members, stability_check, summarize_family_consistency, validate_scenario,
)
from app_core.population import WEIGHT

STATES = ['Primary only', 'Secondary only', 'Both', 'Indecisive']
FAMILY_BANDS = ['Full family meets target', 'Retained members only', 'Below target', 'No peer score']


def scenario_evidence(scenario: dict, base: pd.DataFrame, characters: pd.DataFrame, points: np.ndarray,
                      source_hash: str, repetitions: int, repeat_seed: int) -> dict:
    """Rediscover the original groups; reuse only equivalent saved bootstrap evidence."""
    validate_scenario(scenario, characters, source_hash)
    if not 2 <= repetitions <= 50 or not 0 <= repeat_seed < 2**31:
        raise ValueError('Use 2–50 repeats and a seed from 0 to 2³¹−1.')
    settings = FamilySettings(**scenario['settings'])
    source = scenario['source']
    selected = base.tier.isin(source['tiers']).to_numpy()
    if source['maturity'] != 'All':
        selected &= (base.days_tracked.lt(30) if source['maturity'] == 'Under 30 days' else base.days_tracked.ge(30)).to_numpy()
    if not selected.any():
        raise ValueError('No profiles match the saved audience filters.')
    weights = base.loc[selected, WEIGHT].to_numpy() if settings.population_weighted else np.ones(selected.sum())
    excluded = tuple(source['excluded_keys'])
    discovery = discover_families(points[selected], characters, weights, settings, excluded)
    automatic = discovery['assignments'][['character_key', 'character', 'family']]
    checks = scenario.get('stability_checks') or {}
    legacy = scenario.get('stability') or {}
    if not isinstance(checks, dict) or not isinstance(legacy, dict):
        raise ValueError('Saved stability checks must be objects.')
    saved = checks.get('bootstrap')
    if saved is None and legacy.get('mode') == 'Whole-player bootstrap':
        saved = legacy
    if saved is not None and not isinstance(saved, dict):
        raise ValueError('Saved bootstrap check must be an object.')
    signature = hashlib.sha256(json.dumps([scenario['settings'], source], sort_keys=True).encode()).hexdigest()
    saved_baseline = pd.DataFrame(scenario.get('automatic_assignments', scenario['assignments']))
    same_groups = saved_baseline.set_index('character_key').family.reindex(automatic.character_key).tolist() == automatic.family.tolist()
    same_software = all(scenario.get('software', {}).get(name) == version(name)
                        for name in ['leidenalg', 'igraph', 'numpy', 'pandas'])
    reusable = bool(saved and saved.get('co_membership') and saved.get('mode') == 'Whole-player bootstrap'
                    and saved.get('signature') == signature and saved.get('repetitions') == repetitions
                    and saved.get('repeat_seed', settings.seed) == repeat_seed and same_groups and same_software)
    if reusable:
        # Validate the matrix against the regenerated baseline, including its key order.
        try:
            family_consistency(saved['co_membership'], automatic)
        except (ValueError, KeyError, TypeError):
            reusable = False
    if reusable:
        pairs = saved['co_membership']
    else:
        report = stability_check(points[selected], characters, weights, replace(settings, seed=repeat_seed),
                                 automatic, excluded, repetitions, True, discovery=discovery)
        pairs = report.attrs['co_membership']
    return {'automatic': automatic, 'co_membership': pairs, 'repetitions': repetitions,
            'repeat_seed': repeat_seed, 'profiles': int(selected.sum()),
            'evidence_origin': 'Matching saved bootstrap' if reusable else 'Computed bootstrap'}


def evaluate_scenario(evidence: dict, target: float = .8, trim_fraction: float = .2,
                      single_threshold: float = .8, shared_threshold: float = .4,
                      separation_target: float = .2) -> dict:
    """Re-evaluate thresholds without rerunning the bootstrap."""
    families, characters = summarize_family_consistency(evidence['co_membership'], evidence['automatic'],
                                                        target, trim_fraction, separation_target)
    _, rates = family_consistency(evidence['co_membership'], evidence['automatic'])
    final = refine_memberships(characters, single_threshold, shared_threshold)
    full = families.mean_consistency.ge(target)
    retained = ~full & families.retained_consistency.ge(target)
    missing = families.mean_consistency.isna()
    families['consistency_band'] = np.select([missing, full, retained],
                                            ['No peer score', 'Full family meets target', 'Retained members only'],
                                            default='Below target')
    summary = {'families': len(families), 'characters': len(final),
               'character_coverage': float(evidence['automatic'].family.ne('Unassigned').mean()),
               **{state: int(final.state.eq(state).sum()) for state in STATES},
               **{band: int(families.consistency_band.eq(band).sum()) for band in FAMILY_BANDS}}
    return {'summary': summary, 'families': families, 'characters': characters, 'final': final, 'rates': rates,
            'rules': {'family_target': target, 'trim_fraction': trim_fraction, 'single_threshold': single_threshold,
                      'shared_threshold': shared_threshold, 'separation_target': separation_target}}


def aggregate_coverage(cases: list[dict], universe: pd.DataFrame, maximum_family_size: int = 0,
                       minimum_family_size: int = 1) -> dict:
    """Union qualifying original groups by character identity across successful cases."""
    if minimum_family_size < 1 or maximum_family_size < 0 or not universe.character_key.is_unique:
        raise ValueError('Use a positive minimum size, a nonnegative maximum size and a unique character catalog.')
    keys = set(universe.character_key)
    links, family_rows = [], []
    for case in cases:
        result = case['result']
        if set(result['characters'].character_key) != keys:
            raise ValueError('Coverage cases must use the same complete character catalog.')
        for family in result['families'].itertuples():
            if family.consistency_band not in FAMILY_BANDS[:2]:
                continue
            members = result['characters'].loc[result['characters'].family.eq(family.family)]
            retained_only = family.consistency_band == FAMILY_BANDS[1]
            if retained_only:
                members, _ = split_weakest_members(members, result['rules']['trim_fraction'])
            if len(members) < minimum_family_size or (maximum_family_size and len(members) > maximum_family_size):
                continue
            basis = 'Retained members only' if retained_only else 'Full family'
            score = family.retained_consistency if retained_only else family.mean_consistency
            case_id = case.get('id', case['name'])
            family_rows.append({'family_id': f'{case_id}:{family.family}:{basis}',
                                'scenario_id': case_id, 'scenario': case['name'], 'family': family.family, 'basis': basis,
                                'included_characters': len(members), 'qualifying_consistency': score,
                                'member_keys': members.character_key.tolist(), 'member_names': ', '.join(members.character),
                                'median_separation': family.median_separation})
            for member in members.itertuples():
                links.append({'scenario_id': case_id, 'scenario': case['name'], 'family': family.family, 'basis': basis,
                              'character_key': member.character_key, 'character': member.character,
                              'qualifying_consistency': score, 'original_member_consistency': member.own_consistency,
                              'family_target': result['rules']['family_target'],
                              'trim_fraction': result['rules']['trim_fraction']})
    memberships = pd.DataFrame(links, columns=['scenario_id', 'scenario', 'family', 'basis', 'character_key', 'character',
                                              'qualifying_consistency', 'original_member_consistency',
                                              'family_target', 'trim_fraction'])
    candidates = pd.DataFrame(family_rows, columns=['family_id', 'scenario_id', 'scenario', 'family', 'basis',
                                                   'included_characters', 'qualifying_consistency', 'member_keys',
                                                   'member_names', 'median_separation'])
    full_keys = set(memberships.loc[memberships.basis.eq('Full family'), 'character_key'])
    combined_keys = set(memberships.character_key)
    coverage = universe[['character_key', 'character']].copy()
    coverage['covered_full'] = coverage.character_key.isin(full_keys)
    coverage['covered_full_or_retained'] = coverage.character_key.isin(combined_keys)
    coverage['coverage_status'] = np.select([coverage.covered_full, coverage.covered_full_or_retained],
                                           ['Full family', 'Retained only'], default='Uncovered')
    evidence = {key: group for key, group in memberships.groupby('character_key')}
    sources = []
    for key in coverage.character_key:
        group = evidence.get(key, memberships.iloc[:0])
        full = group.loc[group.basis.eq('Full family')]
        retained = group.loc[group.basis.eq('Retained members only')]
        sources.append({'full_family_matches': len(full), 'retained_family_matches': len(retained),
                        'full_sources': ' | '.join(f'{r.scenario} · {r.family}' for r in full.itertuples()),
                        'retained_sources': ' | '.join(f'{r.scenario} · {r.family}' for r in retained.itertuples())})
    coverage = pd.concat([coverage.reset_index(drop=True), pd.DataFrame(sources)], axis=1).sort_values('character')
    contributions = []
    for case in cases:
        group = memberships.loc[memberships.scenario_id.eq(case.get('id', case['name']))]
        contributions.append({'scenario': case['name'],
                              'full_characters': group.loc[group.basis.eq('Full family'), 'character_key'].nunique(),
                              'full_or_retained_characters': group.character_key.nunique()})
    return {'total_characters': len(coverage), 'full_characters': len(full_keys),
            'combined_characters': len(combined_keys), 'retained_adds': len(combined_keys - full_keys),
            'uncovered_characters': len(keys - combined_keys), 'coverage': coverage,
            'memberships': memberships, 'families': candidates, 'contributions': pd.DataFrame(contributions)}


def smallest_family_cover(candidates: pd.DataFrame, universe: pd.DataFrame, include_retained: bool = True) -> dict:
    """Find the exact smallest viable size for each character, then a compact supporting cover.

    The maximum of these minima is the smallest feasible family-size cap. The
    covering subset is greedy: it preserves a smallest-family option for every
    coverable character but does not minimize the number of chosen families.
    """
    pool = (candidates if include_retained else candidates.loc[candidates.basis.eq('Full family')]).drop_duplicates('family_id')
    catalog = universe[['character_key', 'character']].copy().reset_index(drop=True)
    minimum = {}
    memberships = {}
    for family in pool.itertuples():
        keys = set(family.member_keys)
        memberships[family.family_id] = keys
        for key in keys:
            minimum[key] = min(minimum.get(key, len(keys)), len(keys))
    catalog['smallest_family_size'] = catalog.character_key.map(minimum)
    preferred = {row.family_id: {key for key in memberships[row.family_id] if minimum[key] == len(memberships[row.family_id])}
                 for row in pool.itertuples()}
    lookup = pool.set_index('family_id', drop=False)
    remaining, selected = set(minimum), []
    while remaining:
        useful = [family_id for family_id, keys in preferred.items() if keys & remaining]
        chosen = min(useful, key=lambda family_id: (lookup.loc[family_id, 'included_characters'],
                                                    -len(preferred[family_id] & remaining),
                                                    -lookup.loc[family_id, 'qualifying_consistency'], family_id))
        selected.append(chosen)
        remaining -= preferred[chosen]
    # Remove redundant choices while preserving each character's finest available option.
    for family_id in selected.copy()[::-1]:
        other = set().union(*(preferred[other_id] for other_id in selected if other_id != family_id))
        if preferred[family_id].issubset(other):
            selected.remove(family_id)
    recommendations = lookup.loc[selected].reset_index(drop=True) if selected else pool.iloc[:0].copy()
    chosen_for = {}
    for key in minimum:
        options = [family_id for family_id in selected if key in preferred[family_id]]
        chosen_for[key] = min(options, key=lambda family_id: (-lookup.loc[family_id, 'qualifying_consistency'], family_id))
    catalog['suggested_family_id'] = catalog.character_key.map(chosen_for)
    catalog['suggested_scenario'] = catalog.suggested_family_id.map(lookup.scenario)
    catalog['suggested_family'] = catalog.suggested_family_id.map(lookup.family)
    return {'covered': len(minimum), 'total': len(catalog), 'complete': len(minimum) == len(catalog),
            'minimum_size_cap': max(minimum.values()) if minimum else None,
            'families': recommendations, 'characters': catalog.sort_values(['smallest_family_size', 'character'], na_position='last')}


def target_size_cover(candidates: pd.DataFrame, universe: pd.DataFrame, include_retained: bool = True,
                      ideal_minimum: int = 10, ideal_maximum: int = 15, size_preference: float = .5,
                      max_family_cost: float | None = None, max_cost_per_character: float | None = None,
                      overlap_penalty: float = 0.) -> dict:
    """Greedy size-aware cover with optional cost exclusions and partial coverage.

    Size distance is log2 of the ratio to the nearest ideal boundary, zero in
    range. Refinement trades family count/consistency against each character's
    best selected distance. With a marginal limit it preserves the greedy covered
    set, blocks zero-gain additions and checks replacement cost against restored
    coverage. This is a deterministic heuristic, not an exact optimizer.
    Overlap increases greedy cost by penalty times the already-covered fraction.
    Refinement charges each family's quality cost for its shared-member fraction.
    """
    if not np.isfinite(overlap_penalty) or overlap_penalty < 0:
        raise ValueError('Overlap penalty must be a nonnegative finite number.')
    if ideal_minimum < 1 or ideal_maximum < ideal_minimum or not 0 <= size_preference <= 1:
        raise ValueError('Use a positive ordered ideal size range and a preference between 0 and 1.')
    if any(limit is not None and (not np.isfinite(limit) or limit <= 0)
           for limit in (max_family_cost, max_cost_per_character)):
        raise ValueError('Cost limits must be positive finite numbers or None.')
    available = (candidates if include_retained else candidates.loc[candidates.basis.eq('Full family')])
    available = available.drop_duplicates('family_id').sort_values('family_id').reset_index(drop=True).copy()
    catalog = universe[['character_key', 'character']].copy().reset_index(drop=True)
    all_membership = np.array([catalog.character_key.isin(keys).to_numpy() for keys in available.member_keys], dtype=bool).reshape(len(available), len(catalog))
    sizes = available.included_characters.to_numpy(dtype=float)
    available['target_distance'] = np.maximum(np.maximum(ideal_minimum - sizes, sizes - ideal_maximum), 0)
    available['proportional_distance'] = np.maximum(np.maximum(np.log2(ideal_minimum / sizes), np.log2(sizes / ideal_maximum)), 0)
    weight = 10 * size_preference
    available['selection_cost'] = 2 - available.qualifying_consistency.to_numpy(dtype=float) + weight * available.proportional_distance
    eligible = (available.selection_cost.le(max_family_cost + 1e-12).to_numpy()
                if max_family_cost is not None else np.ones(len(available), dtype=bool))
    pool = available.loc[eligible].reset_index(drop=True)
    membership = all_membership[eligible]
    coverable = membership.any(axis=0)
    quality_cost = 2 - pool.qualifying_consistency.to_numpy(dtype=float)
    greedy_cost = pool.selection_cost.to_numpy(dtype=float)
    pool_sizes = pool.included_characters.to_numpy(dtype=float)
    remaining, selected = coverable.copy(), []
    while remaining.any():
        covered_so_far = coverable & ~remaining
        gain = membership[:, remaining].sum(axis=1)
        repeated_fraction = membership[:, covered_so_far].sum(axis=1) / pool_sizes if overlap_penalty else 0.
        adjusted_cost = greedy_cost * (1 + overlap_penalty * repeated_fraction)
        chosen = int(np.argmax(gain / adjusted_cost))
        if max_cost_per_character is not None and adjusted_cost[chosen] / gain[chosen] > max_cost_per_character + 1e-12:
            break
        selected.append(chosen)
        remaining &= ~membership[chosen]
    covered = coverable & ~remaining
    pair_distances = np.where(membership[:, covered], pool.proportional_distance.to_numpy()[:, None], np.inf)

    def overlap_cost(indices):
        if not overlap_penalty or not indices:
            return 0.
        groups = membership[indices]
        repeated = groups.sum(axis=0) > 1
        fractions = groups[:, repeated].sum(axis=1) / pool_sizes[indices]
        return overlap_penalty * float(np.dot(quality_cost[indices], fractions))

    def added_overlap_costs(others, additions):
        if not overlap_penalty:
            return np.zeros(len(additions))
        existing = membership[others].sum(axis=0)
        groups = membership[additions]
        repeated = existing + groups > 1
        existing_weights = (quality_cost[others] / pool_sizes[others]) @ membership[others]
        return overlap_penalty * (repeated @ existing_weights
            + (groups & repeated).sum(axis=1) * quality_cost[additions] / pool_sizes[additions])

    def objective(best_distances, family_cost):
        valid = np.isfinite(best_distances).all(axis=-1)
        fit = np.where(np.isfinite(best_distances), best_distances, 0).sum(axis=-1)
        return np.where(valid, family_cost + weight * fit, np.inf)

    # A marginal stop fixes the covered set; refinement cannot sneak in extra
    # coverage or zero-gain families after the budget has stopped selection.
    while selected:
        selected.sort()
        best_distances = pair_distances[selected].min(axis=0)
        cost = quality_cost[selected].sum()
        best_score = float(objective(best_distances, cost + overlap_cost(selected)))
        best_selection = selected
        unused = np.array([i for i in range(len(pool)) if i not in selected], dtype=int)
        if len(unused) and max_cost_per_character is None:
            scores = objective(np.minimum(best_distances, pair_distances[unused]), cost + quality_cost[unused]) + added_overlap_costs(selected, unused)
            add = int(np.argmin(scores))
            if scores[add] < best_score - 1e-9:
                best_score, best_selection = float(scores[add]), selected + [int(unused[add])]
        for removed in selected:
            others = [i for i in selected if i != removed]
            without = pair_distances[others].min(axis=0) if others else np.full(covered.sum(), np.inf)
            reduced_cost = cost - quality_cost[removed]
            score = float(objective(without, reduced_cost + overlap_cost(others)))
            if score < best_score - 1e-9:
                best_score, best_selection = score, others
            if len(unused):
                scores = objective(np.minimum(without, pair_distances[unused]), reduced_cost + quality_cost[unused]) + added_overlap_costs(others, unused)
                if max_cost_per_character is not None:
                    other_coverage = membership[others].any(axis=0)
                    gain = membership[unused][:, ~other_coverage].sum(axis=1)
                    repeated_fraction = membership[unused][:, other_coverage].sum(axis=1) / pool_sizes[unused]
                    adjusted = greedy_cost[unused] * (1 + overlap_penalty * repeated_fraction)
                    allowed = ((gain > 0) & (adjusted <= max_cost_per_character * gain + 1e-12)
                               & ~membership[unused][:, ~covered].any(axis=1))
                    scores = np.where(allowed, scores, np.inf)
                swap = int(np.argmin(scores))
                if scores[swap] < best_score - 1e-9:
                    best_score, best_selection = float(scores[swap]), others + [int(unused[swap])]
        if best_selection is selected:
            break
        selected = best_selection

    chosen_for = {}
    for index in np.flatnonzero(covered):
        options = [i for i in selected if membership[i, index]]
        chosen = min(options, key=lambda i: (pool.loc[i, 'proportional_distance'], quality_cost[i], pool.loc[i, 'family_id']))
        chosen_for[catalog.loc[index, 'character_key']] = pool.loc[chosen, 'family_id']
    lookup = pool.set_index('family_id')
    catalog['suggested_family_id'] = catalog.character_key.map(chosen_for)
    catalog['suggested_family_size'] = catalog.suggested_family_id.map(lookup.included_characters)
    catalog['target_distance'] = catalog.suggested_family_id.map(lookup.target_distance)
    catalog['proportional_distance'] = catalog.suggested_family_id.map(lookup.proportional_distance)
    catalog['in_ideal_range'] = catalog.target_distance.eq(0)
    catalog['ideal_option_available'] = membership[pool.target_distance.eq(0)].any(axis=0)
    catalog['suggested_scenario'] = catalog.suggested_family_id.map(lookup.scenario)
    catalog['suggested_family'] = catalog.suggested_family_id.map(lookup.family)
    catalog['coverage_status'] = np.select([covered, ~coverable], ['Covered', 'No eligible family'], default='Marginal cost limit')
    before_cost_filter = all_membership.any(axis=0)
    catalog['coverage_reason'] = np.select(
        [covered, ~before_cost_filter, ~coverable],
        ['Selected family', 'No viable family in current scope', 'Family cost ceiling'], default='Cost per additional character limit')
    gain = all_membership[:, ~covered].sum(axis=1)
    available['new_characters'] = gain
    available['overlap_adjusted_cost'] = available.selection_cost * (1 + overlap_penalty * all_membership[:, covered].sum(axis=1) / sizes)
    available['cost_per_new_character'] = np.divide(available.overlap_adjusted_cost.to_numpy(dtype=float), gain,
                                                   out=np.full(len(available), np.inf), where=gain > 0)
    available['blocked_by'] = np.where(~eligible, 'Family cost ceiling', 'Cost per additional character limit')
    remaining_options = available.loc[gain > 0].sort_values(['cost_per_new_character', 'selection_cost', 'family_id'])
    cheapest = {}
    for family in remaining_options.itertuples():
        for key in family.member_keys:
            cheapest.setdefault(key, family)
    for column, attribute in [('cheapest_remaining_family_id', 'family_id'), ('cheapest_remaining_family', 'family'),
                               ('cheapest_remaining_scenario', 'scenario'), ('cheapest_remaining_cost_per_character', 'cost_per_new_character'),
                               ('cheapest_remaining_blocked_by', 'blocked_by')]:
        catalog[column] = [getattr(cheapest[key], attribute) if key in cheapest and not is_covered else None
                           for key, is_covered in zip(catalog.character_key, covered, strict=True)]
    return {'covered': int(covered.sum()), 'total': len(catalog), 'complete': bool(covered.all()),
            'no_eligible_characters': int((~coverable).sum()), 'cost_limited_characters': int((coverable & ~covered).sum()),
            'family_cost_excluded_characters': int((before_cost_filter & ~coverable).sum()),
            'ideal_characters': int(catalog.in_ideal_range.sum()),
            'outside_ideal_characters': int(covered.sum() - catalog.in_ideal_range.sum()),
            'families': pool.iloc[selected].copy(),
            'remaining_options': remaining_options,
            'characters': catalog.sort_values(['target_distance', 'character'], ascending=[False, True], na_position='last')}
