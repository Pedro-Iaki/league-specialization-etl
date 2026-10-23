"""Resumable local experiments over frozen hunter libraries; never runs discovery."""
from __future__ import annotations

import copy
import gzip
import hashlib
import itertools
import json
import logging
import math
import os
import platform
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from app_core.family_cohort import (
    cohort_payload, fingerprint, new_draft, overlap_table, prepare_library_candidates,
    suggest_from_library, summarize_cohort, validate_cohort, cohort_scoring_policy,
)
from app_core.family_cover import LEGACY_OBJECTIVE, SCORE_OBJECTIVE, compare_cover_quality, SCORE_ABS_TOL, SCORE_REL_TOL
from app_core.family_hunter import decode_library, read_library_file, validate_library


ROOT = Path(__file__).resolve().parents[2]
LOG = logging.getLogger(__name__)
DEFAULT_POLICY = dict(
    family_target=.75, trim_fraction=.4, single_threshold=.65, shared_threshold=.35,
    separation_target=.2, minimum_family_size=5, maximum_family_size=28,
    cover_basis='Full + retained', ideal_minimum=9, ideal_maximum=16, size_preference=.3,
    max_family_cost=3., max_cost_per_character=None, overlap_penalty=0.,
    selection_approach='Compact audience cover', coverage_target=.85,
    minimum_exclusive_share=.4, solve_time_limit=120.,
    compact_objective=LEGACY_OBJECTIVE,
)
PREP_FIELDS = ('family_target', 'trim_fraction', 'single_threshold', 'shared_threshold',
               'separation_target', 'minimum_family_size', 'maximum_family_size')
LIBRARY_ONLY = {'selection_approach', 'coverage_target', 'minimum_exclusive_share',
                'solve_time_limit', 'overlap_penalty', 'compact_objective'}
TERMINAL_JOBS = {'Completed', 'Unsupported / excluded', 'Isolated', 'No accepted family'}


def run_experiments(spec: dict, root: Path = ROOT):
    """Wait, pin inputs, resume verified artifacts, then execute main and follow-up runs."""
    spec = validate_spec(spec)
    output = resolve(root, spec['output'])
    output.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        manifest_path = output / 'manifest.json'
        identity = fingerprint(spec)
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
            'schema_version': 1, 'spec': spec, 'spec_sha256': identity, 'created_at_utc': utc_now(),
        }
        if manifest['spec_sha256'] != identity:
            raise ValueError('Output belongs to another specification. Use a new output directory.')
        implementation = implementation_identity()
        if manifest.get('implementation', implementation) != implementation:
            raise ValueError('Helpers or dependency versions changed. Use a new output directory.')
        manifest['implementation'] = implementation
        manifest.setdefault('wait_started_at_utc', utc_now())
        atomic_json(manifest_path, manifest)
        try:
            wait_for_libraries(spec, root, manifest, manifest_path)
            libraries, catalog, input_identity = load_inputs(spec, root)
            if manifest.get('inputs', input_identity) != input_identity:
                raise ValueError('Pinned libraries changed since this experiment started. Use a new output directory.')
            manifest.update(inputs=input_identity, status='Running')
            atomic_json(manifest_path, manifest)
            baseline = load_baseline(spec, root, catalog, input_identity)
            baseline_keys = set() if baseline is None else {
                key for family in baseline['selected'] for key in family['member_keys']}
            records = []
            cache = {}
            for run in plan_experiments(spec):
                records.append(execute_run(run, spec, libraries, catalog, input_identity,
                                           baseline_keys, output, root, cache))
                write_reports(records, spec, output)
            if 'followup_runs' not in manifest:
                selected = choose_followups(records, spec['followups']['shortlist'])
                manifest['followup_runs'] = followup_plan(selected, spec)
                atomic_json(manifest_path, manifest)
            for run in manifest['followup_runs']:
                records.append(execute_run(run, spec, libraries, catalog, input_identity,
                                           baseline_keys, output, root, cache))
                write_reports(records, spec, output)
            combine_exports(records, output)
            # Detect mutation of source files during execution as well as on resume.
            for alias, info in input_identity['libraries'].items():
                if file_sha(resolve(root, spec['libraries'][alias])) != info['index_sha256']:
                    raise ValueError(f'Input library {alias} changed during execution.')
            manifest.update(status='Complete', completed_at_utc=utc_now(), runs=len(records),
                            feasible_runs=sum(row['feasible'] for row in records))
            atomic_json(manifest_path, manifest)
            LOG.info('Complete: %s', output)
        except BaseException as error:
            manifest.update(status='Interrupted' if isinstance(error, KeyboardInterrupt) else 'Failed',
                            error=f'{type(error).__name__}: {error}', updated_at_utc=utc_now())
            atomic_json(manifest_path, manifest)
            raise


