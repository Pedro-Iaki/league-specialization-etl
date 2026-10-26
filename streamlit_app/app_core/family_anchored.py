"""Independent character-centered Leiden searches and resumable local evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from collections import OrderedDict
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from app_core.families import FamilySettings, _family_graph, _partition_families, pair_statistics, scenario_payload
from app_core.family_cohort import fingerprint, subset_scores
from app_core.family_hunter import build_schedule, consensus_partitions, library_payload, next_library_path, save_library, sweep_graph_settings, validate_library, validate_step
from app_core.population import WEIGHT

METHOD_VERSION = 1
RELATION_FIELDS = ('minimum_mastery', 'minimum_players', 'minimum_shared', 'minimum_similarity',
                   'association', 'population_weighted')


def stable_seed(root: int, *parts) -> int:
    return int(fingerprint([METHOD_VERSION, root, *parts])[:16], 16) % 2**31


def relationship_policy(step: dict) -> dict:
    scenario = step['presets'][0]['scenario']
    source = scenario['source']
    return {'settings': {field: scenario['settings'][field] for field in RELATION_FIELDS},
            'tiers': sorted(source['tiers']), 'maturity': source['maturity'],
            'excluded': sorted(source['excluded_keys'])}


def validate_anchored_step(step: dict, characters: pd.DataFrame, membership_hash: str) -> None:
    validate_step(step, characters, membership_hash)
    if not isinstance(step.get('id'), str) or not step['id'].strip():
        raise ValueError('Each anchored step needs a stable ID.')
    if not isinstance(step.get('candidate_neighbors'), int) or not 1 <= step['candidate_neighbors'] <= 172:
        raise ValueError('Use 1–172 candidate neighbors, excluding the anchor.')
    if not 0 <= step.get('second_degree_fraction', 0.) <= .5 or not 2 <= step.get('core_connections', 2) <= 6:
        raise ValueError('Use an expansion fraction from 0 to 50% and 2–6 core connections.')
    if step.get('resolution_override') is not None and not .05 <= step['resolution_override'] <= 5:
        raise ValueError('Local discovery resolution must be between 0.05 and 5.')
    expected = relationship_policy(step)
    for preset in step['presets'][1:]:
        if relationship_policy(dict(step, presets=[preset])) != expected:
            raise ValueError('Anchored configurations within a step must share mastery, support, association, weighting, audience and exclusions. Put different relationship policies in separate steps.')


def eligible_network(stats: dict, keys: np.ndarray, settings: FamilySettings, excluded: list) -> tuple[np.ndarray, np.ndarray]:
    supported = (np.diag(stats['raw']) >= settings.minimum_players) & ~np.isin(keys, excluded)
    scores = stats['jaccard'] if settings.association == 'jaccard' else stats['adjusted']
    valid = ((stats['raw'] >= settings.minimum_shared) & (stats['jaccard'] >= settings.minimum_similarity)
             & (scores > 0) & supported[:, None] & supported[None, :])
    np.fill_diagonal(valid, False)
    return np.where(valid, scores, 0.), supported


def candidate_neighborhood(stats: dict, keys: np.ndarray, settings: FamilySettings,
                           excluded: list, anchor: int, budget: int,
                           second_fraction: float = 0., core_connections: int = 2) -> dict:
    """Rank before top-K sparsification; two-hop expansion never recurses."""
    positions = {int(key): i for i, key in enumerate(keys)}
    if anchor not in positions:
        raise ValueError('Anchor is absent from this character catalog.')
    center = positions[anchor]
    network, supported = eligible_network(stats, keys, settings, excluded)
    ranked = lambda values, scores: sorted(values, key=lambda i: (-float(scores[i]), int(keys[i])))
    direct = ranked(np.flatnonzero(network[center] > 0).tolist(), network[center])
    if not supported[center]:
        status = 'Unsupported / excluded'
    elif not direct:
        status = 'Isolated'
    else:
        status = 'Ready'
    core = [center] + direct[:5]
    links = (network[:, core] > 0).sum(axis=1)
    core_scores = network[:, core].mean(axis=1)
    second = [i for i in range(len(keys)) if supported[i] and i != center
              and i not in direct and links[i] >= core_connections]
    second.sort(key=lambda i: (-float(core_scores[i]), -float(stats['jaccard'][center, i]), int(keys[i])))
    allowance = min(int(np.floor(budget * second_fraction)), max(0, budget - min(5, len(direct))))
    chosen_second = second[:allowance] if status == 'Ready' else []
    chosen_direct = direct[:budget - len(chosen_second)] if status == 'Ready' else []
    selected = [center] + chosen_direct + chosen_second
    raw_scores = stats['jaccard'] if settings.association == 'jaccard' else stats['adjusted']
    rows = []
    direct_positions = {i: rank + 1 for rank, i in enumerate(direct)}
    for i, key in enumerate(keys):
        if i == center:
            route = 'Anchor'
        elif i in chosen_direct:
            route = 'First degree'
        elif i in chosen_second:
            route = 'Second degree'
        elif not supported[i]:
            route = 'Below support / excluded'
        elif i in direct or i in second:
            route = 'Outside search window'
        else:
            route = 'No eligible path'
        rows.append({'character_key': int(key), 'included': i in selected, 'route': route,
                     'direct_rank': direct_positions.get(i), 'anchor_strength': float(raw_scores[center, i]),
                     'core_strength': float(core_scores[i]), 'core_connections': int(links[i]),
                     'supporting_core': [int(keys[j]) for j in core if network[i, j] > 0]})
    return {'indices': selected, 'rows': rows, 'status': status, 'direct_available': len(direct),
            'core_keys': [int(keys[i]) for i in core], 'budget': budget}


class PairStatisticsPool:
    """Request-owned bounded aggregate cache; independent searches keep independent seeds."""
    def __init__(self, base: pd.DataFrame, points: np.ndarray, root_seed: int, max_entries: int = 96):
        self.base, self.points, self.root_seed = base, points, root_seed
        self.cache = OrderedDict()
        self.max_entries = max_entries
        self.computations = 0

    def get(self, step: dict, repeat: int) -> tuple[dict, int]:
        policy = relationship_policy(step)
        identity = fingerprint([policy, repeat])
        if identity not in self.cache:
            selected = self.base.tier.isin(policy['tiers']).to_numpy()
            if policy['maturity'] != 'All':
                selected &= (self.base.days_tracked.lt(30) if policy['maturity'] == 'Under 30 days' else self.base.days_tracked.ge(30)).to_numpy()
            indices = np.flatnonzero(selected)
            if not len(indices):
                raise ValueError('No profiles match this step’s audience.')
            count = len(indices)
            if repeat >= 0:
                rng = np.random.default_rng(stable_seed(self.root_seed, 'player-sample', policy, repeat))
                indices = indices[rng.integers(0, count, count)]
            weights = (self.base.iloc[indices][WEIGHT].to_numpy() if policy['settings']['population_weighted']
                       else np.ones(count))
            settings = FamilySettings(**step['presets'][0]['scenario']['settings'])
            raw = pair_statistics(self.points[indices], weights, settings)
            self.cache[identity] = ({field: raw[field] for field in ['raw', 'jaccard', 'adjusted']}, count)
            self.computations += 1
            if len(self.cache) > self.max_entries:
                self.cache.popitem(last=False)
        self.cache.move_to_end(identity)
        return self.cache[identity]


def local_ensemble(stats: dict, keys: np.ndarray, step: dict, anchor: int, schedule: list[dict],
                   threshold: float, rounds: int, resolution: float, seed: int) -> dict:
    settings = FamilySettings(**step['presets'][0]['scenario']['settings'])
    window = candidate_neighborhood(stats, keys, settings, step['presets'][0]['scenario']['source']['excluded_keys'],
                                    anchor, step['candidate_neighbors'], step.get('second_degree_fraction', 0.),
                                    step.get('core_connections', 2))
    indices = window['indices']
    local_keys = keys[indices]
    local_stats = {field: values[np.ix_(indices, indices)] for field, values in stats.items()}
    partitions, graphs = [], {}
    for draw in schedule:
        graph_settings = sweep_graph_settings(draw, len(local_keys))
        identity = fingerprint([dict(draw['settings'], seed=0, neighbors=graph_settings.neighbors), draw['excluded']])
        if identity not in graphs:
            graphs[identity] = _family_graph(local_stats, local_keys, graph_settings, tuple(draw['excluded']))[:2]
        graph, weights = graphs[identity]
        partitions.append(_partition_families(graph, weights, local_keys, graph_settings, draw['settings']['seed']))
    consensus = consensus_partitions(partitions, local_keys, threshold, rounds, resolution, seed)
    return dict(consensus, window=window, keys=local_keys)


def anchor_members(result: dict, labels: np.ndarray | None = None) -> set:
    labels = result['labels'] if labels is None else labels
    label = labels[0]  # the anchor is always the first local vertex
    return set(result['keys'][labels == label].astype(int).tolist()) if label >= 0 else set()


def boundary_retention(stats: dict, keys: np.ndarray, settings: FamilySettings, excluded: list, members: list):
    network, _ = eligible_network(stats, keys, settings, excluded)
    indices = np.flatnonzero(np.isin(keys, members))
    total = network[indices].sum()
    return float(network[np.ix_(indices, indices)].sum() / total) if total else None


def hunt_anchor(pool: PairStatisticsPool, characters: pd.DataFrame, step: dict, anchor: int,
                root_seed: int, repeats: int, threshold: float, rounds: int, resolution: float,
                progress=None) -> dict:
    """One independent character-step job. Pair scores can be reused, partition draws cannot."""
    seed = stable_seed(root_seed, 'search', step['id'], anchor)
    schedule = build_schedule(step, seed)
    keys = characters.character_key.to_numpy(dtype=int)
    stats, profiles = pool.get(step, -1)
    discovery = local_ensemble(stats, keys, step, anchor, schedule, threshold, rounds, resolution, seed)
    if discovery['window']['status'] != 'Ready':
        return {'status': discovery['window']['status'], 'source': None}
    alternatives = {}
    for labels, origin in discovery['harvested'] + [(discovery['labels'], 'Final consensus')]:
        members = tuple(sorted(anchor_members(discovery, labels)))
        if len(members) < 2:
            continue
        row = alternatives.setdefault(members, {'ensemble_hits': 0, 'origins': set()})
        row['ensemble_hits'] += origin == 'Ensemble'
        row['origins'].add(origin)
    if not alternatives:
        return {'status': 'No accepted family', 'source': None}
    counts = np.zeros((len(keys), len(keys)))
    eligibility = np.zeros(len(keys))
    positions = {int(key): i for i, key in enumerate(keys)}
    evaluated = set(discovery['keys'].astype(int).tolist())
    recoveries = {members: [] for members in alternatives}
    converged = 0
    for repeat in range(repeats):
        sample_stats, _ = pool.get(step, repeat)
        result = local_ensemble(sample_stats, keys, step, anchor, schedule, threshold, rounds, resolution, seed)
        eligible_keys = result['keys'].astype(int).tolist()
        evaluated.update(eligible_keys)
        eligibility[[positions[key] for key in eligible_keys]] += 1
        members = anchor_members(result)
        member_indices = [positions[key] for key in members]
        counts[np.ix_(member_indices, member_indices)] += 1
        for original in alternatives:
            recoveries[original].append(len(set(original) & members) / len(set(original) | members) if members else 0.)
        converged += result['converged']
        if progress:
            progress((repeat + 1) / repeats)
    evaluated_keys = sorted(evaluated)
    ix = [positions[key] for key in evaluated_keys]
    baseline_members = anchor_members(discovery)
    automatic = characters.assign(family=['AC01' if int(key) in baseline_members else 'Unassigned' for key in keys])
    scenario = step['presets'][0]['scenario']
    saved = scenario_payload(FamilySettings(**scenario['settings']), copy.deepcopy(scenario['source']), automatic,
        {'AC01': {'title': step['name']}}, 'Independent anchored Leiden search; recovery is anchor-specific.')
    saved['anchored'] = {'method_version': METHOD_VERSION, 'anchor': anchor, 'step': copy.deepcopy(step),
                         'schedule': schedule, 'root_seed': root_seed, 'seed': seed, 'repeats': repeats,
                         'threshold': threshold, 'rounds': rounds, 'consensus_resolution': resolution}
    names = dict(zip(characters.character_key, characters.character))
    source = {'name': f'{names[anchor]} · {step["name"]} · {step["candidate_neighbors"]} neighbors',
              'scenario': saved, 'automatic': automatic.to_dict('records'),
              'method': 'anchored_leiden', 'method_version': METHOD_VERSION, 'anchor': anchor,
              'candidate_neighbors': step['candidate_neighbors'], 'evaluated_keys': evaluated_keys,
              'co_membership': {'character_keys': evaluated_keys, 'rates': (counts[np.ix_(ix, ix)] / repeats).tolist()},
              'neighborhood_eligibility': {str(key): float(eligibility[positions[key]] / repeats) for key in evaluated_keys},
              'window': discovery['window'], 'repetitions': repeats, 'repeat_seed': seed, 'profiles': profiles,
              'evidence_kind': 'Hunter pipeline player bootstrap', 'converged': discovery['converged'],
              'bootstrap_converged': converged, 'consensus_history': discovery['history'], 'candidate_families': []}
    local_positions = {int(key): i for i, key in enumerate(discovery['keys'])}
    for number, (members, row) in enumerate(sorted(alternatives.items(), key=lambda item: (len(item[0]), item[0])), 1):
        values = np.asarray(recoveries[members])
        fits, mean = subset_scores(source, list(members))
        selection = [local_positions[key] for key in members]
        rates = discovery['initial_agreement'][np.ix_(selection, selection)]
        source['candidate_families'].append({
            'family': f'AF{number:04d}', 'title': f'{names[anchor]} · {step["name"]} · {len(members)} characters · {number}',
            'member_keys': list(members), 'anchors': [anchor], 'origins': sorted(row['origins']),
            'ensemble_frequency': row['ensemble_hits'] / step['runs'],
            'ensemble_agreement': float(rates[~np.eye(len(members), dtype=bool)].mean()),
            'mean_recovery': float(values.mean()), 'median_recovery': float(np.median(values)),
            'p10_recovery': float(np.quantile(values, .1)), 'exact_recovery': float((values == 1).mean()),
            'bootstrap_consistency': mean, 'anchor_fit': float(fits.loc[fits.character_key.eq(anchor), 'member_fit'].iloc[0]),
            'boundary_retention': boundary_retention(stats, keys, FamilySettings(**scenario['settings']),
                                                     scenario['source']['excluded_keys'], list(members))})
    return {'status': 'Completed', 'source': source}


def sweep_request(steps: list[dict], membership_hash: str, reference_hash: str,
                   root_seed: int, repeats: int, threshold: float, rounds: int, resolution: float) -> dict:
    if (not 0 <= root_seed < 2**31 or not 2 <= repeats <= 10000 or not 0 < threshold <= 1
            or not 1 <= rounds <= 20 or not .05 <= resolution <= 5):
        raise ValueError('Invalid sweep seed, repeat count or consensus controls.')
    if len({step['id'] for step in steps}) != len(steps) or not steps:
        raise ValueError('Use nonempty steps with distinct stable IDs.')
    return {'method': 'anchored_leiden', 'method_version': METHOD_VERSION,
            'membership_sha256': membership_hash, 'reference_sha256': reference_hash,
            'software': {name: version(name) for name in ['leidenalg', 'igraph', 'numpy', 'pandas']},
            'steps': sorted([dict(step, anchors=sorted(set(step['anchors']))) for step in steps], key=lambda step: step['id']),
            'root_seed': root_seed, 'repeats': repeats, 'threshold': threshold, 'rounds': rounds, 'resolution': resolution}


def validate_resume(payload: dict, request: dict, characters: pd.DataFrame) -> dict:
    validated = validate_library(payload, characters, request['membership_sha256'], request['reference_sha256'])
    if validated.get('request_fingerprint') != fingerprint(request) or validated.get('request') != request:
        raise ValueError('Checkpoint differs from this request, software or method version. Start a new sweep.')
    expected = {f'{step["id"]}:{key}' for step in request['steps'] for key in step['anchors']}
    jobs = validated.get('jobs', {})
    if set(jobs) != expected:
        raise ValueError('Checkpoint job index does not match the requested character-step jobs.')
    for job in jobs.values():
        if job['status'] not in {'Pending', 'Failed', 'Completed', 'Unsupported / excluded', 'Isolated', 'No accepted family'}:
            raise ValueError('Checkpoint job status is invalid.')
        if job['status'] == 'Completed' and job.get('source_id') not in validated['sources']:
            raise ValueError('Completed checkpoint job lacks its evidence.')
        if job['status'] == 'Completed':
            source = validated['sources'][job['source_id']]
            if source['anchor'] != job['anchor'] or source['scenario']['anchored']['step']['id'] != job['step_id']:
                raise ValueError('Checkpoint job points to another anchor or step’s evidence.')
    return validated


def run_anchored_sweep(base: pd.DataFrame, characters: pd.DataFrame, points: np.ndarray,
                       request: dict, name: str, directory: Path, checkpoint: dict | None = None,
                       checkpoint_path: Path | None = None, progress=None) -> tuple[dict, Path]:
    """Checkpoint each completed character-step, retry failed work on an explicit resume."""
    for step in request['steps']:
        validate_anchored_step(step, characters, request['membership_sha256'])
    if checkpoint is not None:
        prior = validate_resume(checkpoint, request, characters)
        sources, jobs = copy.deepcopy(prior['sources']), copy.deepcopy(prior['jobs'])
    else:
        sources = {}
        jobs = {f'{step["id"]}:{anchor}': {'anchor': anchor, 'step_id': step['id'], 'step': step['name'], 'status': 'Pending'}
                for step in request['steps'] for anchor in step['anchors']}
    pool = PairStatisticsPool(base, points, request['root_seed'])
    started = time.perf_counter()
    terminal = {'Completed', 'Unsupported / excluded', 'Isolated', 'No accepted family'}
    checkpoint_path = checkpoint_path or next_library_path(directory, 'anchored')
    source_files = {}
    def metadata():
        completed = sum(job['status'] in terminal for job in jobs.values())
        errors = [{'job': key, 'error': job['error']} for key, job in jobs.items() if job['status'] == 'Failed']
        result = library_payload({}, request['membership_sha256'], request['reference_sha256'], name,
            {'requested_steps': len(jobs), 'finished_steps': completed, 'complete': completed == len(jobs), 'errors': errors})
        result.pop('checksum')
        result.update(request=request, request_fingerprint=fingerprint(request), jobs=jobs,
                      method='anchored_leiden', pair_computations=pool.computations,
                      elapsed_seconds=time.perf_counter() - started)
        return result
    def persist():
        # Evidence is immutable: write each completed job once, then atomically advance its index.
        evidence_dir = Path(str(checkpoint_path) + '.sources')
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for source_id, source in sources.items():
            if source_id in source_files:
                continue
            content = json.dumps(source, allow_nan=False).encode('utf-8')
            destination = evidence_dir / f'{source_id}.json'
            temporary = destination.with_suffix('.tmp')
            temporary.write_bytes(content)
            os.replace(temporary, destination)
            source_files[source_id] = hashlib.sha256(content).hexdigest()
        index = metadata()
        index.update(kind='Leiden hunter checkpoint', source_files=source_files)
        index['checksum'] = fingerprint(index)
        save_library(directory, index, checkpoint_path)
    # A pending job index survives interruption before the first result as well.
    persist()
    for step in request['steps']:
        for anchor in step['anchors']:
            job_id = f'{step["id"]}:{anchor}'
            if jobs[job_id]['status'] in terminal:
                continue
            job = jobs[job_id]
            def report(fraction):
                if progress:
                    done = sum(row['status'] in terminal or row['status'] == 'Failed' for row in jobs.values())
                    progress((done + fraction) / len(jobs), job)
            job.pop('error', None)
            job['status'] = 'Pending'
            report(0.)
            try:
                result = hunt_anchor(pool, characters, step, anchor, request['root_seed'], request['repeats'],
                                     request['threshold'], request['rounds'], request['resolution'], report)
                job['status'] = result['status']
                if result['source'] is not None:
                    source = result['source']
                    source_id = fingerprint(source['scenario'])
                    sources[source_id] = source
                    job['source_id'] = source_id
            except (ValueError, KeyError, TypeError) as error:
                job.update(status='Failed', error=str(error))
            persist()
            report(0.)
    result = metadata()
    result['sources'] = sources
    result['checksum'] = fingerprint(result)
    return result, checkpoint_path
