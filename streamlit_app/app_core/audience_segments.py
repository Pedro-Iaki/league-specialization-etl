"""Frozen audience bands and weighted maps, independent of focus eligibility."""
from __future__ import annotations

import copy
import hashlib
import json
from itertools import product

import numpy as np
import pandas as pd

from app_core import data
from app_core.config import ROLE_ORDER
from app_core.data import DashboardDataError
from app_core.family_affinity import affinity_metadata, load_family_definition
from app_core.population import (
    WEIGHT,
    effective_sample_size,
    load_reference,
    population_weights,
    reference_fingerprint,
    validate_reference,
)

DEFINITION_VERSION = 'family-audience-segments-v1'
REFERENCE_FILE = 'audience_segments_reference.json'
RANK_GROUPS = ['Lowest', 'Medium', 'High', 'Highest']
RANK_MAP = dict(zip(
    ['IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER', 'GRANDMASTER', 'CHALLENGER'],
    ['Lowest'] * 3 + ['Medium'] * 2 + ['High'] + ['Highest'] * 4, strict=True,
))
CHARACTER_TYPES = dict(zip(ROLE_ORDER, ['A', 'B', 'C', 'D', 'E'], strict=True))
# Readable ranges, chosen once after inspecting the wider, calibrated audience.
# These approximate the scale of its distribution; they are not quintiles.
BAND_SPECS = {
    'activity_band': {'source': 'lifetime_mastery_points', 'prefix': 'A',
                      'right_closed_cuts': [600000, 1500000, 2500000, 4000000],
                      'labels': ['Up to 600k', '600k–1.5m', '1.5m–2.5m', '2.5m–4m', 'Over 4m']},
    'engagement_band': {'source': 'total_games', 'prefix': 'E', 'right_closed_cuts': [24, 99, 249, 499],
                        'labels': ['1–24', '25–99', '100–249', '250–499', '500+']},
    'history_band': {'source': 'oldest_retained_play_days', 'prefix': 'H',
                    'right_closed_cuts': [365, 1095, 1825, 2555],
                    'labels': ['Up to 1 year', '1–3 years', '3–5 years', '5–7 years', 'Over 7 years']},
}
MINIMUM_PLAYERS = 30
MINIMUM_EFFECTIVE_PLAYERS = 20
REQUIRED = {'region', 'queue', 'tier', 'as_of_date', 'main_role', 'family_state', 'family_category',
            'primary_family_id', 'family_affinity', *(spec['source'] for spec in BAND_SPECS.values())}


def build_segment_reference(players: pd.DataFrame, source_hash: str, rank_reference: pd.DataFrame | None = None) -> dict:
    """Freeze the whole profile base and target reference; run only on manual refresh."""
    _validate_profiles(players)
    target = load_reference() if rank_reference is None else validate_reference(rank_reference)
    _, support = population_weights(players, target)
    return {
        'definition_version': DEFINITION_VERSION,
        'source_profile_sha256': source_hash,
        'source_profile_count': len(players),
        'as_of_date': str(pd.to_datetime(players.as_of_date).max().date()),
        'scope': players[['region', 'queue']].drop_duplicates().iloc[0].to_dict(),
        'family_affinity': affinity_metadata(load_family_definition()),
        'rank_reference': target.to_dict('records'),
        'rank_reference_sha256': reference_fingerprint(target),
        'tier_support': support[['tier', 'sample_players', 'represented', 'population_share']].to_dict('records'),
        'bands': copy.deepcopy(BAND_SPECS),
        'minimum_players': MINIMUM_PLAYERS,
        'minimum_effective_players': MINIMUM_EFFECTIVE_PLAYERS,
        'cohort': 'All current profiles; no family, type, focus, history or spending eligibility filter',
        'weighting': 'Individual-tier calibration on the full profile scope, inherited after filtering',
        'rank_map_statistic': 'P(activity band | rank group), conditional on any selected engagement/history lens',
        'affinity_statistic': 'Weighted mean among scored vectors; unavailable vectors excluded with coverage reported',
        'primary_statistic': 'Exclusive primary-category share of all selected weighted profiles, including tie/missing states',
        'suppression': 'Mask displayed estimates when cell N < 30 or Kish effective N < 20; retain denominators and raw shares',
    }


def load_segment_reference() -> dict:
    """Reject a reference from another profile snapshot; do not rebuild on page filters."""
    try:
        path = data.DATA_DIR / REFERENCE_FILE
        reference = json.loads(path.read_text(encoding='utf-8'))
        item = data.load_manifest().get('audience_segments_reference', {})
        if item and item.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Audience segment reference differs from its manifest')
        actual = hashlib.sha256(data.snapshot_paths()['players'].read_bytes()).hexdigest()
        if reference.get('source_profile_sha256') != actual:
            raise ValueError('Audience segment reference belongs to a different player snapshot')
        _validate_reference(reference)
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise DashboardDataError(f'Cannot use frozen audience segments: {error}') from error
    return reference


