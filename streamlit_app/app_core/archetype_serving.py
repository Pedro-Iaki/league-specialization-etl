"""Frozen pool-archetype inference and anonymous serving contract (NumPy only).

This representation includes every active champion, without the story family's
15k cutoff. Zero-total nonempty pools use equal weights, as in the reviewed lab.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app_core.family_affinity import load_family_definition

MODEL_PATH = Path(__file__).resolve().parents[1] / 'definitions/player-pool-archetypes-v1.json'
IDS = tuple(f'A{i}' for i in range(1, 9))
NAMES = ('Bruisers And Tanks', 'Mages And Enchanters', 'ADCs', 'Assassins And Duelists',
         'Front-Line Disablers', 'Control Mages', 'Burst Mages', 'Aggressive Junglers')
FEATURE_ID = 'active_pool_all_lifetime_mastery_coverage_equal_zero_fallback_v1'
COLUMNS = ('archetype_model_id', 'archetype_state', 'archetype_pool_size', 'archetype_loadings',
           'archetype_best_ids', 'archetype_strength', 'archetype_runner_up_ids', 'archetype_gap',
           'archetype_active_ids', 'archetype_kind', 'archetype_primary_id')
STATES = {'scored', 'empty_pool', 'below_minimum_pool', 'uncovered_pool', 'unavailable_pool'}


def load_model(path: Path = MODEL_PATH) -> dict:
    model = json.loads(path.read_text(encoding='utf8'))
    definition = load_family_definition()
    h, weights = np.asarray(model['profiles']), np.asarray(model['family_weights'])
    if (model['model_id'] != 'player-pool-archetypes-v1' or model['feature_id'] != FEATURE_ID
            or model['family_sha256'] != definition.sha256
            or model['family_order'] != list(definition.family_order)
            or model['ids'] != list(IDS) or model['names'] != list(NAMES)
            or h.shape != (8, 25) or weights.shape != (25,)
            or not np.isfinite(h).all() or not np.isfinite(weights).all()
            or (h < 0).any() or (weights <= 0).any() or (h.sum(axis=1) <= 0).any()
            or model['minimum_pool'] != 4 or model['threshold'] != .2):
        raise ValueError('Incompatible archetype definition, features or numeric model.')
    return model


def model_metadata(model: dict) -> dict:
    encoded = json.dumps(model, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'model_id': model['model_id'], 'sha256': hashlib.sha256(encoded).hexdigest(),
            'feature_id': FEATURE_ID, 'ids': list(IDS), 'names': list(NAMES),
            'threshold': model['threshold'], 'minimum_pool': model['minimum_pool']}


def pool_features(members, definition) -> tuple[np.ndarray, str, int | None]:
    if members is None:
        return np.zeros(25), 'unavailable_pool', None
    members = list(members)
    vector = np.zeros(len(definition.family_order))
    if not members:
        return vector, 'empty_pool', 0
    keys = [int(m['key']) for m in members]
    points = np.asarray([float(m['points']) for m in members])
    if len(set(keys)) != len(keys) or not np.isfinite(points).all() or (points < 0).any():
        raise ValueError('Invalid active membership for archetype inference.')
    shares = points / points.sum() if points.sum() else np.full(len(points), 1 / len(points))
    for key, share in zip(keys, shares):
        for index in definition.champion_families.get(key, ()):
            vector[index] += share
    state = 'below_minimum_pool' if len(keys) < 4 else ('scored' if vector.sum() else 'uncovered_pool')
    return vector, state, len(keys)


def infer_loadings(matrix: np.ndarray, model: dict) -> np.ndarray:
    """Fixed-profile KL multiplicative updates; each row stops independently.

    Cohort-independent initialization/stopping makes subset and business exports
    identical. No fitting, feature reweighting or randomized initialization occurs.
    """
    x = np.asarray(matrix, dtype=float) * np.asarray(model['family_weights'])
    h = np.asarray(model['profiles']) * np.asarray(model['family_weights'])
    if x.ndim != 2 or x.shape[1] != 25 or not np.isfinite(x).all() or (x < 0).any():
        raise ValueError('Invalid archetype feature matrix.')
    w = np.repeat((x.sum(axis=1) / h.sum())[:, None], 8, axis=1)
    active = np.ones(len(x), dtype=bool)
    for _ in range(model['inference']['max_iter']):
        old = w[active].copy()
        if not len(old):
            break
        new = old * ((x[active] / np.maximum(old @ h, 1e-15)) @ h.T) / h.sum(axis=1)
        w[active] = new
        done = np.max(np.abs(new - old), axis=1) <= model['inference']['atol']
        active[np.flatnonzero(active)[done]] = False
    if active.any():
        raise ValueError(f'Archetype inference did not converge for {active.sum()} rows.')
    return w


def describe_loadings(values, model: dict) -> dict:
    values = np.asarray(values, dtype=float)
    best = np.flatnonzero(np.isclose(values, values.max(), rtol=0, atol=1e-12))
    rest = np.flatnonzero((values < values.max() - 1e-12) & (values > 0))
    runner = rest[np.isclose(values[rest], values[rest].max(), rtol=0, atol=1e-12)] if len(rest) else []
    expressed = [IDS[i] for i in np.flatnonzero(values >= model['threshold'])]
    kind = 'Diffuse' if not expressed else ('Single' if len(expressed) == 1 else 'Blend')
    return {'archetype_loadings': values.tolist(), 'archetype_best_ids': [IDS[i] for i in best],
                'archetype_strength': float(values.max()), 'archetype_runner_up_ids': [IDS[i] for i in runner],
                'archetype_gap': 0. if len(best) > 1 else float(values.max() - (values[runner[0]] if len(runner) else 0)),
                'archetype_active_ids': expressed, 'archetype_kind': kind,
                'archetype_primary_id': IDS[best[0]] if len(best) == 1 and kind != 'Diffuse' else None}


def score_pools(pools, model: dict) -> pd.DataFrame:
    definition = load_family_definition()
    features = [pool_features(pool, definition) for pool in pools]
    rows = []
    eligible = [i for i, (_, state, _) in enumerate(features) if state == 'scored']
    inferred = infer_loadings(np.array([features[i][0] for i in eligible]).reshape(-1, 25), model)
    scores = dict(zip(eligible, inferred))
    for i, (_, state, count) in enumerate(features):
        row = dict.fromkeys(COLUMNS)
        row.update(archetype_model_id=model['model_id'], archetype_state=state, archetype_pool_size=count,
                   archetype_best_ids=[], archetype_runner_up_ids=[], archetype_active_ids=[])
        if i in scores:
            row.update(describe_loadings(scores[i], model))
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)


def validate_archetypes(frame: pd.DataFrame, metadata: dict, model: dict | None = None) -> None:
    model = load_model() if model is None else model
    if metadata != model_metadata(model) or not set(COLUMNS).issubset(frame):
        raise ValueError('Archetype serving metadata/schema differs from frozen model.')
    for row in frame.loc[:, list(COLUMNS)].to_dict('records'):
        if row['archetype_state'] not in STATES or row['archetype_model_id'] != model['model_id']:
            raise ValueError('Invalid archetype state/model.')
        if row['archetype_state'] == 'scored':
            values = np.asarray(row['archetype_loadings'], dtype=float)
            if values.shape != (8,) or not np.isfinite(values).all() or (values < 0).any() or row['archetype_pool_size'] < 4:
                raise ValueError('Invalid archetype loadings/pool.')
            for key, expected in describe_loadings(values, model).items():
                actual = row[key]
                if isinstance(expected, list):
                    if list(actual) != expected:
                        raise ValueError(f'Archetype derived field differs: {key}')
                elif not (expected is None and pd.isna(actual)) and actual != expected:
                    raise ValueError(f'Archetype derived field differs: {key}')
        else:
            if row['archetype_loadings'] is not None and (not np.isscalar(row['archetype_loadings']) or pd.notna(row['archetype_loadings'])):
                raise ValueError('Unscored archetype must have null loadings.')
            if (any(len(row[key]) for key in ['archetype_best_ids','archetype_runner_up_ids','archetype_active_ids'])
                    or any(pd.notna(row[key]) for key in ['archetype_kind','archetype_primary_id','archetype_strength','archetype_gap'])):
                raise ValueError('Unscored archetype cannot have an assignment.')
            count = row['archetype_pool_size']
            state = row['archetype_state']
            if ((state == 'empty_pool' and count != 0)
                    or (state == 'below_minimum_pool' and not 0 < count < 4)
                    or (state == 'uncovered_pool' and count < 4)
                    or (state == 'unavailable_pool' and pd.notna(count))):
                raise ValueError('Archetype eligibility disagrees with pool size.')


def select_archetype(frame: pd.DataFrame, archetype: str, mode: str = 'primary') -> pd.Series:
    """Primary excludes weak/tied maxima; expressed includes every threshold-passing mixture member."""
    if archetype not in IDS or mode not in {'primary', 'expressed', 'best_match'}:
        raise ValueError('Unknown archetype selection.')
    if not set(COLUMNS).issubset(frame):
        return pd.Series(False, index=frame.index)
    if mode == 'primary':
        return frame.archetype_primary_id.eq(archetype)
    column = 'archetype_active_ids' if mode == 'expressed' else 'archetype_best_ids'
    return frame[column].map(lambda ids: archetype in ids)


def coverage(frame: pd.DataFrame, weight: str | None = None) -> pd.DataFrame:
    """Retain full input denominator; pass population_weight for behavioral reporting only."""
    if 'archetype_state' not in frame:
        return pd.DataFrame([{'state': 'unavailable_snapshot', 'profiles': len(frame), 'share': 1.}])
    weights = pd.Series(1., index=frame.index) if weight is None else frame[weight]
    result = pd.DataFrame({'state': frame.archetype_state, 'weight': weights})
    grouped = result.groupby('state').agg(profiles=('state', 'size'), mass=('weight', 'sum')).reset_index()
    grouped['share'] = grouped.mass / weights.sum() if weights.sum() else np.nan
    return grouped