def load_spec(path: Path) -> dict:
    return validate_spec(json.loads(path.read_text(encoding='utf-8-sig')))


def validate_spec(raw: dict) -> dict:
    """Reject misspellings and invalid grids before waiting or touching evidence."""
    allowed = {'schema_version', 'name', 'output', 'libraries', 'scopes', 'fixed', 'grid', 'wait',
               'followups', 'retry_seconds', 'member_fit_target', 'save_to_builder', 'baseline'}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError('Unknown specification fields or specification is not an object.')
    spec = copy.deepcopy(raw)
    if spec.get('schema_version') != 1:
        raise ValueError('Use experiment schema_version 1.')
    for field in ['name', 'output']:
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise ValueError(f'{field} must be a nonempty string.')
    libraries = spec.get('libraries')
    if not isinstance(libraries, dict) or not libraries or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in libraries.items()):
        raise ValueError('libraries must map aliases to local file paths.')
    scopes = spec.get('scopes')
    if not isinstance(scopes, dict) or not scopes or any(
            not isinstance(k, str) or not k or not isinstance(v, list) or not v
            or any(not isinstance(alias, str) for alias in v)
            or len(v) != len(set(v)) or any(alias not in libraries for alias in v) for k, v in scopes.items()):
        raise ValueError('scopes must map names to unique known library aliases.')
    if set(libraries) != {alias for scope in scopes.values() for alias in scope}:
        raise ValueError('Every declared library must be used in a scope.')
    fixed, grid = spec.get('fixed', {}), spec.get('grid', {})
    if not isinstance(fixed, dict) or not isinstance(grid, dict) or (set(fixed) | set(grid)) - set(DEFAULT_POLICY):
        raise ValueError('Unknown policy fields; use the helper policy names in the example.')
    if any(not isinstance(values, list) or not values for values in grid.values()):
        raise ValueError('Every grid value must be a nonempty list.')
    spec['fixed'], spec['grid'] = fixed, grid
    spec.setdefault('member_fit_target', .8)
    spec.setdefault('retry_seconds', 0)
    spec.setdefault('save_to_builder', False)
    if not isinstance(spec['save_to_builder'], bool):
        raise ValueError('save_to_builder must be true or false.')
    bounded(spec['member_fit_target'], 0, 1, 'member_fit_target')
    bounded(spec['retry_seconds'], 0, 86400, 'retry_seconds')
    wait = spec.setdefault('wait', {})
    if not isinstance(wait, dict) or set(wait) - {'enabled', 'poll_seconds', 'timeout_seconds', 'stale_seconds'}:
        raise ValueError('Unknown wait settings.')
    for key, default in dict(enabled=False, poll_seconds=30, timeout_seconds=86400, stale_seconds=3600).items():
        wait.setdefault(key, default)
    if not isinstance(wait['enabled'], bool):
        raise ValueError('wait.enabled must be true or false.')
    for key in ['poll_seconds', 'timeout_seconds', 'stale_seconds']:
        bounded(wait[key], 1, 604800, key)
    followups = spec.setdefault('followups', {})
    if not isinstance(followups, dict) or set(followups) - {'shortlist', 'coverage_target', 'max_family_cost'}:
        raise ValueError('Unknown followup settings.')
    for key, default in dict(shortlist=0, coverage_target=.95, max_family_cost=4.).items():
        followups.setdefault(key, default)
    if type(followups['shortlist']) is not int or not 0 <= followups['shortlist'] <= 20:
        raise ValueError('followups.shortlist must be an integer from 0 to 20.')
    bounded(followups['coverage_target'], .000001, 1, 'followup coverage')
    bounded(followups['max_family_cost'], .000001, 1000, 'followup family cost')
    if spec.get('baseline') is not None and not isinstance(spec['baseline'], str):
        raise ValueError('baseline must be a cohort path.')
    count = len(scopes) * math.prod(len(values) for values in grid.values())
    if count > 10000:
        raise ValueError('Grid exceeds 10,000 runs; split the experiment.')
    runs = plan_experiments(spec)
    for run in runs:
        validate_policy(run['policy'])
    if spec['followups']['shortlist'] and any(run['policy']['compact_objective'] == SCORE_OBJECTIVE for run in runs):
        raise ValueError('Compact v2 uses explicit sensitivity specifications; disable legacy automatic followups.')
    return spec


