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
from app_core.family_batch import evaluate_scenario


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


def finite_or_none(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def subset_scores(source: dict, keys: list, target: float = .8) -> tuple[pd.DataFrame, float]:
    """Score included members by key, excluding self even with nonunit diagonals."""
    matrix_keys = source['co_membership']['character_keys']
    positions = {key: i for i, key in enumerate(matrix_keys)}
    if not keys or len(set(keys)) != len(keys) or not set(keys).issubset(positions):
        raise ValueError('Included members must be nonempty, unique and present in the source evidence.')
    indices = [positions[key] for key in keys]
    rates = np.asarray(source['co_membership']['rates'], dtype=float)[np.ix_(indices, indices)].copy()
    np.fill_diagonal(rates, np.nan)
    names = {row['character_key']: row['character'] for row in source['automatic']}
    if len(keys) == 1:
        fits = support = weakest = np.array([np.nan])
        mean = np.nan
    else:
        fits = np.nanmean(rates, axis=1)
        support = np.sum(rates >= target, axis=1) / (len(keys) - 1)
        weakest = np.nanmin(rates, axis=1)
        mean = float(fits.mean())
    return pd.DataFrame({'character_key': keys, 'character': [names[key] for key in keys],
                         'member_fit': fits, 'peer_support': support, 'weakest_pair': weakest}), mean


def policy_metrics(candidate: dict, mean: float, covered: set, policy: dict) -> dict:
    """Explain every current exclusion; marginal cost is relative to this draft."""
    size = len(candidate['member_keys'])
    low, high = policy.get('ideal_minimum', 10), policy.get('ideal_maximum', 15)
    distance = max(0., np.log2(low / size), np.log2(size / high))
    cost = 2 - mean + 10 * policy.get('size_preference', .5) * distance if pd.notna(mean) else np.nan
    new = len(set(candidate['member_keys']) - covered)
    marginal = cost / new if new else np.nan
    reasons = []
    if pd.isna(mean):
        reasons.append('No pair evidence')
    elif mean < policy.get('family_target', .8):
        reasons.append('Below family-consistency target')
    if policy.get('cover_basis') == 'Full families only' and candidate['basis'] != 'Full family':
        reasons.append('Excluded by full-only basis')
    if size < policy.get('minimum_family_size', 1):
        reasons.append('Below minimum size')
    if policy.get('maximum_family_size', 0) and size > policy['maximum_family_size']:
        reasons.append('Above maximum size')
    if policy.get('selection_approach') == 'Target-size cover':
        if policy.get('max_family_cost') is not None and cost > policy['max_family_cost'] + 1e-12:
            reasons.append('Above family-cost ceiling')
        if (policy.get('max_cost_per_character') is not None
                and new and marginal > policy['max_cost_per_character'] + 1e-12):
            reasons.append('Above current marginal-cost limit')
    return {'size': size, 'family_mean': mean, 'proportional_distance': distance,
            'in_ideal_range': low <= size <= high, 'selection_cost': cost,
            'new_characters': new, 'already_covered': size - new,
            'cost_per_new_character': marginal, 'policy_flags': ' | '.join(reasons),
            'eligible': not reasons}


def validate_policy(policy: dict) -> None:
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
    if policy.get('cover_basis', 'Full + retained') not in {'Full + retained', 'Full families only'}:
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
                                repeated_characters=sum(counts[key] > 1 for key in family['member_keys'])))
        links.extend(fits.assign(family_id=family['id'], title=family['title'],
                                 source_id=family['source_id'], family_mean=mean).to_dict('records'))
    memberships = pd.DataFrame(links, columns=['character_key', 'character', 'member_fit', 'peer_support',
                                               'weakest_pair', 'family_id', 'title', 'source_id', 'family_mean'])
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
    return {'families': pd.DataFrame(family_rows), 'memberships': memberships, 'characters': characters,
            'summary': {'families': len(selected), 'covered': len(covered), 'missing': len(rows) - len(covered),
                        'repeated': sum(value > 1 for value in counts.values()),
                        'extra_memberships': sum(counts.values()) - len(covered),
                        'membership_rows': sum(counts.values()), 'weak_fit': int(weak.sum()),
                        'unscored': int(unscored.sum()), 'ideal_characters': len(ideal_keys)}}


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
            family_consistency(source['co_membership'], baseline)
            if not 2 <= source['repetitions'] <= 50 or not 0 <= source['repeat_seed'] < 2**31:
                raise ValueError('Invalid bootstrap repeat settings.')
        seen = set()
        source_sets = set()
        for family in draft['selected']:
            source = draft['sources'][family['source_id']]
            keys = family['member_keys']
            expected_id = candidate_id(family['source_id'], family['family'], family['basis'], keys)
            identity = (family['source_id'], tuple(sorted(keys)))
            if family['id'] != expected_id or family['id'] in seen or identity in source_sets:
                raise ValueError('Invalid or duplicate selected-family identity.')
            original = {r['character_key'] for r in source['automatic'] if r['family'] == family['family']}
            if (family['basis'] not in {'Full family', 'Retained members only'} or not set(keys).issubset(original)
                    or (family['basis'] == 'Full family' and set(keys) != original)):
                raise ValueError('Selected members do not match their source family.')
            subset_scores(source, keys)
            if not isinstance(family['title'], str) or not family['title'].strip():
                raise ValueError('Family titles must be nonempty.')
            seen.add(family['id'])
            source_sets.add(identity)
        # Check policy values through the same evaluation used when rendering the library.
        validate_policy(draft['policy'])
        if any(draft['policy'].get(field, 0) > len(universe) for field in ['minimum_family_size', 'maximum_family_size']):
            raise ValueError('Coverage size limits exceed this character catalog.')
        candidate_library(draft['sources'], draft['policy'])
        summarize_cohort(draft)
        return draft
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError(f'Cohort file is missing or has invalid fields: {error}') from error
