"""Curated overlapping family collections, using frozen source bootstrap evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version

import numpy as np
import pandas as pd

from app_core.families import family_consistency, split_weakest_members
from app_core.family_batch import evaluate_scenario, smallest_family_cover, target_size_cover
from app_core.family_cover import LEGACY_OBJECTIVE, SCORE_OBJECTIVE, base_family_cost, collection_costs


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def candidate_id(source_id: str, family: str, basis: str, members: list) -> str:
    return fingerprint([source_id, family, basis, sorted(members)])[:24]


def sources_from_cases(cases: list[dict]) -> dict:
    sources = {}
    for case in cases:
        source_id = fingerprint(case['scenario'])
        evidence = case['evidence']
        sources[source_id] = {
            'name': case['name'], 'scenario': case['scenario'],
            'automatic': evidence['automatic'].to_dict('records'),
            'co_membership': evidence['co_membership'],
            'repetitions': evidence['repetitions'], 'repeat_seed': evidence['repeat_seed'],
            'profiles': evidence['profiles'],
            'evidence_software': {name: version(name) for name in ['leidenalg', 'igraph', 'numpy', 'pandas']},
        }
    return sources


def candidate_library(sources: dict, rules: dict) -> list[dict]:
    """Include original groups for review, plus qualifying retained-only subsets."""
    candidates = []
    for source_id, source in sources.items():
        if 'candidate_families' in source:
            candidates.extend(_hunter_candidates(source_id, source, rules))
            continue
        evidence = dict(source, automatic=pd.DataFrame(source['automatic']))
        result = evaluate_scenario(evidence, **{
            'target': rules['family_target'], 'trim_fraction': rules['trim_fraction'],
            'single_threshold': rules['single_threshold'], 'shared_threshold': rules['shared_threshold'],
            'separation_target': rules['separation_target'],
        })
        for family in result['families'].itertuples():
            members = result['characters'].loc[result['characters'].family.eq(family.family)]
            kept, removed = split_weakest_members(members, rules['trim_fraction'])
            label = source['scenario'].get('families', {}).get(family.family, {}).get('title', family.family)
            for basis, group in [('Full family', members), ('Retained members only', kept)]:
                if basis != 'Full family' and not (
                    family.mean_consistency < rules['family_target'] <= family.retained_consistency
                ):
                    continue
                keys = sorted(group.character_key.tolist())
                candidates.append({
                    'id': candidate_id(source_id, family.family, basis, keys),
                    'source_id': source_id, 'family': family.family, 'basis': basis,
                    'member_keys': keys, 'title': f'{label} · {basis}',
                    'removed_keys': removed.character_key.tolist(),
                    'retained_consistency': finite_or_none(family.retained_consistency),
                    'original_separation': finite_or_none(family.median_separation),
                    'exception_note': '', 'added_as_exception': False,
                })
    return candidates


def _hunter_candidates(source_id: str, source: dict, rules: dict) -> list[dict]:
    candidates = []
    for family in source['candidate_families']:
        keys = family['member_keys']
        fits, mean = subset_scores(source, keys)
        ranked = fits.rename(columns={'member_fit': 'own_consistency'})
        kept, removed = split_weakest_members(ranked, rules['trim_fraction'])
        retained_keys = sorted(kept.character_key.tolist())
        _, retained_mean = subset_scores(source, retained_keys)
        for basis, members in [('Full family', keys), ('Retained members only', retained_keys)]:
            if basis != 'Full family' and not mean < rules['family_target'] <= retained_mean:
                continue
            candidates.append({
                'id': candidate_id(source_id, family['family'], basis, members),
                'source_id': source_id, 'family': family['family'], 'basis': basis,
                'member_keys': sorted(members), 'title': f'{family["title"]} · {basis}',
                'removed_keys': removed.character_key.tolist(), 'retained_consistency': finite_or_none(retained_mean),
                'original_separation': None, 'exception_note': '', 'added_as_exception': False,
                **{field: family[field] for field in ['anchors', 'origins']},
                **({field: family[field] for field in ['ensemble_frequency', 'ensemble_agreement',
                      'mean_recovery', 'p10_recovery', 'exact_recovery', 'median_recovery', 'anchor_fit', 'boundary_retention']
                      if field in family} if basis == 'Full family' else {}),
            })
    return candidates


def original_family_keys(source: dict, family: str) -> set:
    if 'candidate_families' in source:
        return set(next((row['member_keys'] for row in source['candidate_families'] if row['family'] == family), []))
    return {row['character_key'] for row in source['automatic'] if row['family'] == family}


def finite_or_none(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def source_matrix(source: dict, keys: list) -> np.ndarray:
    """Align compact anchored evidence; never-evaluated characters remain unavailable."""
    matrix_keys = source['co_membership']['character_keys']
    positions = {key: i for i, key in enumerate(matrix_keys)}
    if source.get('method') != 'anchored_leiden' and not set(keys).issubset(positions):
        raise ValueError('Included members must be present in the source evidence.')
    values = np.asarray(source['co_membership']['rates'], dtype=float)
    result = np.full((len(keys), len(keys)), np.nan)
    known = [(i, positions[key]) for i, key in enumerate(keys) if key in positions]
    if known:
        destination, origin = zip(*known)
        result[np.ix_(destination, destination)] = values[np.ix_(origin, origin)]
    return result


def subset_scores(source: dict, keys: list, target: float = .8) -> tuple[pd.DataFrame, float]:
    """Score included members by key, excluding self even with nonunit diagonals."""
    names = {row['character_key']: row['character'] for row in source['automatic']}
    if not keys or len(set(keys)) != len(keys) or not set(keys).issubset(names):
        raise ValueError('Included members must be nonempty, unique and present in the source evidence.')
    rates = source_matrix(source, keys)
    np.fill_diagonal(rates, np.nan)
    count = np.isfinite(rates).sum(axis=1)
    available = np.divide(np.nansum(rates, axis=1), count, out=np.full(len(keys), np.nan), where=count > 0)
    if len(keys) == 1:
        fits = support = weakest = np.array([np.nan])
        mean = np.nan
    else:
        fits = np.where(count == len(keys) - 1, available, np.nan)
        support = np.sum(rates >= target, axis=1) / (len(keys) - 1)
        support = np.where(count == len(keys) - 1, support, np.nan)
        weakest = np.where(count == len(keys) - 1, np.min(np.where(np.isnan(rates), np.inf, rates), axis=1), np.nan)
        mean = float(fits.mean())
    return pd.DataFrame({'character_key': keys, 'character': [names[key] for key in keys],
                         'member_fit': fits, 'peer_support': support, 'weakest_pair': weakest,
                         'available_member_fit': available, 'scored_peers': count}), mean


def policy_metrics(candidate: dict, mean: float, covered: set, policy: dict) -> dict:
    """Explain every current exclusion; marginal cost is relative to this draft."""
    size = len(candidate['member_keys'])
    low, high = policy.get('ideal_minimum', 10), policy.get('ideal_maximum', 15)
    distance = max(0., np.log2(low / size), np.log2(size / high))
    cost = float(base_family_cost(size, mean, low, high, policy.get('size_preference', .5))) if pd.notna(mean) else np.nan
    new = len(set(candidate['member_keys']) - covered)
    marginal = cost / new if new else np.nan
    reasons = []
    if pd.isna(mean):
        reasons.append('Incomplete or unavailable pair evidence')
    elif mean < policy.get('family_target', .8):
        reasons.append('Below family-consistency target')
    if policy.get('cover_basis') in {'Full families only', 'Full only'} and candidate['basis'] != 'Full family':
        reasons.append('Excluded by full-only basis')
    if size < policy.get('minimum_family_size', 1):
        reasons.append('Below minimum size')
    if policy.get('maximum_family_size', 0) and size > policy['maximum_family_size']:
        reasons.append('Above maximum size')
    if policy.get('selection_approach') in {'Target-size cover', 'Compact audience cover'}:
        if policy.get('max_family_cost') is not None and cost > policy['max_family_cost'] + 1e-12:
            reasons.append('Above family-cost ceiling')
        if (policy.get('selection_approach') == 'Target-size cover' and policy.get('max_cost_per_character') is not None
                and new and marginal > policy['max_cost_per_character'] + 1e-12):
            reasons.append('Above current marginal-cost limit')
    return {'size': size, 'family_mean': mean, 'proportional_distance': distance,
            'in_ideal_range': low <= size <= high, 'selection_cost': cost,
            'new_characters': new, 'already_covered': size - new,
            'cost_per_new_character': marginal, 'policy_flags': ' | '.join(reasons),
            'eligible': not reasons}


def validate_policy(policy: dict) -> None:
    if policy.get('compact_objective', LEGACY_OBJECTIVE) not in {LEGACY_OBJECTIVE, SCORE_OBJECTIVE}:
        raise ValueError('Invalid Compact objective version.')
    penalty = policy.get('overlap_penalty', 0.)
    if isinstance(penalty, bool) or not isinstance(penalty, (int, float)) or not np.isfinite(penalty) or penalty < 0:
        raise ValueError('Invalid overlap penalty.')
    low, high = policy.get('ideal_minimum', 10), policy.get('ideal_maximum', 15)
    if (not all(isinstance(value, int) and not isinstance(value, bool)
                for value in [low, high, policy.get('minimum_family_size', 1), policy.get('maximum_family_size', 0)])
            or not 1 <= low <= high or not 0 <= policy.get('size_preference', .5) <= 1
            or policy.get('minimum_family_size', 1) < 1 or policy.get('maximum_family_size', 0) < 0):
        raise ValueError('Invalid cohort size preferences or coverage limits.')
    if (not 0 <= policy['family_target'] <= 1 or not 0 <= policy['trim_fraction'] <= .4
            or not 0 <= policy['shared_threshold'] <= policy['single_threshold'] <= 1
            or not 0 <= policy['separation_target'] <= 1):
        raise ValueError('Invalid cohort review thresholds.')
    for field in ['max_family_cost', 'max_cost_per_character']:
        limit = policy.get(field)
        if limit is not None and (not np.isfinite(limit) or limit <= 0):
            raise ValueError('Cohort cost limits must be positive finite numbers or null.')
    if policy.get('cover_basis', 'Full + retained') not in {'Full + retained', 'Full families only', 'Full only'}:
        raise ValueError('Invalid cohort family basis.')


def score_candidates(candidates: list[dict], sources: dict, covered: set, policy: dict,
                     target: float = .8, character_key=None) -> pd.DataFrame:
    rows = []
    for candidate in candidates:
        if character_key is not None and character_key not in candidate['member_keys']:
            continue
        source = sources[candidate['source_id']]
        fits, mean = subset_scores(source, candidate['member_keys'], target)
        row = dict(candidate, scenario=source['name'], profiles=source['profiles'],
                   method=source.get('method', 'full_leiden' if 'candidate_families' in source else 'scenario'),
                   source_anchor=next((row['character'] for row in source['automatic'] if row['character_key'] == source.get('anchor')), None),
                   candidate_neighbors=source.get('candidate_neighbors'),
                   repetitions=source['repetitions'], repeat_seed=source['repeat_seed'],
                   rank_tiers='/'.join(source['scenario']['source']['tiers']),
                   tracking_history=source['scenario']['source']['maturity'],
                   **policy_metrics(candidate, mean, covered, policy))
        if character_key is not None:
            row.update(fits.loc[fits.character_key.eq(character_key)].iloc[0].to_dict())
        rows.append(row)
    return pd.DataFrame(rows)


def new_draft(sources: dict, universe: pd.DataFrame, policy: dict, membership_hash: str,
              reference_hash: str, selected: list[dict] | None = None) -> dict:
    return {'schema_version': 1, 'name': 'Family cohort', 'notes': '',
            'membership_sha256': membership_hash, 'reference_sha256': reference_hash,
            'catalog': universe[['character_key', 'character']].to_dict('records'),
            'sources': copy.deepcopy(sources), 'selected': copy.deepcopy(selected or []),
            'origin_policy': copy.deepcopy(policy), 'policy': copy.deepcopy(policy),
            'character_notes': {}, 'member_target': .8}


def edit_draft(draft: dict, candidate: dict | None = None, remove_id: str | None = None) -> dict:
    """Atomic whole-family add/remove/swap. Inputs and source records stay unchanged."""
    result = copy.deepcopy(draft)
    selected = result['selected']
    if remove_id is not None:
        if not any(row['id'] == remove_id for row in selected):
            raise ValueError('The family to remove is no longer selected.')
        selected[:] = [row for row in selected if row['id'] != remove_id]
    if candidate is not None:
        if any(row['id'] == candidate['id'] or (
            row['source_id'] == candidate['source_id'] and set(row['member_keys']) == set(candidate['member_keys'])
        ) for row in selected):
            raise ValueError('This source/member-set family is already selected.')
        selected.append(copy.deepcopy(candidate))
    return result


def edit_members(draft: dict, family_id: str, keys: list, reason: str) -> dict:
    """Create an analyst variant inside the cohort, preserving original library evidence."""
    if not reason.strip():
        raise ValueError('Record a reason for the manual membership decision.')
    original = next(row for row in draft['selected'] if row['id'] == family_id)
    if len(keys) < 2:
        raise ValueError('Keep at least two characters in a family.')
    if set(keys) == set(original['member_keys']):
        raise ValueError('Membership has not changed.')
    source = draft['sources'][original['source_id']]
    subset_scores(source, keys)
    changed = copy.deepcopy(original)
    changed.setdefault('base_member_keys', original['member_keys'].copy())
    changed.setdefault('base_basis', original['basis'])
    changed.update(member_keys=sorted(keys), basis='Manual variant', added_as_exception=True,
                   manual_reason=reason.strip(), exception_note=reason.strip())
    for field in ['mean_recovery', 'p10_recovery', 'exact_recovery', 'ensemble_agreement', 'ensemble_frequency',
                  'retained_consistency', 'original_separation', 'median_recovery', 'anchor_fit', 'boundary_retention']:
        changed.pop(field, None)
    changed['id'] = candidate_id(changed['source_id'], changed['family'], changed['basis'], keys)
    return edit_draft(draft, changed, family_id)


def merge_sources(draft: dict, sources: dict) -> dict:
    result = copy.deepcopy(draft)
    for key, source in sources.items():
        if key in result['sources'] and fingerprint(source) != fingerprint(result['sources'][key]):
            raise ValueError('A source identity already exists with different evidence. Existing evidence was preserved.')
        result['sources'][key] = copy.deepcopy(source)
    return result


def prepare_library_candidates(draft: dict, policy: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Score evidence once; changing the cover objective can reuse these rows."""
    candidates = candidate_library(draft['sources'], policy)
    rows = score_candidates(candidates, draft['sources'], set(), policy)
    if not rows.empty:
        rows = rows.loc[rows.family_mean.ge(policy['family_target'])]
        rows = rows.loc[rows['size'].ge(policy.get('minimum_family_size', 1))]
        if policy.get('maximum_family_size', 0):
            rows = rows.loc[rows['size'].le(policy['maximum_family_size'])]
    rows = rows.rename(columns={'id': 'family_id', 'source_id': 'scenario_id', 'size': 'included_characters',
                                'family_mean': 'qualifying_consistency'})
    if rows.empty:
        rows = pd.DataFrame(columns=['family_id', 'scenario_id', 'scenario', 'family', 'basis',
                                      'included_characters', 'qualifying_consistency', 'member_keys'])
    return rows, candidates


