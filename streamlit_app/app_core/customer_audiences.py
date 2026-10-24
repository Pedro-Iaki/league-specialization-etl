"""Unweighted synthetic customer measures over correctly associated family rows."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app_core.audience_segments import CHARACTER_TYPES, MINIMUM_PLAYERS, RANK_MAP, assign_bands
from app_core.family_affinity import STATE_LABELS


def prepare_customers(frame: pd.DataFrame, reference: dict) -> pd.DataFrame:
    """Read attached current traits; never join anonymous files or recalibrate cash."""
    fields = {'family_category', 'family_state', 'primary_family_id', 'audience_as_of_date', 'audience_region',
              'audience_queue', 'audience_tier', 'audience_main_role', 'audience_lifetime_mastery_points',
              'audience_total_games', 'audience_oldest_retained_play_days', 'scenario_id', 'as_of_date',
              'purchase_window_start', 'purchase_window_end', 'cash_purchase_count_60d', 'cash_spent_usd_60d'}
    if not fields.issubset(frame) or frame.empty or frame.attrs.get('family_affinity') != reference['family_affinity']:
        raise ValueError('The customer view requires a matching family-enriched business snapshot.')
    scenario = frame.attrs.get('business_scenario', {})
    required_scenario = {'scenario_id', 'player_count', 'as_of_date', 'purchase_window_start', 'purchase_window_end',
                         'generator_version', 'generator_seed'}
    if (not required_scenario.issubset(scenario) or set(frame.scenario_id) != {scenario.get('scenario_id')}
            or len(frame) != scenario.get('player_count')):
        raise ValueError('Prepare the complete frozen scenario before applying customer filters.')
    for column in ['as_of_date', 'purchase_window_start', 'purchase_window_end']:
        actual = pd.to_datetime(frame[column], utc=True, errors='coerce')
        if not actual.eq(pd.Timestamp(scenario[column], tz='UTC')).all():
            raise ValueError('Customer dates differ from the frozen scenario metadata.')
    current_dates = pd.to_datetime(frame.audience_as_of_date, utc=True, errors='coerce')
    if (frame.audience_as_of_date.notna() & ~current_dates.eq(pd.Timestamp(reference['as_of_date'], tz='UTC'))).any():
        raise ValueError('Customer audience dates differ from the current segment reference.')
    for column in ['region', 'queue']:
        values = frame[f'audience_{column}']
        if (values.notna() & values.ne(reference['scope'][column])).any():
            raise ValueError('Customer audience scope differs from the current segment reference.')
    current = frame[[f'audience_{spec["source"]}' for spec in reference['bands'].values()]].rename(
        columns=lambda name: name.removeprefix('audience_'))
    bands = assign_bands(current, reference)
    result = frame.copy()
    for column in reference['bands']:
        result[column] = bands[column]
    result['rank_group'] = frame.audience_tier.map(RANK_MAP).fillna('Unrecognized')
    result['character_type'] = frame.audience_main_role.map(CHARACTER_TYPES).fillna('Unavailable')
    amounts = pd.to_numeric(frame.cash_spent_usd_60d, errors='coerce') * 100
    counts = pd.to_numeric(frame.cash_purchase_count_60d, errors='coerce')
    if (not np.isfinite(amounts).all() or amounts.lt(0).any()
            or not np.allclose(amounts, np.rint(amounts), rtol=0, atol=1e-6)
            or not np.isfinite(counts).all() or counts.lt(0).any() or counts.ne(np.floor(counts)).any()
            or (counts.eq(0) & amounts.ne(0)).any()):
        raise ValueError('Cash measures need nonnegative cent amounts, integer event counts and zero cash for nonbuyers.')
    result['cash_cents'] = np.rint(amounts).astype('int64')
    result['cash_buyer'] = counts.gt(0)
    return result


def customer_summary(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Cash is summed once in integer cents; no gameplay weights enter any measure."""
    result = frame.groupby(groups, dropna=False, observed=True).agg(
        profiles=('cash_buyer', 'size'), cash_purchasers=('cash_buyer', 'sum'), cash_cents=('cash_cents', 'sum'),
    ).reset_index()
    result['cash_usd'] = result.cash_cents / 100
    result['purchaser_share'] = result.cash_purchasers / result.profiles
    result['cash_per_purchaser'] = result.cash_usd / result.cash_purchasers.where(result.cash_purchasers.gt(0))
    result['audience_share'] = result.profiles / result.profiles.sum() if len(result) else np.nan
    cash_total = result.cash_cents.sum()
    result['cash_share'] = result.cash_cents / cash_total if cash_total else np.nan
    result['purchaser_estimate'] = result.purchaser_share.where(result.profiles.ge(MINIMUM_PLAYERS))
    result['cash_per_purchaser_estimate'] = result.cash_per_purchaser.where(
        result.profiles.ge(MINIMUM_PLAYERS) & result.cash_purchasers.ge(MINIMUM_PLAYERS))
    result['audience_estimate'] = result.audience_share.where(result.profiles.ge(MINIMUM_PLAYERS))
    result['cash_share_estimate'] = result.cash_share.where(result.profiles.ge(MINIMUM_PLAYERS))
    return result


def family_customer_summary(frame: pd.DataFrame, family_ids: list[str], top_ids: list[str] | None = None) -> pd.DataFrame:
    """Exclusive primary labels and non-family states partition customer rows exactly."""
    if not frame.family_category.isin([*family_ids, *STATE_LABELS.values()]).all():
        raise ValueError('Customer family categories differ from the adopted definition.')
    data = frame
    if top_ids is not None:
        data = frame.assign(family_category=frame.family_category.where(
            ~frame.family_category.isin(set(family_ids) - set(top_ids)), 'Other families'))
    return customer_summary(data, ['family_category'])