def plan_experiments(spec: dict) -> list[dict]:
    # Put preparation controls outside cover-only controls to reuse the last preparation.
    fields = sorted(spec.get('grid', {}), key=lambda field: (field not in PREP_FIELDS, field))
    combinations = list(itertools.product(*(spec['grid'][field] for field in fields)))
    runs, seen = [], set()
    for scope in sorted(spec['scopes']):
        for values in combinations:
            policy = dict(DEFAULT_POLICY, **spec.get('fixed', {}))
            policy.update(zip(fields, values))
            key = fingerprint([scope, policy])
            if key not in seen:
                runs.append({'id': f'run-{len(runs) + 1:04d}-{key[:8]}', 'scope': scope,
                             'phase': 'main', 'policy': policy})
                seen.add(key)
    return runs


def validate_policy(policy: dict):
    if policy['selection_approach'] != 'Compact audience cover':
        raise ValueError('This harness currently supports Compact audience cover only.')
    for field in ['family_target', 'single_threshold', 'shared_threshold', 'separation_target',
                  'minimum_exclusive_share', 'size_preference']:
        bounded(policy[field], 0, 1, field)
    bounded(policy['trim_fraction'], 0, .4, 'trim_fraction')
    bounded(policy['coverage_target'], .000001, 1, 'coverage_target')
    bounded(policy['solve_time_limit'], .001, 86400, 'solve_time_limit')
    for field in ['minimum_family_size', 'maximum_family_size', 'ideal_minimum', 'ideal_maximum']:
        if type(policy[field]) is not int or policy[field] < (0 if field == 'maximum_family_size' else 1):
            raise ValueError(f'{field} must be a valid integer size.')
    if policy['ideal_minimum'] > policy['ideal_maximum'] or (
            policy['maximum_family_size'] and policy['minimum_family_size'] > policy['maximum_family_size']):
        raise ValueError('Family size ranges must be ordered.')
    if policy['cover_basis'] not in {'Full only', 'Full + retained'}:
        raise ValueError('cover_basis must be Full only or Full + retained.')
    if policy['max_family_cost'] is not None:
        bounded(policy['max_family_cost'], .000001, 1000, 'max_family_cost')
    if policy['compact_objective'] not in {LEGACY_OBJECTIVE, SCORE_OBJECTIVE}:
        raise ValueError('Unknown Compact objective version.')
    bounded(policy['overlap_penalty'], 0, math.inf, 'overlap_penalty')
    if policy['compact_objective'] == LEGACY_OBJECTIVE and policy['overlap_penalty']:
        raise ValueError('Overlap penalty is inactive in legacy Compact; use 0.')
    if policy['max_cost_per_character'] is not None:
        raise ValueError('Marginal-cost limit is inactive in Compact; use null.')