def suggest_from_library(draft: dict, policy: dict,
                         prepared: tuple[pd.DataFrame, list[dict]] | None = None) -> tuple[dict, list[dict]]:
    """Reuse cover methods for scenario and hunter candidates alike."""
    rows, candidates = prepare_library_candidates(draft, policy) if prepared is None else prepared
    universe = pd.DataFrame(draft['catalog'])
    retained = policy.get('cover_basis', 'Full + retained') == 'Full + retained'
    if policy.get('selection_approach') == 'Smallest available':
        cover = smallest_family_cover(rows, universe, retained)
    elif policy.get('selection_approach') == 'Compact audience cover':
        from app_core.family_cover import compact_audience_cover
        cover = compact_audience_cover(rows, universe, retained, policy.get('ideal_minimum', 10), policy.get('ideal_maximum', 15),
                                       policy.get('size_preference', .5), policy.get('max_family_cost'),
                                       policy.get('coverage_target', 1.), policy.get('solve_time_limit', 30.),
                                       policy.get('minimum_exclusive_share', 0.),
                                       policy.get('compact_objective', LEGACY_OBJECTIVE), policy.get('overlap_penalty', 0.))
    else:
        cover = target_size_cover(rows, universe, retained, policy.get('ideal_minimum', 10), policy.get('ideal_maximum', 15),
                                  policy.get('size_preference', .5), policy.get('max_family_cost'), policy.get('max_cost_per_character'),
                                  policy.get('overlap_penalty', 0.))
    ids = set(cover['families'].family_id) if not cover['families'].empty else set()
    return cover, [row for row in candidates if row['id'] in ids]


