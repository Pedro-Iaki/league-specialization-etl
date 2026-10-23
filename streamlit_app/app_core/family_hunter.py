"""Leiden ensembles, iterative consensus and independently resampled family libraries."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

import igraph as ig
import numpy as np
import pandas as pd

from app_core.families import (
    FamilySettings, _family_graph, _partition_families, pair_statistics, scenario_payload,
    validate_scenario,
)
from app_core.family_cohort import fingerprint, subset_scores
from app_core.population import WEIGHT


def agreement_matrix(partitions: list[np.ndarray]) -> np.ndarray:
    """Unassigned vertices never contribute agreement, including on the diagonal."""
    return np.mean([(p[:, None] == p[None, :]) & (p[:, None] >= 0) for p in partitions], axis=0)


def partition_groups(labels: np.ndarray) -> list[tuple]:
    return [tuple(np.flatnonzero(labels == label).tolist()) for label in sorted(set(labels) - {-1})]


def _signature(labels: np.ndarray) -> tuple:
    return tuple(sorted(partition_groups(labels)))


def build_schedule(step: dict, seed: int) -> list[dict]:
    """Freeze sampled configurations before either discovery or bootstrap evaluation."""
    rng = np.random.default_rng(seed)
    schedule = []
    for _ in range(step['runs']):
        preset = step['presets'][int(rng.integers(len(step['presets'])))]
        values = copy.deepcopy(preset['scenario']['settings'])
        if step.get('resolution_override') is not None:
            values['resolution'] = step['resolution_override']
        spread = step.get('resolution_spread', 0.)
        if spread:
            values['resolution'] = float(np.clip(values['resolution'] * np.exp(rng.uniform(-spread, spread)), .05, 5))
        neighbors = step.get('neighbor_spread', 0)
        if neighbors:
            values['neighbors'] = int(np.clip(values['neighbors'] + rng.integers(-neighbors, neighbors + 1), 1, 172))
        fraction = None
        if step.get('neighbor_mode') == 'fraction':
            fraction = values['neighbors'] / len(preset['scenario']['assignments'])
            variation = step.get('neighbor_fraction_spread', 0.)
            if variation:
                fraction += rng.uniform(-variation, variation)
            fraction = float(np.clip(fraction, 0., 1.))
        values['seed'] = int(rng.integers(2**31))
        draw = {'preset': preset['name'], 'settings': values,
                'excluded': preset['scenario']['source']['excluded_keys']}
        if fraction is not None:
            draw['neighbor_fraction'] = fraction
        schedule.append(draw)
    return schedule


def sweep_graph_settings(draw: dict, character_count: int) -> FamilySettings:
    """Scale a frozen neighbor share to the graph's actual available peers."""
    settings = FamilySettings(**draw['settings'])
    if 'neighbor_fraction' in draw:
        available = max(1, character_count - 1)
        count = int(np.floor(draw['neighbor_fraction'] * available + .5))
        settings = replace(settings, neighbors=max(1, min(available, count)))
    return settings


def consensus_ensemble(points: np.ndarray, weights: np.ndarray, keys: np.ndarray,
                       schedule: list[dict], threshold: float, rounds: int,
                       consensus_resolution: float, seed: int, progress=None) -> dict:
    """Recluster a thresholded co-assignment graph; stop at agreement or the cap."""
    stats_cache, graph_cache, partitions = {}, {}, []
    for index, draw in enumerate(schedule):
        settings = sweep_graph_settings(draw, len(keys))
        if settings.minimum_mastery not in stats_cache:
            stats_cache[settings.minimum_mastery] = pair_statistics(points, weights, settings)
        graph_key = fingerprint([dict(draw['settings'], seed=0, neighbors=settings.neighbors), draw['excluded']])
        if graph_key not in graph_cache:
            graph_cache[graph_key] = _family_graph(stats_cache[settings.minimum_mastery], keys, settings, tuple(draw['excluded']))[:2]
        graph, edge_weights = graph_cache[graph_key]
        partitions.append(_partition_families(graph, edge_weights, keys, settings, settings.seed))
        if progress:
            progress((index + 1) / len(schedule))
    return consensus_partitions(partitions, keys, threshold, rounds, consensus_resolution, seed)


