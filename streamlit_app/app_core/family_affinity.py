"""Lifetime mastery within model-selected active pools, attributed to overlapping families.

This module performs no source joins, population weighting, discovery, or serving writes.
Callers must supply the correctly associated player's active champion records.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType

DEFINITION_PATH = Path(__file__).resolve().parents[1] / 'definitions/champion-audience-families-v1.json'
DEFINITION_SHA256 = 'fdb8f3eaca472fcf24b749a1d6af60ea74b0d908c1dbcfd831a5339a8029f781'
COHORT_ID = 'champion-audience-families-v1'
METRIC_ID = 'active_pool_lifetime_mastery_family_affinity_v1'
MINIMUM_MASTERY = 15_000
TIE_ATOL = 1e-12
STATE_LABELS = {
    'shared_top': 'Shared top',
    'no_active_pool': 'No active pool',
    'insufficient_mastery': 'Insufficient mastery',
    'unmapped_pool': 'Unmapped pool',
    'unavailable_pool': 'Pool unavailable',
}
AFFINITY_COLUMNS = (
    'family_affinity', 'family_state', 'family_category', 'primary_family_id', 'top_family_ids',
    'top_family_score', 'runner_up_family_ids', 'runner_up_family_score', 'family_gap',
    'active_pool_available', 'active_pool_champion_count', 'active_pool_mastery_points',
    'eligible_pool_champion_count', 'eligible_pool_mastery_points', 'scored_pool_champion_count',
    'scored_pool_mastery_points', 'below_cutoff_mastery_points', 'unmapped_mastery_points',
    'below_cutoff_mastery_share', 'unmapped_mastery_share', 'scored_mastery_share',
    'unknown_champion_count', 'family_weighting_fallback',
)


@dataclass(frozen=True)
class FamilyDefinition:
    cohort_id: str
    sha256: str
    family_order: tuple[str, ...]
    champion_families: Mapping[int, tuple[int, ...]]


def player_family_affinity(members: Iterable[Mapping] | None, definition: FamilyDefinition) -> dict:
    """Score one confirmed active pool using records with integer ``key`` and numeric ``points``.

    ``None`` means unavailable evidence; an empty iterable means a confirmed empty pool.
    Below-cutoff and unknown mastery remain in the denominator. No fallback is applied.
    """
    result = {
        'family_affinity': None, 'family_state': 'unavailable_pool', 'family_category': STATE_LABELS['unavailable_pool'],
        'primary_family_id': None, 'top_family_ids': [], 'top_family_score': None,
        'runner_up_family_ids': [], 'runner_up_family_score': None, 'family_gap': None,
        'active_pool_available': members is not None,
        'active_pool_champion_count': None, 'active_pool_mastery_points': None,
        'eligible_pool_champion_count': None, 'eligible_pool_mastery_points': None,
        'scored_pool_champion_count': None, 'scored_pool_mastery_points': None,
        'below_cutoff_mastery_points': None, 'unmapped_mastery_points': None,
        'below_cutoff_mastery_share': None, 'unmapped_mastery_share': None, 'scored_mastery_share': None,
        'unknown_champion_count': None, 'family_weighting_fallback': False,
    }
    if members is None:
        return result

    records = _pool_records(members)
    total = _sum_points(points for _, points in records)
    eligible = [(key, points) for key, points in records if points >= MINIMUM_MASTERY]
    mapped = [(key, points) for key, points in eligible if key in definition.champion_families]
    below = _sum_points(points for _, points in records if points < MINIMUM_MASTERY)
    unknown = _sum_points(points for key, points in eligible if key not in definition.champion_families)
    scored = _sum_points(points for _, points in mapped)
    result.update(
        active_pool_champion_count=len(records), active_pool_mastery_points=total,
        eligible_pool_champion_count=len(eligible), eligible_pool_mastery_points=_sum_points(p for _, p in eligible),
        scored_pool_champion_count=len(mapped), scored_pool_mastery_points=scored,
        below_cutoff_mastery_points=below, unmapped_mastery_points=unknown,
        below_cutoff_mastery_share=below / total if total else None,
        unmapped_mastery_share=unknown / total if total else None,
        scored_mastery_share=scored / total if total else None,
        unknown_champion_count=sum(key not in definition.champion_families for key, _ in records),
    )
    if not records:
        state = 'no_active_pool'
    elif not eligible:
        state = 'insufficient_mastery'
    elif not mapped:
        state = 'unmapped_pool'
    else:
        return _rank_affinities(mapped, total, definition, result)
    result.update(family_state=state, family_category=STATE_LABELS[state])
    return result


def load_family_definition(path: Path = DEFINITION_PATH, expected_sha256: str = DEFINITION_SHA256) -> FamilyDefinition:
    """Load a pinned definition; changing its bytes requires an explicit new identity."""
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValueError('Family definition SHA-256 differs from the expected version.')
    definition = prepare_family_definition(json.loads(content), definition_sha256=digest)
    if path == DEFINITION_PATH and (definition.cohort_id != COHORT_ID or len(definition.family_order) != 25):
        raise ValueError('The accepted definition must contain F01–F25 for the frozen cohort.')
    return definition


def prepare_family_definition(payload: Mapping, *, definition_sha256: str) -> FamilyDefinition:
    """Compile immutable canonical lookup tables; the caller owns the supplied source hash.

    Exporters should use ``load_family_definition`` to verify actual file bytes. This pure
    entry point also permits small independently checked definitions in calculation tests.
    """
    if not isinstance(definition_sha256, str) or not re.fullmatch('[0-9a-f]{64}', definition_sha256):
        raise ValueError('A definition requires its SHA-256 identity.')
    if not isinstance(payload, Mapping) or type(payload.get('schema_version')) is not int or payload['schema_version'] != 1:
        raise ValueError('Unsupported family definition schema.')
    cohort_id, families = payload.get('cohort_id'), payload.get('families')
    if not isinstance(cohort_id, str) or not cohort_id or not isinstance(families, list) or not families:
        raise ValueError('Family definition requires a cohort ID and nonempty families.')
    groups = {}
    for family in families:
        if not isinstance(family, Mapping):
            raise TypeError('Each family must be an object.')
        family_id, members = family.get('family_key'), family.get('members')
        if not isinstance(family_id, str) or not re.fullmatch(r'F[0-9]{2}', family_id) or family_id in groups:
            raise ValueError('Family IDs must be unique Fxx identifiers.')
        if not isinstance(members, list) or not members:
            raise ValueError('Each family requires member champions.')
        keys = []
        for member in members:
            if not isinstance(member, Mapping):
                raise TypeError('Each family member must be an object.')
            key = member.get('character_key')
            if isinstance(key, bool) or not isinstance(key, Integral) or key < 1:
                raise ValueError('Champion keys must be positive integers.')
            keys.append(int(key))
        if len(keys) != len(set(keys)):
            raise ValueError('A champion cannot appear twice inside one family.')
        groups[family_id] = keys
    order = tuple(sorted(groups))
    champion_families = {}
    for index, family_id in enumerate(order):
        for key in groups[family_id]:
            champion_families.setdefault(key, []).append(index)
    return FamilyDefinition(cohort_id, definition_sha256, order,
                            MappingProxyType({key: tuple(value) for key, value in champion_families.items()}))


def affinity_metadata(definition: FamilyDefinition) -> dict:
    """Serializable metric identity; exporters add actual source dates and file hashes."""
    return {
        'schema_version': 1, 'metric_id': METRIC_ID, 'metric_version': 1,
        'family_cohort_id': definition.cohort_id, 'family_definition_sha256': definition.sha256,
        'family_order': list(definition.family_order), 'minimum_mastery': MINIMUM_MASTERY,
        'denominator': 'All lifetime mastery within the full model-selected active pool',
        'attribution': 'Full membership in every containing family; coordinates are not additive',
        'membership_source': 'fct_players_champion_activity.is_recent_pool_champion',
        'weight_source': 'fct_masteries_current.champion_points',
        'date_basis': 'Model active membership as of its observation; lifetime points at their retained snapshot. '
                   'Exporter must record actual source/as-of/snapshot dates.',
        'tie_atol': TIE_ATOL, 'tie_rtol': 0, 'weighting_fallback': False,
        'null_vector_states': [state for state in STATE_LABELS if state != 'shared_top'],
    }


def _pool_records(members):
    if isinstance(members, (str, bytes, Mapping)):
        raise TypeError('Supply an iterable of active champion records, or None for unavailable evidence.')
    try:
        iterator = iter(members)
    except TypeError as error:
        raise ValueError('Active champion pool is not iterable.') from error
    records, seen = [], set()
    for member in iterator:
        if not isinstance(member, Mapping) or 'key' not in member or 'points' not in member:
            raise ValueError('Each active champion needs key and points fields.')
        key, points = member['key'], member['points']
        if isinstance(key, bool) or not isinstance(key, Integral) or key < 1:
            raise ValueError('Active champion keys must be positive integers.')
        if key in seen:
            raise ValueError('Duplicate active champion key; validate the source join grain.')
        if isinstance(points, bool) or not isinstance(points, Real):
            raise TypeError('Lifetime mastery points must be finite nonnegative numbers.')
        try:
            value = float(points)
        except OverflowError as error:
            raise ValueError('Lifetime mastery points exceed the finite numeric range.') from error
        if not math.isfinite(value) or value < 0:
            raise ValueError('Lifetime mastery points must be finite nonnegative numbers.')
        records.append((int(key), value))
        seen.add(key)
    return sorted(records)


def _sum_points(values):
    try:
        return math.fsum(values)
    except OverflowError as error:
        raise ValueError('Total lifetime mastery exceeds the finite numeric range.') from error


def _rank_affinities(mapped, total, definition, result):
    contributions = [[] for _ in definition.family_order]
    for key, points in mapped:
        for index in definition.champion_families[key]:
            contributions[index].append(points)
    scores = [_sum_points(values) / total for values in contributions]
    top = max(scores)
    top_indices = [i for i, score in enumerate(scores) if score > 0 and math.isclose(score, top, rel_tol=0, abs_tol=TIE_ATOL)]
    shared = len(top_indices) > 1
    runner = top if shared else max((score for i, score in enumerate(scores) if i != top_indices[0]), default=0)
    runner_ids = [] if shared else [
        definition.family_order[i] for i, score in enumerate(scores)
        if i != top_indices[0] and score > 0 and math.isclose(score, runner, rel_tol=0, abs_tol=TIE_ATOL)]
    primary = None if shared else definition.family_order[top_indices[0]]
    result.update(
        family_affinity=scores, family_state='shared_top' if shared else 'primary',
        family_category=STATE_LABELS['shared_top'] if shared else primary, primary_family_id=primary,
        top_family_ids=[definition.family_order[i] for i in top_indices], top_family_score=top,
        runner_up_family_ids=runner_ids, runner_up_family_score=runner,
        family_gap=0. if shared else top - runner,
    )
    return result