def summarize_cohort(draft: dict, policy: dict | None = None, target: float | None = None) -> dict:
    policy = draft['policy'] if policy is None else policy
    target = draft['member_target'] if target is None else target
    selected, sources = draft['selected'], draft['sources']
    counts = {}
    for family in selected:
        for key in family['member_keys']:
            counts[key] = counts.get(key, 0) + 1
    covered = set(counts)
    family_rows, links = [], []
    for family in selected:
        fits, mean = subset_scores(sources[family['source_id']], family['member_keys'], target)
        metrics = policy_metrics(family, mean, covered - set(family['member_keys']), policy)
        # Family-level exclusions remain meaningful; marginal cost is displayed in action previews instead.
        metrics['policy_flags'] = ' | '.join(x for x in metrics['policy_flags'].split(' | ')
                                            if x and x != 'Above current marginal-cost limit')
        family_rows.append(dict(family, scenario=sources[family['source_id']]['name'], **metrics,
                                weakest_member=fits.member_fit.min(),
                                weak_members=int(fits.member_fit.lt(target).sum()),
                                unscored_members=int(fits.member_fit.isna().sum()),
                                exclusive_characters=sum(counts[key] == 1 for key in family['member_keys']),
                                exclusive_share=sum(counts[key] == 1 for key in family['member_keys']) / len(family['member_keys']),
                                repeated_characters=sum(counts[key] > 1 for key in family['member_keys'])))
        manual = set(family['member_keys']) - set(family.get('base_member_keys', family['member_keys']))
        links.extend(fits.assign(family_id=family['id'], title=family['title'],
                                 source_id=family['source_id'], family_mean=mean,
                                 manual_assignment=fits.character_key.isin(manual),
                                 manual_variant=family['basis'] == 'Manual variant',
                                 manual_reason=family.get('manual_reason', '')).to_dict('records'))
    memberships = pd.DataFrame(links, columns=['character_key', 'character', 'member_fit', 'peer_support',
                                               'weakest_pair', 'family_id', 'title', 'source_id', 'family_mean',
                                               'manual_assignment', 'manual_variant', 'manual_reason',
                                               'available_member_fit', 'scored_peers'])
    rows = []
    for member in draft['catalog']:
        key = member['character_key']
        group = memberships.loc[memberships.character_key.eq(key)]
        rows.append(dict(member, family_count=counts.get(key, 0), best_fit=group.member_fit.max(),
                         worst_fit=group.member_fit.min(),
                         families=' | '.join(group.title),
                         fits=' | '.join(f'{r.title}: {r.member_fit:.0%}' if pd.notna(r.member_fit)
                                         else f'{r.title}: unscored' for r in group.itertuples()),
                         note=draft['character_notes'].get(str(key), '')))
    characters = pd.DataFrame(rows)
    ideal_keys = set().union(*(set(family['member_keys']) for family in selected
                              if policy.get('ideal_minimum', 10) <= len(family['member_keys']) <= policy.get('ideal_maximum', 15)))
    weak = characters.family_count.gt(0) & characters.best_fit.lt(target)
    unscored = characters.family_count.gt(0) & characters.best_fit.isna()
    families = pd.DataFrame(family_rows)
    scoring = cohort_scoring_policy(draft, policy)
    if not families.empty and scoring.get('selection_approach') == 'Compact audience cover':
        # Saved suggestions keep their scoring settings; member edits are rescored in that context.
        families['selection_cost'] = base_family_cost(families['size'].to_numpy(), families.family_mean.to_numpy(),
            scoring.get('ideal_minimum', 10), scoring.get('ideal_maximum', 15), scoring.get('size_preference', .5))
        families = collection_costs(families, scoring.get('overlap_penalty', 0.)
                                    if scoring.get('compact_objective', LEGACY_OBJECTIVE) == SCORE_OBJECTIVE else 0.)
    return {'families': families, 'memberships': memberships, 'characters': characters,
            'summary': {'families': len(selected), 'covered': len(covered), 'missing': len(rows) - len(covered),
                        'repeated': sum(value > 1 for value in counts.values()),
                        'extra_memberships': sum(counts.values()) - len(covered),
                        'membership_rows': sum(counts.values()), 'weak_fit': int(weak.sum()),
                        'unscored': int(unscored.sum()), 'ideal_characters': len(ideal_keys)}}