def consensus_partitions(partitions: list[np.ndarray], keys: np.ndarray, threshold: float,
                         rounds: int, consensus_resolution: float, seed: int) -> dict:
    """Shared bounded consensus over already generated partitions."""
    initial = agreement_matrix(partitions)
    harvested = [(p, 'Ensemble') for p in partitions]
    history = []
    run_count = len(partitions)
    consensus_settings = FamilySettings(minimum_family_size=2, resolution=consensus_resolution)
    for iteration in range(rounds):
        if len({_signature(p) for p in partitions}) == 1:
            break
        rates = agreement_matrix(partitions)
        left, right = np.where(np.triu((rates >= threshold) & (rates > 0), 1))
        graph = ig.Graph(n=len(keys), edges=list(zip(left.tolist(), right.tolist())), directed=False)
        edge_weights = rates[left, right].tolist()
        partitions = [_partition_families(graph, edge_weights, keys, consensus_settings,
                                          (seed + iteration * run_count + j) % 2**31)
                      for j in range(run_count)]
        harvested.extend((p, 'Consensus') for p in partitions)
        history.append({'round': iteration + 1, 'distinct_partitions': len({_signature(p) for p in partitions})})
    final_rates = agreement_matrix(partitions)
    # At a capped, nonconverged run retain the actual partition closest to the final ensemble.
    costs = [float(np.mean(np.abs(agreement_matrix([p]) - final_rates))) for p in partitions]
    final = partitions[int(np.argmin(costs))]
    return {'labels': final, 'initial_agreement': initial, 'final_agreement': final_rates,
            'harvested': harvested, 'history': history,
            'converged': len({_signature(p) for p in partitions}) == 1}


def validate_step(step: dict, characters: pd.DataFrame, membership_hash: str) -> None:
    if (not step.get('name', '').strip() or not step.get('presets') or not 2 <= step['runs'] <= 10000
            or not 0 <= step.get('resolution_spread', 0) <= 2
            or not 0 <= step.get('neighbor_spread', 0) <= 171
            or step.get('neighbor_mode', 'absolute') not in {'absolute', 'fraction'}
            or not 0 <= step.get('neighbor_fraction_spread', 0.) <= 1):
        raise ValueError('Each step needs a name, configurations, at least two runs and valid variation ranges.')
    if not step['anchors'] or not set(step['anchors']).issubset(set(characters.character_key)):
        raise ValueError('Each step needs anchor characters from this snapshot.')
    contexts = []
    for preset in step['presets']:
        scenario = preset['scenario']
        validate_scenario(scenario, characters, membership_hash)
        context = scenario['source']
        contexts.append([sorted(context['tiers']), context['maturity'], scenario['settings']['population_weighted']])
    if len({fingerprint(context) for context in contexts}) != 1:
        raise ValueError('Configurations within a step must use the same rank tiers, history filter and weighting. Use separate steps for different audiences.')


