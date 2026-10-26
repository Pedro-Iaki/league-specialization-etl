"""Private-key audience enrichment and strict anonymous family export contracts."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app_core.business import BUSINESS_PUBLIC_COLUMNS
from app_core.family_affinity import (
    AFFINITY_COLUMNS,
    STATE_LABELS,
    TIE_ATOL,
    FamilyDefinition,
    affinity_metadata,
    player_family_affinity,
)

PROFILE_CONTEXT_COLUMNS = (
    'as_of_date', 'snapshot_date', 'region', 'queue', 'patch', 'tier', 'tier_order',
    'division', 'league_points', 'rank_score', 'total_games', 'win_rate',
    'latest_rank_period_window_days', 'latest_rank_period_games', 'latest_rank_period_lp_delta',
    'latest_rank_period_win_rate', 'latest_rank_period_lp_per_game', 'latest_rank_period_lp_per_day',
    'latest_rank_period_games_per_day', 'latest_rank_period_days_covered',
    'role_top_pct', 'role_jungle_pct', 'role_middle_pct', 'role_bottom_pct', 'role_support_pct',
    'role_purity', 'main_role', 'main_role_weight', 'role_champions_sampled_count',
    'recent_champion_count', 'recent_mastery_points', 'recent_primary_champion_key',
    'recent_primary_champion_name', 'recent_playstyle', 'recent_top1_share',
    'recent_favoured_champion_count', 'recent_favoured_champions_share', 'recent_hhi', 'recent_normalized_entropy',
    'lifetime_champion_count', 'lifetime_mastery_points', 'lifetime_primary_champion_key',
    'lifetime_primary_champion_name', 'lifetime_top1_share', 'lifetime_favoured_champion_count',
    'lifetime_favoured_champions_share', 'lifetime_hhi', 'lifetime_normalized_entropy', 'lifetime_playstyle',
    'tracked_mastery_points_per_day', 'days_since_last_play', 'days_tracked',
)
ACTIVE_SUMMARY_COLUMNS = (
    'active_pool_lifetime_champion_count', 'active_pool_lifetime_mastery_points',
    'active_pool_lifetime_primary_champion_key', 'active_pool_lifetime_primary_champion_name',
    'active_pool_lifetime_primary_champion_points', 'active_pool_lifetime_top1_share', 'active_pool_lifetime_hhi',
)
HISTORY_COLUMNS = ('oldest_retained_play_at', 'oldest_retained_play_days',
                   'mastery_source_min_snapshot_date', 'mastery_source_max_snapshot_date')
BUSINESS_CONTEXT_COLUMNS = (
    'as_of_date', 'snapshot_date', 'region', 'queue', 'tier', 'main_role', 'total_games',
    'lifetime_mastery_points', 'lifetime_playstyle', 'recent_playstyle', 'days_tracked', *HISTORY_COLUMNS,
)
PROFILE_AUDIENCE_COLUMNS = (*PROFILE_CONTEXT_COLUMNS, *ACTIVE_SUMMARY_COLUMNS, *HISTORY_COLUMNS,
                            *AFFINITY_COLUMNS, 'population_weight')
BUSINESS_AUDIENCE_COLUMNS = (*BUSINESS_PUBLIC_COLUMNS, *AFFINITY_COLUMNS,
                             *(f'audience_{column}' for column in BUSINESS_CONTEXT_COLUMNS))

# Full active membership is selected in SQL; all mastery/cutoff scoring happens in the pure helper.
FAMILY_PROFILE_QUERY = """
with active_members as (
    select a.player_id, sort_array(collect_list(named_struct(
        'key', cast(a.champion_key as int), 'name', c.name, 'points', cast(m.champion_points as bigint)
    ))) as members
    from league_pipeline.gold.fct_players_champion_activity a
    left join league_pipeline.silver.fct_masteries_current m
      on a.player_id = m.puuid and a.champion_key = m.champion_key
    left join league_pipeline.silver.dim_champions c on a.champion_key = c.key
    where a.is_recent_pool_champion
    group by a.player_id
), activity_available as (
    select distinct player_id from league_pipeline.gold.fct_players_champion_activity
), as_of as (
    select max(as_of_date) as as_of_date from league_pipeline.gold.mart_player_profile
), mastery_history as (
    select m.puuid as player_id,
        min(case when m.champion_points > 0 and m.last_play_time > timestamp '2009-01-01'
                  and cast(m.last_play_time as date) <= ao.as_of_date then m.last_play_time end) as oldest_retained_play_at,
        min(m.snapshot_date) as mastery_source_min_snapshot_date,
        max(m.snapshot_date) as mastery_source_max_snapshot_date
    from league_pipeline.silver.fct_masteries_current m cross join as_of ao
    group by m.puuid
)
select p.*, coalesce(a.members, array()) as _active_members, av.player_id is not null as _active_pool_available,
    h.oldest_retained_play_at,
    datediff(p.as_of_date, cast(h.oldest_retained_play_at as date)) as oldest_retained_play_days,
    h.mastery_source_min_snapshot_date, h.mastery_source_max_snapshot_date