def cohort_scoring_policy(draft: dict, policy: dict | None = None) -> dict:
    """Optimizer cost provenance is separate from mutable review thresholds and memberships."""
    origin = draft.get('origin_suggestion', {})
    if origin.get('method') == 'Compact audience cover':
        return dict(origin['policy'], selection_approach='Compact audience cover')
    return draft['policy'] if policy is None else policy


def overlap_table(draft: dict) -> pd.DataFrame:
    names = {row['character_key']: row['character'] for row in draft['catalog']}
    rows = []
    for first in draft['selected']:
        left = set(first['member_keys'])
        for second in draft['selected']:
            right = set(second['member_keys'])
            shared = left & right
            rows.append({'row_id': first['id'], 'column_id': second['id'],
                         'row_title': first['title'], 'column_title': second['title'],
                         'shared': len(shared), 'union': len(left | right),
                         'jaccard': len(shared) / len(left | right), 'containment': len(shared) / len(left),
                         'shared_characters': ', '.join(sorted(names[key] for key in shared))})
    return pd.DataFrame(rows)


def cohort_payload(draft: dict) -> dict:
    """Checksum the portable evidence and frozen memberships; scalars are recalculated."""
    payload = copy.deepcopy(draft)
    payload.pop('checksum', None)
    payload['saved_at_utc'] = datetime.now(timezone.utc).isoformat()
    payload['checksum'] = fingerprint(payload)
    return payload