def hunt_step(base: pd.DataFrame, characters: pd.DataFrame, points: np.ndarray,
              step: dict, membership_hash: str, seed: int = 42, bootstrap_repeats: int = 20,
              agreement_threshold: float = .5, consensus_rounds: int = 3,
              consensus_resolution: float = 1., progress=None) -> dict:
    """Generate overlapping alternatives, then rerun the frozen pipeline on player resamples."""
    validate_step(step, characters, membership_hash)
    if (not 2 <= bootstrap_repeats <= 10000 or not 0 <= seed < 2**31 or not 0 < agreement_threshold <= 1
            or not 1 <= consensus_rounds <= 20 or not .05 <= consensus_resolution <= 5):
        raise ValueError('Invalid bootstrap, consensus or random-seed controls.')
    scenario = step['presets'][0]['scenario']
    context = scenario['source']
    selected = base.tier.isin(context['tiers']).to_numpy()
    if context['maturity'] != 'All':
        selected &= (base.days_tracked.lt(30) if context['maturity'] == 'Under 30 days' else base.days_tracked.ge(30)).to_numpy()
    if not selected.any():
        raise ValueError('No profiles match this step’s audience.')
    cohort = points[selected]
    weights = base.loc[selected, WEIGHT].to_numpy() if scenario['settings']['population_weighted'] else np.ones(selected.sum())
    keys = characters.character_key.to_numpy(dtype=int)
    schedule = build_schedule(step, seed)
    def run(data, sample_weights, callback=None):
        return consensus_ensemble(data, sample_weights, keys, schedule, agreement_threshold,
                                  consensus_rounds, consensus_resolution, seed, callback)
    discovery = run(cohort, weights, (lambda fraction: progress(.15 * fraction, 'Generating ensemble')) if progress else None)
    harvested = {}
    for labels, origin in discovery['harvested'] + [(discovery['labels'], 'Final consensus')]:
        for group in partition_groups(labels):
            members = tuple(sorted(int(keys[i]) for i in group))
            anchors = sorted(set(members) & set(step['anchors']))
            if not anchors:
                continue
            row = harvested.setdefault(members, {'member_keys': list(members), 'anchors': anchors,
                                                'ensemble_hits': 0, 'origins': set()})
            row['origins'].add(origin)
            row['ensemble_hits'] += origin == 'Ensemble'
    if not harvested:
        raise ValueError('No accepted family contains the selected anchors. Relax support, size or graph filters.')
    rng = np.random.default_rng(seed)
    together = np.zeros((len(keys), len(keys)))
    recovery = {members: [] for members in harvested}
    positions = {int(key): i for i, key in enumerate(keys)}
    bootstrap_converged = 0
    for repeat in range(bootstrap_repeats):
        sample = rng.integers(0, len(cohort), len(cohort))
        result = run(cohort[sample], weights[sample])
        labels = result['labels']
        together += agreement_matrix([labels])
        bootstrap_converged += result['converged']
        groups = [set(group) for group in partition_groups(labels)]
        for members in harvested:
            indices = {positions[key] for key in members}
            recovery[members].append(max((len(indices & group) / len(indices | group) for group in groups), default=0.))
        if progress:
            progress(.15 + .85 * (repeat + 1) / bootstrap_repeats, f'Player bootstrap {repeat + 1}/{bootstrap_repeats}')
    labels = discovery['labels']
    automatic = characters.assign(family=[f'HC{label + 1:03d}' if label >= 0 else 'Unassigned' for label in labels])
    hunter_definition = {'step': step, 'schedule': schedule, 'seed': seed,
                         'bootstrap_repeats': bootstrap_repeats, 'agreement_threshold': agreement_threshold,
                         'consensus_rounds': consensus_rounds, 'consensus_resolution': consensus_resolution}
    titles = {family: {'title': family} for family in set(automatic.family) - {'Unassigned'}}
    saved_scenario = scenario_payload(FamilySettings(**scenario['settings']), copy.deepcopy(context), automatic,
                                      titles, 'Hunter: ensemble alternatives with whole-pipeline player-bootstrap evidence.')
    saved_scenario['hunter'] = hunter_definition
    source = {'name': step['name'], 'scenario': saved_scenario, 'automatic': automatic.to_dict('records'),
              'co_membership': {'character_keys': keys.tolist(), 'rates': (together / bootstrap_repeats).tolist()},
              'repetitions': bootstrap_repeats, 'repeat_seed': seed, 'profiles': int(selected.sum()),
              'evidence_kind': 'Hunter pipeline player bootstrap',
              'ensemble_agreement': {'character_keys': keys.tolist(), 'rates': discovery['initial_agreement'].tolist()},
              'converged': discovery['converged'], 'consensus_history': discovery['history'],
              'bootstrap_converged': bootstrap_converged, 'candidate_families': []}
    for number, (members, row) in enumerate(sorted(harvested.items(), key=lambda item: (len(item[0]), item[0])), 1):
        row['origins'] = sorted(row['origins'])
        values = recovery[members]
        _, mean = subset_scores(source, list(members))
        ix = [positions[key] for key in members]
        agreement = discovery['initial_agreement'][np.ix_(ix, ix)]
        peer_mask = ~np.eye(len(ix), dtype=bool)
        source['candidate_families'].append(dict(row, family=f'HF{number:04d}',
            title=f'{step["name"]} · {len(members)} characters · {number}',
            mean_recovery=float(np.mean(values)), p10_recovery=float(np.quantile(values, .1)),
            exact_recovery=float(np.mean(np.asarray(values) == 1)),
            ensemble_frequency=row['ensemble_hits'] / step['runs'],
            ensemble_agreement=float(agreement[peer_mask].mean()), bootstrap_consistency=mean))
    return source