def bounded(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be finite and between {low} and {high}.')


def wait_for_libraries(spec: dict, root: Path, manifest: dict, manifest_path: Path):
    started = datetime.fromisoformat(manifest['wait_started_at_utc']).timestamp()
    while True:
        waiting = []
        for alias, path in spec['libraries'].items():
            file = resolve(root, path)
            if not file.exists():
                waiting.append(f'{alias}: file not created')
                continue
            payload = decode_library(file.read_bytes())
            raw = dict(payload)
            if raw.pop('checksum', None) != fingerprint(raw):
                raise ValueError(f'{alias}: invalid library/index checksum.')
            status = payload.get('run_status', {})
            if status.get('errors'):
                raise ValueError(f'{alias}: hunter recorded errors: {status["errors"]}')
            if not status.get('complete'):
                waiting.append(f'{alias}: {status.get("finished_steps", 0)}/{status.get("requested_steps", "?")} jobs')
                if time.time() - file.stat().st_mtime > spec['wait']['stale_seconds']:
                    raise RuntimeError(f'{alias}: checkpoint is stale; preserve it and inspect the hunter.')
                continue
            if (type(status.get('requested_steps')) is not int or status['requested_steps'] < 1
                    or type(status.get('finished_steps')) is not int
                    or status['finished_steps'] != status['requested_steps']):
                raise ValueError(f'{alias}: complete flag disagrees with job counts.')
            if 'jobs' in payload:
                jobs = payload['jobs']
                if len(jobs) != status['requested_steps'] or any(
                        job.get('status') not in TERMINAL_JOBS for job in jobs.values()):
                    raise ValueError(f'{alias}: job index is not complete.')
        if not waiting:
            return
        if not spec['wait']['enabled']:
            raise RuntimeError('Libraries are not ready: ' + '; '.join(waiting))
        if time.time() - started > spec['wait']['timeout_seconds']:
            raise RuntimeError('Timed out waiting for completed hunter libraries.')
        manifest.update(status='Waiting', progress=waiting, updated_at_utc=utc_now())
        atomic_json(manifest_path, manifest)
        LOG.info('Waiting: %s', '; '.join(waiting))
        time.sleep(min(spec['wait']['poll_seconds'], 60))


def load_inputs(spec: dict, root: Path):
    libraries, identities, catalog, hashes = {}, {}, None, None
    for alias, value in spec['libraries'].items():
        path = resolve(root, value)
        index_hash = file_sha(path)
        payload = read_library_file(path)
        if not payload['sources']:
            raise ValueError(f'{alias}: library has no usable evidence.')
        first = next(iter(payload['sources'].values()))
        current = pd.DataFrame(first['automatic'])[['character_key', 'character']].sort_values('character_key').reset_index(drop=True)
        current_hashes = (payload['membership_sha256'], payload['reference_sha256'])
        if catalog is not None and (not current.equals(catalog) or hashes != current_hashes):
            raise ValueError('Libraries use different character catalogs, snapshots or population references.')
        catalog, hashes = current, current_hashes
        validate_library(payload, catalog, *hashes)
        if file_sha(path) != index_hash:
            raise ValueError(f'{alias}: library changed while loading.')
        libraries[alias] = payload
        identities[alias] = {'path': str(path), 'index_sha256': index_hash, 'library_checksum': payload['checksum'],
                             'sources': len(payload['sources']), 'request': payload.get('request'),
                             'bootstrap_repeats': sorted({source['repetitions'] for source in payload['sources'].values()})}
    baseline = resolve(root, spec['baseline']) if spec.get('baseline') else None
    return libraries, catalog, dict(libraries=identities, membership_sha256=hashes[0], reference_sha256=hashes[1],
                                    baseline_sha256=file_sha(baseline) if baseline else None)


def load_baseline(spec, root, catalog, inputs):
    if not spec.get('baseline'):
        return None
    return validate_cohort(decode_library(resolve(root, spec['baseline']).read_bytes()), catalog,
                           inputs['membership_sha256'], inputs['reference_sha256'])


def execute_run(run, spec, libraries, catalog, inputs, baseline_keys, output, root, cache):
    directory = output / run['id']
    record_path = directory / 'result.json'
    if record_path.exists():
        record = json.loads(record_path.read_text())
        checksum = record.pop('checksum', None)
        if checksum != fingerprint(record):
            raise ValueError('Saved run record checksum differs.')
        if record['run'] != run:
            raise ValueError('Saved run identity differs.')
        for name, expected in record['artifacts'].items():
            if file_sha(directory / name) != expected:
                raise ValueError(f'{run["id"]}: saved artifact is missing or changed: {name}')
        if spec['save_to_builder'] and record.get('cohort_file'):
            save_builder_copy(directory / 'cohort.json.gz', output, run, root)
        LOG.info('Resume: verified %s', run['id'])
        return record
    directory.mkdir(parents=True, exist_ok=True)
    policy = run['policy']
    key = fingerprint([run['scope'], {field: policy[field] for field in PREP_FIELDS}])
    if cache.get('key') != key:
        # Retain only the latest preparation: dense evidence can be large.
        sources = {}
        for alias in spec['scopes'][run['scope']]:
            for source_id, source in libraries[alias]['sources'].items():
                if source_id in sources and fingerprint(sources[source_id]) != fingerprint(source):
                    raise ValueError('Conflicting source identity across libraries; evidence was not pooled.')
                sources[source_id] = source
        base = new_draft(sources, catalog, policy, inputs['membership_sha256'], inputs['reference_sha256'])
        LOG.info('Preparing %s: %s sources', run['scope'], len(sources))
        prepared = prepare_library_candidates(base, policy)
        cache.clear()
        cache.update(key=key, base=base, prepared=prepared)
    base, prepared = cache['base'], cache['prepared']
    LOG.info('Run %s: %s', run['id'], policy)
    cover, selected = suggest_from_library(base, policy, prepared)
    attempts = [dict(solver_result(cover), time_limit=policy['solve_time_limit'])]
    if not cover['optimal'] and not cover['infeasible'] and spec['retry_seconds'] > policy['solve_time_limit']:
        retry_policy = dict(policy, solve_time_limit=spec['retry_seconds'])
        retry_cover, retry_selected = suggest_from_library(base, retry_policy, prepared)
        attempts.append(dict(solver_result(retry_cover), time_limit=spec['retry_seconds']))
        # Keep the better validated feasible incumbent, even if the retry timed out earlier.
        if (compare_cover_quality(retry_cover, cover) < 0
                or (compare_cover_quality(retry_cover, cover) == 0
                    and sum(s['optimal'] for s in retry_cover['solver']['stages'])
                    > sum(s['optimal'] for s in cover['solver']['stages']))):
            cover, selected = retry_cover, retry_selected
    usable = cover['feasible'] and cover['eligible_characters'] > 0
    status = ('no-eligible-characters' if not cover['eligible_characters'] else
              ('optimal' if cover['optimal'] else 'feasible-limited') if cover['feasible'] else
              ('infeasible' if cover['infeasible'] else 'no-feasible-result'))
    record = dict(run=run, status=status, feasible=usable, optimal=cover['optimal'],
                  eligible_characters=cover['eligible_characters'], required_characters=cover['required_characters'],
                  roster_characters=len(catalog), attempts=attempts, covered=None, families=None,
                  extra_memberships=None, cohort_file=None, completed_at_utc=utc_now())
    record.update(compact_objective=cover['compact_objective'], overlap_penalty=cover['overlap_penalty'],
                  base_cost=cover['base_cost'] if usable else None,
                  overlap_cost=cover['overlap_cost'] if usable else None,
                  adjusted_cost=cover['adjusted_cost'] if usable else None)
    paths = []
    atomic_json(directory / 'attempts.json', attempts)
    paths.append('attempts.json')
    atomic_csv(directory / 'candidate-character-status.csv', cover['characters'])
    paths.append('candidate-character-status.csv')
    if usable:
        review_policy = {k: v for k, v in policy.items() if k not in LIBRARY_ONLY}
        name = (f'{spec["name"]} / {run["scope"]} / consistency {policy["family_target"]:.0%} '
                f'trim {policy["trim_fraction"]:.0%} coverage {policy["coverage_target"]:.0%} '
                f'exclusive {policy["minimum_exclusive_share"]:.0%} / {run["id"]}')
        draft = dict(base, name=name, policy=review_policy, origin_policy=review_policy,
                     member_target=spec['member_fit_target'], selected=copy.deepcopy(selected),
                     notes='Automated exploratory cover. Review member fits before adopting families.',
                     origin_suggestion={'method': 'Compact audience cover', 'policy': policy,
                                        'solver': cover['solver'], 'attempts': attempts,
                                        'eligible_characters': cover['eligible_characters'],
                                        'required_characters': cover['required_characters'],
                                        'libraries': {a: inputs['libraries'][a] for a in spec['scopes'][run['scope']]}})
        payload = cohort_payload(draft)
        atomic_bytes(directory / 'cohort.json.gz', gzip.compress(json_bytes(payload), compresslevel=1))
        restored = validate_cohort(decode_library((directory / 'cohort.json.gz').read_bytes()), catalog,
                                  inputs['membership_sha256'], inputs['reference_sha256'])
        if restored['selected'] != selected:
            raise ValueError('Portable cohort did not preserve selected families.')
        frames, report = export_frames(draft)
        verify_report(cover, report, policy)
        for filename, frame in frames.items():
            frame = frame.assign(run_id=run['id'], scope=run['scope'], optimization_status=status)
            atomic_csv(directory / filename, frame)
            reread = pd.read_csv(directory / filename)
            if len(frame) != len(reread) or list(frame.columns) != list(reread.columns):
                raise ValueError('CSV roundtrip differs from exported report.')
            paths.append(filename)
        paths.append('cohort.json.gz')
        record.update(report_metrics(report, baseline_keys))
        record['eligible_coverage'] = cover['covered'] / cover['eligible_characters'] if cover['eligible_characters'] else None
        record.update(cohort_file='cohort.json.gz', source_ids=sorted({x['source_id'] for x in selected}),
                      assignment_signature=fingerprint(sorted(sorted(x['member_keys']) for x in selected)))
        if spec['save_to_builder']:
            save_builder_copy(directory / 'cohort.json.gz', output, run, root)
    record['artifacts'] = {name: file_sha(directory / name) for name in paths}
    # The last atomic write commits a completed run. An interrupted export is rerun.
    atomic_json(record_path, dict(record, checksum=fingerprint(record)))
    LOG.info('Saved %s: %s, covered=%s', run['id'], status, record['covered'])
    return record


def solver_result(cover):
    return {key: cover[key] for key in ['feasible', 'optimal', 'infeasible', 'covered',
            'eligible_characters', 'required_characters', 'solver']}


def export_frames(draft):
    """The four builder exports, with frozen source provenance on family/member rows."""
    report = summarize_cohort(draft)
    provenance = pd.DataFrame([dict(
        source_id=key, source_scenario=source['name'], bootstrap_repeats=source['repetitions'],
        repeat_seed=source['repeat_seed'], profiles=source['profiles'],
        method=source.get('method', 'full_leiden' if 'candidate_families' in source else 'scenario'),
        anchor_key=source.get('anchor'), candidate_neighbors=source.get('candidate_neighbors'),
        rank_tiers='/'.join(source['scenario']['source']['tiers']),
        tracking_history=source['scenario']['source']['maturity']) for key, source in draft['sources'].items()])
    families = report['families'].drop(columns='removed_keys', errors='ignore').copy()
    memberships = report['memberships'].copy()
    if not families.empty:
        names = {row['character_key']: row['character'] for row in draft['catalog']}
        families['member_names'] = families.member_keys.map(lambda keys: ', '.join(names[k] for k in keys))
        families['member_keys'] = families.member_keys.map(json.dumps)
        families = families.merge(provenance, on='source_id', how='left')
    if not memberships.empty:
        memberships = memberships.merge(provenance, on='source_id', how='left')
    context = dict(membership_sha256=draft['membership_sha256'], reference_sha256=draft['reference_sha256'],
                   member_fit_target=draft['member_target'], family_target=draft['policy']['family_target'])
    scoring = cohort_scoring_policy(draft)
    context.update(selection_approach=scoring.get('selection_approach', 'Manual cohort'),
                   compact_objective=scoring.get('compact_objective', LEGACY_OBJECTIVE)
                   if scoring.get('selection_approach') == 'Compact audience cover' else None,
                   overlap_penalty=scoring.get('overlap_penalty', 0.))
    frames = {'cohort-families.csv': families, 'cohort-memberships.csv': memberships,
              'cohort-character-review.csv': report['characters'], 'cohort-overlap.csv': overlap_table(draft)}
    # Empty selected cohorts still produce CSVs with headers.
    return {name: frame.assign(**context) for name, frame in frames.items()}, report


def report_metrics(report, baseline_keys):
    families, memberships, characters = report['families'], report['memberships'], report['characters']
    covered = set(characters.loc[characters.family_count.gt(0), 'character_key'])
    names = dict(zip(characters.character_key, characters.character))
    best = memberships.groupby('character_key').member_fit.max() if not memberships.empty else pd.Series(dtype=float)
    metrics = dict(covered=len(covered), families=len(families),
                   extra_memberships=len(memberships) - len(covered),
                   repeated_characters=int(characters.family_count.gt(1).sum()),
                   roster_coverage=len(covered) / len(characters),
                   mean_family_consistency=None if families.empty else float(families.family_mean.mean()),
                   minimum_family_consistency=None if families.empty else float(families.family_mean.min()),
                   families_with_recovery_summary=int(families['mean_recovery'].notna().sum())
                   if 'mean_recovery' in families else 0,
                   minimum_exclusive_share=None if families.empty else float(families.exclusive_share.min()),
                   minimum_observed_exclusive_share=None if families.empty else float(families.exclusive_share.min()),
                   median_exclusive_share=None if families.empty else float(families.exclusive_share.median()),
                   maximum_exclusive_share=None if families.empty else float(families.exclusive_share.max()),
                   minimum_size=None if families.empty else int(families['size'].min()),
                   median_size=None if families.empty else float(families['size'].median()),
                   maximum_size=None if families.empty else int(families['size'].max()),
                   full_families=0 if families.empty else int(families.basis.eq('Full family').sum()),
                   retained_families=0 if families.empty else int(families.basis.eq('Retained members only').sum()),
                   unscored_characters=int(best.isna().sum()),
                   missing=[names[k] for k in sorted(set(names) - covered)],
                   recovered=[names[k] for k in sorted(covered - baseline_keys)] if baseline_keys else [],
                   lost=[names[k] for k in sorted(baseline_keys - covered)],
                   best_member_fit={names[k]: None if pd.isna(value) else float(value) for k, value in best.items()})
    fits = memberships.member_fit.dropna() if not memberships.empty else pd.Series(dtype=float)
    metrics.update(mean_member_fit=None if fits.empty else float(fits.mean()),
                   median_member_fit=None if fits.empty else float(fits.median()),
                   p10_member_fit=None if fits.empty else float(fits.quantile(.1)),
                   minimum_member_fit=None if fits.empty else float(fits.min()))
    for threshold in [.8, .65, .5]:
        label = int(threshold * 100)
        metrics[f'all_placements_below_{label}'] = int(best.lt(threshold).sum())
        metrics[f'best_fit_at_least_{label}'] = int(best.ge(threshold).sum())
        metrics[f'any_placement_below_{label}'] = (int(memberships.loc[memberships.member_fit.lt(threshold),
                                                                    'character_key'].nunique())
                                                 if not memberships.empty else 0)
    return metrics


def verify_report(cover, report, policy):
    families, memberships = report['families'], report['memberships']
    if report['summary']['covered'] != cover['covered'] or len(memberships) - cover['covered'] != cover['extra_memberships']:
        raise ValueError('Report coverage/membership totals differ from solver.')
    if cover['covered'] < cover['required_characters']:
        raise ValueError('Selected cohort fails requested coverage.')
    if not families.empty and (not families.exclusive_share.ge(policy['minimum_exclusive_share'] - 1e-9).all()
                               or not families.family_mean.ge(policy['family_target'] - 1e-9).all()):
        raise ValueError('Selected cohort fails exclusivity or family consistency.')
    if cover.get('compact_objective') == SCORE_OBJECTIVE:
        for key, column in [('base_cost', 'selection_cost'), ('overlap_cost', 'overlap_cost'), ('adjusted_cost', 'adjusted_cost')]:
            if not math.isclose(cover[key], families[column].sum(), abs_tol=SCORE_ABS_TOL, rel_tol=SCORE_REL_TOL):
                raise ValueError(f'Report {key} differs from solver.')


def choose_followups(records, count):
    """Versioned review ordering across policies; never compare differently scaled raw costs."""
    feasible = [row for row in records if row['feasible'] and row['covered']]
    if any(row['run']['policy'].get('compact_objective') == SCORE_OBJECTIVE for row in feasible):
        # Review across policies uses coverage/fit, never differently scaled raw costs.
        feasible.sort(key=lambda row: (-row['covered'], -(row['covered'] - row['all_placements_below_80']),
            row['all_placements_below_50'] / row['covered'], row['run']['id']))
    else:
        feasible.sort(key=lambda row: (
            row['all_placements_below_50'] / row['covered'], row['all_placements_below_80'] / row['covered'],
            -row['covered'], row['extra_memberships'], row['run']['id']))
    chosen, seen = [], set()
    for row in feasible:
        if row['assignment_signature'] not in seen:
            chosen.append(row)
            seen.add(row['assignment_signature'])
        if len(chosen) == count:
            break
    return chosen if count else []


def followup_plan(records, spec):
    result = []
    for row in records:
        original = row['run']
        for label, field in [('coverage', 'coverage_target'), ('cost', 'max_family_cost')]:
            value = spec['followups'][field]
            if original['policy'][field] == value:
                continue
            policy = dict(original['policy'], **{field: value})
            result.append(dict(id=f'{original["id"]}-{label}', scope=original['scope'], phase='followup',
                               parent=original['id'], policy=policy))
    return result


def write_reports(records, spec, output):
    rows, seen = [], {}
    for row in records:
        flat = {k: v for k, v in row.items() if k not in {'run', 'artifacts', 'attempts', 'best_member_fit', 'source_ids'}}
        flat.update(run_id=row['run']['id'], scope=row['run']['scope'], phase=row['run']['phase'], **row['run']['policy'])
        signature = row.get('assignment_signature')
        flat['same_assignments_as'] = seen.get(signature) if signature else None
        if signature:
            seen.setdefault(signature, row['run']['id'])
        rows.append(flat)
    atomic_csv(output / 'comparison.csv', pd.DataFrame(rows))
    shortlist = choose_followups(records, 3)
    atomic_json(output / 'shortlist.json', [row['run']['id'] for row in shortlist])
    text = [f'# {spec["name"]}', '',
            'Exploratory results over frozen evidence. Coverage targets use eligible characters; roster coverage uses all characters.',
            'Higher average consistency does not establish that each member fits. Resampling is internal stability evidence.', '',
            '| Run | Scope | Status | Covered / roster | Families | Extra memberships | All placements below 80% |',
            '|---|---|---|---:|---:|---:|---:|']
    for row in records:
        text.append(f'| {row["run"]["id"]} | {row["run"]["scope"]} | {row["status"]} | '
                    f'{row["covered"]} / {row["roster_characters"]} | {row["families"]} | '
                    f'{row["extra_memberships"]} | {row.get("all_placements_below_80", "—")} |')
    v2 = any(row['run']['policy'].get('compact_objective') == SCORE_OBJECTIVE for row in records)
    ordering = ('highest coverage, then most champions with best fit at least 80%, then lowest fraction '
                'with best fit below 50%, then run ID. Raw costs are not compared across policies.' if v2 else
                'lowest fraction with all placements below 50%, then below 80%, then higher covered count, then fewer extra memberships.')
    text.extend(['', 'Review shortlist: ' + ', '.join(row['run']['id'] for row in shortlist), '',
                 f'Shortlist ordering: {ordering} Identical membership sets appear once. '
                 'This ordering is an exploration aid, not an accepted audience taxonomy.', '',
                 'Each completed run has result.json, attempts.json, character eligibility diagnostics, and—when feasible—'
                 'a portable cohort plus four CSV views. result.json records best member fits and recovered/lost names. '
                 'Exact duplicate covers are flagged in comparison.csv; evidence quality can still differ.', '',
                 'Resume with the same specification and output directory. Completed artifacts are hash-verified. '
                 'No Streamlit restart or hunter mutation is performed.'])
    atomic_bytes(output / 'README.md', '\n'.join(text).encode())


def save_builder_copy(source, output, run, root):
    destination = root / 'data/character_families/cohorts' / f'experiment-{fingerprint(str(output))[:10]}-{run["id"]}.json.gz'
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_bytes(destination, source.read_bytes())


def combine_exports(records, output):
    for name in ['cohort-families.csv', 'cohort-memberships.csv', 'cohort-character-review.csv', 'cohort-overlap.csv']:
        frames = [pd.read_csv(output / row['run']['id'] / name) for row in records if row['feasible']]
        if frames:
            atomic_csv(output / f'all-{name}', pd.concat(frames, ignore_index=True))


def implementation_identity():
    modules = ['family_experiments.py', 'family_cohort.py', 'family_cover.py', 'family_batch.py', 'family_hunter.py', 'families.py']
    return dict(python=platform.python_version(), helpers={name: file_sha(Path(__file__).with_name(name)) for name in modules},
                dependencies={name: version(name) for name in ['numpy', 'pandas', 'scipy', 'igraph', 'leidenalg']})


@contextmanager
def output_lock(directory):
    """OS-owned lock releases on exit/crash; a leftover file never needs deleting."""
    with (directory / '.runner.lock').open('a+b') as handle:
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another experiment runner owns this output directory.') from error
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve(root, value):
    return (root / value).resolve()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value):
    return json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2).encode('utf-8')


def atomic_json(path, value):
    atomic_bytes(path, json_bytes(value))


def atomic_csv(path, frame):
    atomic_bytes(path, frame.to_csv(index=False).encode('utf-8'))


def atomic_bytes(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(value)
    os.replace(temporary, path)