def prepare_segments(players: pd.DataFrame, reference: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calibrate the complete base once. Callers filter this result without recalibrating."""
    _validate_reference(reference)
    _validate_profiles(players)
    if len(players) != reference['source_profile_count'] or players[['region', 'queue']].iloc[0].to_dict() != reference['scope']:
        raise ValueError('Prepare segments on the complete matching profile scope before filtering')
    frame, diagnostics = population_weights(players, pd.DataFrame(reference['rank_reference']))
    frame = assign_bands(frame, reference)
    frame['rank_group'] = frame.tier.map(RANK_MAP).fillna('Unrecognized')
    frame['character_type'] = frame.main_role.map(CHARACTER_TYPES).fillna('Unavailable')
    return frame, diagnostics


def assign_bands(frame: pd.DataFrame, reference: dict) -> pd.DataFrame:
    """Equal values stay together; zero and invalid/missing values get distinct codes."""
    result = frame.copy()
    for column, spec in reference['bands'].items():
        values = pd.to_numeric(result[spec['source']], errors='coerce')
        positive = np.isfinite(values) & values.gt(0)
        codes = pd.Series('Missing', index=result.index, dtype=object)
        codes.loc[values.eq(0)] = spec['prefix'] + '0'
        ordinal = np.searchsorted(spec['right_closed_cuts'], values.loc[positive], side='left') + 1
        codes.loc[positive] = [f"{spec['prefix']}{number}" for number in ordinal]
        result[column] = codes
    return result


def band_order(reference: dict, dimension: str) -> list[str]:
    prefix = reference['bands'][dimension]['prefix']
    return [f'{prefix}{number}' for number in range(6)] + ['Missing']


def rank_context(reference: dict) -> pd.DataFrame:
    """Full saved reference prevalence, observed coverage and sparse-tier mass, separately."""
    support = pd.DataFrame(reference['tier_support'])
    support['rank_group'] = support.tier.map(RANK_MAP)
    support['supported_share'] = support.population_share.where(support.represented, 0)
    support['sparse_tier_share'] = support.population_share.where(
        support.sample_players.between(1, reference['minimum_players'] - 1), 0)
    grouped = support.groupby('rank_group').agg(
        reference_share=('population_share', 'sum'), supported_share=('supported_share', 'sum'),
        sparse_tier_share=('sparse_tier_share', 'sum'), profiles=('sample_players', 'sum'),
    ).reindex(RANK_GROUPS).reset_index()
    grouped['unsupported_share'] = grouped.reference_share - grouped.supported_share
    return grouped


def segment_counts(frame: pd.DataFrame, dimensions: list[str], *, conditional_on: list[str] | None = None,
                   levels: dict[str, list] | None = None) -> pd.DataFrame:
    """Joint shares or a named conditional; transposing dimensions cannot change the statistic.

    Always use frozen positive weights. Suppression masks estimates, never their
    denominators or the underlying shares. Empty cells remain distinguishable.
    """
    conditional_on = conditional_on or []
    if not dimensions or not set(conditional_on).issubset(dimensions):
        raise ValueError('A conditional denominator must be one of the grouped dimensions')
    valid = _weighted_rows(frame)
    valid[dimensions] = valid[dimensions].astype(object).fillna('Missing')
    valid['_squared_weight'] = valid[WEIGHT] ** 2
    grouped = valid.groupby(dimensions, observed=True, dropna=False).agg(
        profiles=(WEIGHT, 'size'), weighted_mass=(WEIGHT, 'sum'), squared_weights=('_squared_weight', 'sum'))
    if levels is not None:
        if any(not set(valid[key]).issubset(levels[key]) for key in dimensions):
            raise ValueError('Display levels cannot drop observed categories from the denominator')
        index = pd.MultiIndex.from_tuples(list(product(*(levels[key] for key in dimensions))), names=dimensions)
        if len(dimensions) == 1:
            index = pd.Index(levels[dimensions[0]], name=dimensions[0])
        grouped = grouped.reindex(index, fill_value=0)
    result = grouped.reset_index()
    result['effective_players'] = result.weighted_mass.pow(2) / result.squared_weights.replace(0, np.nan)
    if conditional_on:
        denominator = result.groupby(conditional_on, observed=True).weighted_mass.transform('sum')
    else:
        denominator = result.weighted_mass.sum()
    result['denominator_weight'] = denominator
    result['share'] = result.weighted_mass / result.denominator_weight.replace(0, np.nan)
    result['status'] = np.select([result.profiles.eq(0), result.profiles.lt(MINIMUM_PLAYERS)
                                 | result.effective_players.lt(MINIMUM_EFFECTIVE_PLAYERS)],
                                ['empty', 'sparse'], default='available')
    result['estimate'] = result.share.where(result.status.eq('available'))
    return result.drop(columns='squared_weights')


def family_cells(frame: pd.DataFrame, family_id: str, dimensions: list[str]) -> pd.DataFrame:
    """Affinity uses scored-vector denominators; primary prevalence keeps the whole cell."""
    definition = load_family_definition()
    if family_id not in definition.family_order:
        raise ValueError('Unknown family coordinate')
    position = definition.family_order.index(family_id)
    valid = _weighted_rows(frame)
    columns = [*dimensions, 'family_id', 'profiles', 'effective_players', 'weighted_mass',
               'scored_profiles', 'scored_effective_players', 'scored_weight', 'scored_coverage',
               'primary_profiles', 'primary_effective_players',
               'mean_affinity', 'primary_share', 'affinity_estimate', 'primary_estimate']
    if valid.empty:
        return pd.DataFrame(columns=columns)
    valid['_score'] = [float(vector[position]) if state in {'primary', 'shared_top'} else np.nan
                       for vector, state in zip(valid.family_affinity, valid.family_state, strict=True)]
    rows = []
    groups = valid.groupby(dimensions, observed=True, dropna=False) if dimensions else [((), valid)]
    for keys, cell in groups:
        keys = keys if isinstance(keys, tuple) else (keys,)
        scored = cell.loc[cell._score.notna()]
        total, scored_total = cell[WEIGHT].sum(), scored[WEIGHT].sum()
        n_eff, scored_eff = effective_sample_size(cell[WEIGHT]), effective_sample_size(scored[WEIGHT])
        mean = float(np.average(scored._score, weights=scored[WEIGHT])) if scored_total else np.nan
        primary_rows = cell.loc[cell.primary_family_id.eq(family_id)]
        primary_eff = effective_sample_size(primary_rows[WEIGHT])
        primary = float(primary_rows[WEIGHT].sum() / total)
        rows.append({
            **dict(zip(dimensions, keys, strict=True)), 'family_id': family_id,
            'profiles': len(cell), 'effective_players': n_eff, 'weighted_mass': float(total),
            'scored_profiles': len(scored), 'scored_effective_players': scored_eff,
            'scored_weight': float(scored_total), 'scored_coverage': float(scored_total / total),
            'primary_profiles': len(primary_rows), 'primary_effective_players': primary_eff,
            'mean_affinity': mean, 'primary_share': primary,
            'affinity_estimate': mean if len(scored) >= MINIMUM_PLAYERS and scored_eff >= MINIMUM_EFFECTIVE_PLAYERS else np.nan,
            'primary_estimate': primary if len(primary_rows) >= MINIMUM_PLAYERS and primary_eff >= MINIMUM_EFFECTIVE_PLAYERS else np.nan,
        })
    return pd.DataFrame(rows, columns=columns)


def _weighted_rows(frame):
    if WEIGHT not in frame:
        raise ValueError('Audience summaries require weights frozen before selection')
    values = pd.to_numeric(frame[WEIGHT], errors='coerce')
    mask = np.isfinite(values) & values.gt(0)
    valid = frame.loc[mask].copy()
    valid[WEIGHT] = values.loc[mask].to_numpy()
    return valid


def _validate_profiles(players):
    if players.empty or not REQUIRED.issubset(players):
        raise ValueError('Complete family-enriched profiles are required')
    if players[['region', 'queue']].isna().any().any() or len(players[['region', 'queue']].drop_duplicates()) != 1:
        raise ValueError('Audience maps require one documented region and queue; do not pool unknown population scopes')
    if players[['region', 'queue']].iloc[0].to_dict() != {'region': 'na1', 'queue': 'RANKED_SOLO_5x5'}:
        raise ValueError('The accepted population reference targets NA ranked solo/duo')
    if players.attrs.get('family_affinity') != affinity_metadata(load_family_definition()):
        raise ValueError('Profile family metadata differs from the pinned audience metric')


def _validate_reference(reference):
    if (reference.get('definition_version') != DEFINITION_VERSION
            or reference.get('family_affinity') != affinity_metadata(load_family_definition())):
        raise ValueError('Unsupported audience/family definition')
    if reference_fingerprint(pd.DataFrame(reference['rank_reference'])) != reference['rank_reference_sha256']:
        raise ValueError('Frozen population reference fingerprint differs')
    if reference.get('bands') != BAND_SPECS:
        raise ValueError('Unsupported fixed audience bands; version a deliberate band change')
    if (reference.get('minimum_players') != MINIMUM_PLAYERS
            or reference.get('minimum_effective_players') != MINIMUM_EFFECTIVE_PLAYERS):
        raise ValueError('Unsupported audience suppression policy')