def library_payload(sources: dict, membership_hash: str, reference_hash: str, name: str,
                    run_status: dict | None = None) -> dict:
    payload = {'schema_version': 1, 'kind': 'Leiden hunter library', 'name': name,
               'membership_sha256': membership_hash, 'reference_sha256': reference_hash,
               'saved_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': sources}
    if run_status is not None:
        payload['run_status'] = run_status
    payload['checksum'] = fingerprint(payload)
    return payload


def validate_library(payload: dict, universe: pd.DataFrame, membership_hash: str, reference_hash: str) -> dict:
    # The cohort validator owns source evidence validation; no discovery is run here.
    from app_core.family_cohort import cohort_payload, new_draft, validate_cohort
    raw = dict(payload)
    checksum = raw.pop('checksum', None)
    if checksum != fingerprint(raw):
        raise ValueError('Hunter library checksum differs.')
    if (raw.get('schema_version') != 1 or raw.get('kind') != 'Leiden hunter library'
            or raw.get('membership_sha256') != membership_hash or raw.get('reference_sha256') != reference_hash):
        raise ValueError('Hunter library uses another snapshot, reference or schema.')
    policy = {'family_target': .8, 'trim_fraction': .2, 'single_threshold': .8,
              'shared_threshold': .4, 'separation_target': .2}
    draft = new_draft(raw['sources'], universe, policy, membership_hash, reference_hash)
    validate_cohort(cohort_payload(draft), universe, membership_hash, reference_hash)
    return raw


def next_library_path(directory: Path, prefix: str) -> Path:
    """Number new libraries in creation order, preserving all existing files."""
    directory.mkdir(parents=True, exist_ok=True)
    numbers = []
    for existing in directory.glob(f'{prefix}-*'):
        suffix = existing.name[len(prefix) + 1:].split('.')[0]
        if suffix.isdecimal():
            numbers.append(int(suffix))
    return directory / f'{prefix}-{max(numbers, default=0) + 1}.json'


def save_library(directory: Path, payload: dict, path: Path | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = path or next_library_path(directory, 'hunter')
    temporary = path.with_suffix('.tmp')
    content = json.dumps(payload, allow_nan=False).encode('utf-8')
    temporary.write_bytes(gzip.compress(content, compresslevel=1) if path.suffix == '.gz' else content)
    os.replace(temporary, path)
    return path


def decode_library(content: bytes) -> dict:
    """Read plain or gzip JSON; callers retain ownership of schema validation."""
    if content.startswith(b'\x1f\x8b'):
        content = gzip.decompress(content)
    return json.loads(content)


def read_library_file(path: Path) -> dict:
    """Hydrate local anchored checkpoints; portable libraries stay ordinary JSON."""
    payload = decode_library(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError('A library or checkpoint must be a JSON object.')
    if payload.get('kind') != 'Leiden hunter checkpoint':
        return payload
    raw = dict(payload)
    checksum = raw.pop('checksum', None)
    if fingerprint(raw) != checksum:
        raise ValueError('Checkpoint index checksum differs.')
    sources = {}
    directory = Path(str(path) + '.sources')
    for source_id, expected_hash in raw.pop('source_files').items():
        if len(source_id) != 64 or any(char not in '0123456789abcdef' for char in source_id):
            raise ValueError('Invalid checkpoint evidence identity.')
        content = (directory / f'{source_id}.json').read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise ValueError('Checkpoint evidence checksum differs.')
        sources[source_id] = json.loads(content)
    raw.update(kind='Leiden hunter library', sources=sources)
    raw['checksum'] = fingerprint(raw)
    return raw