def validate_cohort(payload: dict, universe: pd.DataFrame, membership_hash: str, reference_hash: str) -> dict:
    """Validate a self-contained collection without discovery or external services."""
    try:
        draft = copy.deepcopy(payload)
        checksum = draft.pop('checksum')
        if checksum != fingerprint(draft):
            raise ValueError('Cohort checksum differs; the file or its evidence was modified.')
        if (draft['schema_version'] != 1 or draft['membership_sha256'] != membership_hash
                or draft['reference_sha256'] != reference_hash):
            raise ValueError('Cohort uses a different snapshot, population reference or schema.')
        expected = universe[['character_key', 'character']].sort_values('character_key').reset_index(drop=True)
        actual = pd.DataFrame(draft['catalog']).sort_values('character_key').reset_index(drop=True)
        if not expected.equals(actual):
            raise ValueError('Cohort catalog does not match this snapshot.')
        if not 0 <= draft['member_target'] <= 1:
            raise ValueError('Invalid member-fit target.')
        for source_id, source in draft['sources'].items():
            if fingerprint(source['scenario']) != source_id:
                raise ValueError('Source scenario fingerprint differs.')
            context = source['scenario']['source']
            if context['membership_sha256'] != membership_hash or context['reference_sha256'] != reference_hash:
                raise ValueError('Source evidence belongs to another snapshot or reference.')
            baseline = pd.DataFrame(source['automatic'])
            if not baseline[['character_key', 'character']].sort_values('character_key').reset_index(drop=True).equals(expected):
                raise ValueError('Source evidence catalog does not match.')
            if source.get('method') == 'anchored_leiden':
                evaluated = source['co_membership']['character_keys']
                if (not evaluated or set(evaluated) != set(source['evaluated_keys'])
                        or not set(evaluated).issubset(set(baseline.character_key)) or source['anchor'] not in evaluated
                        or source.get('method_version') != 1):
                    raise ValueError('Invalid anchored evaluation scope.')
                definition = source['scenario']['anchored']
                if definition['anchor'] != source['anchor'] or definition['step']['candidate_neighbors'] != source['candidate_neighbors']:
                    raise ValueError('Anchored source definition differs from its evidence scope.')
                family_consistency(source['co_membership'], baseline.loc[baseline.character_key.isin(evaluated)].reset_index(drop=True))
                if (set(source['neighborhood_eligibility']) != {str(key) for key in evaluated}
                        or any(not np.isfinite(value) or not 0 <= value <= 1 for value in source['neighborhood_eligibility'].values())):
                    raise ValueError('Invalid anchored neighborhood eligibility.')
            else:
                family_consistency(source['co_membership'], baseline)
            maximum_repeats = 10000 if source.get('evidence_kind') == 'Hunter pipeline player bootstrap' else 50
            if not 2 <= source['repetitions'] <= maximum_repeats or not 0 <= source['repeat_seed'] < 2**31:
                raise ValueError('Invalid bootstrap repeat settings.')
            if 'candidate_families' in source:
                family_ids = set()
                for family in source['candidate_families']:
                    if family['family'] in family_ids or len(family['member_keys']) < 2:
                        raise ValueError('Invalid or duplicate hunter family.')
                    subset_scores(source, family['member_keys'])
                    if source.get('method') == 'anchored_leiden' and (source['anchor'] not in family['member_keys']
                            or not set(family['member_keys']).issubset(set(source['evaluated_keys']))):
                        raise ValueError('Anchored discoveries must contain their anchor and evaluated members.')
                    if not set(family['anchors']).issubset(family['member_keys']):
                        raise ValueError('Hunter anchors must be included family members.')
                    for field in ['mean_recovery', 'p10_recovery', 'exact_recovery', 'ensemble_agreement', 'ensemble_frequency']:
                        if not np.isfinite(family[field]) or not 0 <= family[field] <= 1:
                            raise ValueError('Hunter diagnostics must be probabilities between zero and one.')
                    family_ids.add(family['family'])
        seen = set()
        source_sets = set()
        for family in draft['selected']:
            source = draft['sources'][family['source_id']]
            keys = family['member_keys']
            expected_id = candidate_id(family['source_id'], family['family'], family['basis'], keys)
            identity = (family['source_id'], tuple(sorted(keys)))
            if family['id'] != expected_id or family['id'] in seen or identity in source_sets:
                raise ValueError('Invalid or duplicate selected-family identity.')
            original = original_family_keys(source, family['family'])
            if family['basis'] == 'Manual variant':
                if (not family.get('manual_reason', '').strip() or len(keys) < 2
                        or not family.get('base_member_keys') or not set(family['base_member_keys']).issubset(original)
                        or family.get('base_basis') not in {'Full family', 'Retained members only'}):
                    raise ValueError('Manual family variants require source membership and a review reason.')
            elif (family['basis'] not in {'Full family', 'Retained members only'} or not set(keys).issubset(original)
                  or (family['basis'] == 'Full family' and set(keys) != original)):
                raise ValueError('Selected members do not match their source family.')
            subset_scores(source, keys)
            if not isinstance(family['title'], str) or not family['title'].strip():
                raise ValueError('Family titles must be nonempty.')
            seen.add(family['id'])
            source_sets.add(identity)
        # Check policy values through the same evaluation used when rendering the library.
        validate_policy(draft['policy'])
        if draft.get('origin_suggestion', {}).get('method') == 'Compact audience cover':
            validate_policy(draft['origin_suggestion']['policy'])
        if any(draft['policy'].get(field, 0) > len(universe) for field in ['minimum_family_size', 'maximum_family_size']):
            raise ValueError('Coverage size limits exceed this character catalog.')
        candidate_library(draft['sources'], draft['policy'])
        summarize_cohort(draft)
        return draft
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError(f'Cohort file is missing or has invalid fields: {error}') from error