from league_pipeline.gold.mart_player_profile p
left join active_members a on p.player_id = a.player_id
left join activity_available av on p.player_id = av.player_id
left join mastery_history h on p.player_id = h.player_id
"""
FAMILY_BUSINESS_QUERY = 'select * from league_pipeline.gold.mart_player_spending'


def prepare_private_profiles(source: pd.DataFrame, definition: FamilyDefinition, archetype_model: dict | None = None) -> pd.DataFrame:
    """Keep the real key only in memory until both anonymous exports have been associated."""
    _unique_keys(source, ['player_id'], 'profile')
    required = {'player_id', '_active_members', '_active_pool_available', *PROFILE_CONTEXT_COLUMNS, *HISTORY_COLUMNS}
    if not required.issubset(source.columns):
        raise ValueError('Joint profile query is missing required source fields.')
    if source.queue.isna().any() or not source._active_pool_available.eq(True).all():
        raise ValueError('A complete profile export requires queue and confirmed active-pool source availability.')
    source = source.reset_index(drop=True)
    lifetime = pd.to_numeric(source.lifetime_mastery_points, errors='coerce')
    if not np.isfinite(lifetime).all() or lifetime.lt(0).any():
        raise ValueError('Lifetime account mastery must be finite and nonnegative.')
    scores, summaries = [], []
    for members in source._active_members:
        pool = [] if members is None else list(members)  # query LEFT JOIN absence is confirmed empty
        score = player_family_affinity(pool, definition)
        scores.append(score)
        total = score['active_pool_mastery_points']
        leader = min(pool, key=lambda member: (-member['points'], member['key'])) if pool and total else None
        summaries.append({
            'active_pool_lifetime_champion_count': len(pool), 'active_pool_lifetime_mastery_points': total,
            'active_pool_lifetime_primary_champion_key': leader['key'] if leader else None,
            'active_pool_lifetime_primary_champion_name': leader.get('name') if leader else None,
            'active_pool_lifetime_primary_champion_points': leader['points'] if leader else None,
            'active_pool_lifetime_top1_share': leader['points'] / total if leader else None,
            'active_pool_lifetime_hhi': math.fsum((member['points'] / total) ** 2 for member in pool) if total else None,
        })
    result = pd.concat([source.loc[:, ['player_id', *PROFILE_CONTEXT_COLUMNS, *HISTORY_COLUMNS]].copy(),
                        pd.DataFrame(summaries), pd.DataFrame(scores)], axis=1)
    history = pd.to_datetime(result.oldest_retained_play_at, utc=True).dt.tz_localize(None)
    as_of = pd.to_datetime(result.as_of_date, utc=True).dt.tz_localize(None)
    if ((history.notna() & (history.dt.normalize() > as_of))
            | result.oldest_retained_play_days.lt(0)).any():
        raise ValueError('Oldest retained play cannot be later than the audience observation.')
    elapsed = (as_of.dt.normalize() - history.dt.normalize()).dt.days
    if (history.isna() != result.oldest_retained_play_days.isna()).any() or not np.allclose(
            elapsed.dropna(), result.loc[history.notna(), 'oldest_retained_play_days'], rtol=0, atol=0):
        raise ValueError('Oldest retained play marker disagrees with its observed date span.')
    if (result.active_pool_mastery_points > result.lifetime_mastery_points + 1e-6).any():
        raise ValueError('Active mastery exceeds account mastery; verify source date consistency.')
    if archetype_model is not None:
        from app_core.archetype_serving import model_metadata, score_pools
        result = pd.concat([result, score_pools(source._active_members, archetype_model)], axis=1)
        result.attrs['pool_archetypes'] = model_metadata(archetype_model)
    return result


def attach_business_audience(source: pd.DataFrame, profiles: pd.DataFrame,
                             definition: FamilyDefinition) -> pd.DataFrame:
    """Join actual private keys, preserve frozen traits, expose current context with audience_ prefixes."""
    _unique_keys(source, ['scenario_id', 'player_id'], 'business scenario')
    _unique_keys(profiles, ['player_id'], 'profile')
    if source.scenario_id.nunique() != 1 or not {*BUSINESS_PUBLIC_COLUMNS, 'queue'}.issubset(source.columns):
        raise ValueError('Business source must be one complete frozen scenario with queue.')
    from app_core.archetype_serving import COLUMNS, load_model, score_pools
    archetype_columns = list(COLUMNS) if 'pool_archetypes' in profiles.attrs else []
    current = profiles.loc[:, ['player_id', *BUSINESS_CONTEXT_COLUMNS, *AFFINITY_COLUMNS, *archetype_columns]].copy()
    current['_audience_match'] = True
    current = current.rename(columns={column: f'audience_{column}' for column in BUSINESS_CONTEXT_COLUMNS})
    result = source.merge(current, left_on=['player_id', 'queue'], right_on=['player_id', 'audience_queue'],
                          how='left', validate='many_to_one', sort=False)
    if len(result) != len(source):
        raise ValueError('Private audience join changed the business denominator.')
    empty = player_family_affinity(None, definition)
    for index in result.index[result._audience_match.isna()]:
        for column, value in empty.items():
            result.at[index, column] = value
        if archetype_columns:
            unavailable = score_pools([None], load_model()).iloc[0]
            for column in archetype_columns:
                result.at[index, column] = unavailable[column]
    result = result.loc[:, [*BUSINESS_AUDIENCE_COLUMNS, *archetype_columns]].copy()
    result.attrs['family_affinity'] = affinity_metadata(definition)
    if archetype_columns:
        result.attrs['pool_archetypes'] = profiles.attrs['pool_archetypes']
    return result


def validate_family_frame(frame: pd.DataFrame, metadata: dict, *, business: bool = False) -> None:
    """Validate version, anonymous allowlist, coverage, category and vector invariants on export/load."""
    from app_core.family_affinity import load_family_definition

    definition = load_family_definition()
    expected = affinity_metadata(definition)
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError('Family export metric, definition, family order or scoring metadata differs.')
    allowed = set(BUSINESS_AUDIENCE_COLUMNS if business else PROFILE_AUDIENCE_COLUMNS)
    from app_core.archetype_serving import COLUMNS, validate_archetypes
    if set(COLUMNS).intersection(frame.columns) or 'pool_archetypes' in frame.attrs:
        validate_archetypes(frame, frame.attrs.get('pool_archetypes'))
        allowed.update(COLUMNS)
    if set(frame.columns) != allowed or frame.empty:
        raise ValueError('Family audience export violates its complete anonymous column allowlist.')
    if business and (frame.scenario_id.nunique() != 1 or frame.scenario_id.isna().any()):
        raise ValueError('Family business export must identify one scenario.')
    for row in frame.loc[:, list(AFFINITY_COLUMNS)].to_dict('records'):
        _validate_affinity_row(row, definition.family_order)


def _unique_keys(frame, keys, label):
    if not set(keys).issubset(frame.columns) or frame.empty:
        raise ValueError(f'{label} source lacks its private association keys or is empty.')
    if (frame[keys].isna().any().any() or frame.duplicated(keys).any()
            or any(frame[key].astype(str).str.strip().eq('').any() for key in keys)):
        raise ValueError(f'{label} source has missing/duplicate private keys; no automatic deduplication.')


def _null(value):
    return value is None or value is pd.NA or value is pd.NaT or (np.isscalar(value) and pd.isna(value))


def _validate_affinity_row(row, family_order):
    state, vector = row['family_state'], row['family_affinity']
    if state not in {'primary', 'shared_top', 'no_active_pool', 'insufficient_mastery', 'unmapped_pool', 'unavailable_pool'}:
        raise ValueError('Unknown family evidence state.')
    if row['family_weighting_fallback'] is not False:
        raise ValueError('Family mastery metric cannot use a weighting fallback.')
    active = state != 'unavailable_pool'
    if not isinstance(row['active_pool_available'], (bool, np.bool_)) or bool(row['active_pool_available']) != active:
        raise ValueError('Family pool availability disagrees with its state.')
    total = row['active_pool_mastery_points']
    if not active and any(not _null(row[key]) for key in AFFINITY_COLUMNS if key.endswith(
            ('_count', '_points', '_share'))):
        raise ValueError('Unavailable source cannot invent measured pool counts or mastery.')
    if active:
        counts = [row[key] for key in ['active_pool_champion_count', 'eligible_pool_champion_count',
                                      'scored_pool_champion_count', 'unknown_champion_count']]
        if any(_null(value) or not np.isfinite(value) or value < 0 or value != int(value) for value in counts):
            raise ValueError('Family pool counts must be nonnegative integers.')
        if counts[2] > counts[1] or counts[1] > counts[0] or counts[3] > counts[0]:
            raise ValueError('Family scoring counts disagree with active membership.')
        masses = [row[key] for key in ['active_pool_mastery_points', 'eligible_pool_mastery_points',
                                      'scored_pool_mastery_points', 'below_cutoff_mastery_points', 'unmapped_mastery_points']]
        if any(_null(value) or not np.isfinite(value) or value < 0 for value in masses):
            raise ValueError('Family mastery totals must be finite nonnegative values.')
        if ((counts[0] == 0 and masses[0] != 0)
                or (counts[1] == 0) != (masses[1] == 0)
                or (counts[2] == 0) != (masses[2] == 0)):
            raise ValueError('Family mastery totals disagree with eligible champion counts.')
        if not np.isclose(masses[0], sum(masses[2:]), rtol=1e-12, atol=1e-9) or not np.isclose(
                masses[1], masses[2] + masses[4], rtol=1e-12, atol=1e-9):
            raise ValueError('Family mastery components do not reconcile.')
        for key, mass in [('below_cutoff_mastery_share', masses[3]), ('unmapped_mastery_share', masses[4]),
                          ('scored_mastery_share', masses[2])]:
            if total > 0:
                if _null(row[key]) or not np.isclose(row[key], mass / total, rtol=0, atol=TIE_ATOL):
                    raise ValueError('Family coverage share disagrees with its full-active denominator.')
            elif not _null(row[key]):
                raise ValueError('Zero mastery has no measured coverage shares.')
    if state not in {'primary', 'shared_top'}:
        if row['family_category'] != STATE_LABELS[state]:
            raise ValueError('Unavailable family category disagrees with its evidence state.')
        if ((state == 'no_active_pool' and row['active_pool_champion_count'] != 0)
                or (state == 'insufficient_mastery' and (row['active_pool_champion_count'] == 0
                                                        or row['eligible_pool_champion_count'] != 0))
                or (state == 'unmapped_pool' and (row['eligible_pool_champion_count'] == 0
                                                  or row['scored_pool_champion_count'] != 0))):
            raise ValueError('Family unavailable state disagrees with its eligibility counts.')
        if not _null(vector) or any(not _null(row[key]) for key in ['primary_family_id', 'top_family_score',
                                                                  'runner_up_family_score', 'family_gap']):
            raise ValueError('Unscorable family states require null vector and ranking fields.')
        if len(row['top_family_ids']) or len(row['runner_up_family_ids']):
            raise ValueError('Unscorable family states cannot invent ranking IDs.')
        return
    scores = np.asarray(vector, dtype=float)
    if scores.shape != (len(family_order),) or not np.isfinite(scores).all() or (scores < 0).any() or (scores > 1).any():
        raise ValueError('Family affinity must be a finite bounded vector in the declared order.')
    if scores.max() > row['scored_mastery_share'] + TIE_ATOL:
        raise ValueError('Family affinity exceeds all available mapped mastery.')
    maximum = scores.max()
    top = [family_order[i] for i, value in enumerate(scores) if value > 0 and abs(value - maximum) <= TIE_ATOL]
    if not top or list(row['top_family_ids']) != top or not np.isclose(row['top_family_score'], maximum, rtol=0, atol=TIE_ATOL):
        raise ValueError('Family top IDs/score disagree with its vector.')
    shared = len(top) > 1
    if (state == 'shared_top') != shared or row['family_category'] != ('Shared top' if shared else top[0]):
        raise ValueError('Family category disagrees with the positive maximum/tie rule.')
    if (shared and not _null(row['primary_family_id'])) or (not shared and row['primary_family_id'] != top[0]):
        raise ValueError('Primary family ID disagrees with tie status.')
    runner = maximum if shared else max((value for i, value in enumerate(scores) if family_order[i] != top[0]), default=0)
    runner_ids = [] if shared else [family_order[i] for i, value in enumerate(scores)
                                   if family_order[i] != top[0] and value > 0 and abs(value - runner) <= TIE_ATOL]
    gap = 0 if shared else maximum - runner
    if (list(row['runner_up_family_ids']) != runner_ids
            or not np.isclose(row['runner_up_family_score'], runner, rtol=0, atol=TIE_ATOL)
            or not np.isclose(row['family_gap'], gap, rtol=0, atol=TIE_ATOL)):
        raise ValueError('Family runner-up/gap disagree with its vector.')
