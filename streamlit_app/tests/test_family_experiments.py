"""Experiment state boundaries use temporary evidence and actual cohort/solver helpers."""
from __future__ import annotations

import copy
import json
import time

import numpy as np
import pandas as pd
import pytest

from app_core import family_experiments as lab
from app_core.family_cohort import fingerprint
from app_core.family_hunter import library_payload
from app_core.family_cover import SCORE_OBJECTIVE


@pytest.fixture
def experiment(tmp_path):
    catalog = pd.DataFrame({'character_key': range(6), 'character': list('ABCDEF')})
    automatic = catalog.assign(family=['A'] * 3 + ['B'] * 3)
    matrix = np.zeros((6, 6))
    matrix[:3, :3] = .95
    matrix[3:, 3:] = .85
    np.fill_diagonal(matrix, 0)
    scenario = {'source': {'membership_sha256': 'snapshot', 'reference_sha256': 'reference',
                           'tiers': ['GOLD'], 'maturity': 'All'},
                'families': {'A': {'title': 'A'}, 'B': {'title': 'B'}}, 'software': {'test': '1'}}
    source = dict(name='fixture', scenario=scenario, automatic=automatic.to_dict('records'),
                  co_membership={'character_keys': list(range(6)), 'rates': matrix.tolist()},
                  repetitions=20, repeat_seed=42, profiles=100)
    payload = library_payload({fingerprint(scenario): source}, 'snapshot', 'reference', 'fixture',
                              {'requested_steps': 1, 'finished_steps': 1, 'complete': True, 'errors': []})
    lab.atomic_json(tmp_path / 'library.json', payload)
    spec = lab.validate_spec(dict(schema_version=1, name='Test', output='results',
                                 libraries={'old': 'library.json'}, scopes={'old': ['old']},
                                 fixed=dict(minimum_family_size=2, maximum_family_size=6,
                                            ideal_minimum=2, ideal_maximum=3, solve_time_limit=3),
                                 grid={'coverage_target': [.8, 1.]}))
    return tmp_path, spec, payload


def test_grid_reuses_preparation_controls_and_rejects_typos(experiment):
    _, spec, _ = experiment
    spec['grid'] = dict(family_target=[.75, .8], coverage_target=[.8, .9], trim_fraction=[.2, .4])
    runs = lab.plan_experiments(lab.validate_spec(spec))
    assert len(runs) == 8
    assert runs[0]['policy']['family_target'] == runs[1]['policy']['family_target']
    assert runs[0]['policy']['trim_fraction'] == runs[1]['policy']['trim_fraction']
    assert runs[0]['policy']['coverage_target'] != runs[1]['policy']['coverage_target']
    spec['fixed']['family_consistency'] = .8
    with pytest.raises(ValueError, match='Unknown policy'):
        lab.validate_spec(spec)


@pytest.mark.parametrize('change', [
    {'grid': {'coverage_target': []}}, {'fixed': {'trim_fraction': .5}},
    {'fixed': {'overlap_penalty': 5}}, {'fixed': {'minimum_family_size': 1.5}},
    {'fixed': {'minimum_exclusive_share': float('nan')}}, {'wait': {'enabled': 'yes'}},
    {'save_to_builder': 'yes'}, {'scopes': {'bad': ['missing']}},
])
def test_invalid_specs_fail_before_running(experiment, change):
    _, spec, _ = experiment
    spec.update(change)
    with pytest.raises(ValueError):
        lab.validate_spec(spec)


def test_v2_policy_validation_and_grid_without_creating_a_batch(experiment):
    _, spec, _ = experiment
    spec['fixed'].update(compact_objective=SCORE_OBJECTIVE, overlap_penalty=1.)
    spec['grid'] = dict(family_target=[.75, .8, .85], trim_fraction=[.2, .3, .4],
                        minimum_exclusive_share=[.25, .4], max_family_cost=[None, 3])
    assert len(lab.plan_experiments(lab.validate_spec(spec))) == 36
    spec['followups']['shortlist'] = 3
    with pytest.raises(ValueError, match='explicit sensitivity'):
        lab.validate_spec(spec)


@pytest.mark.parametrize('penalty', [0., 1., 2.])
def test_v2_roundtrip_exports_costs_and_resumes(experiment, monkeypatch, penalty):
    root, spec, _ = experiment
    spec['fixed'].update(compact_objective=SCORE_OBJECTIVE, overlap_penalty=penalty)
    spec['grid'] = {}
    lab.run_experiments(spec, root)
    record_path = next((root / 'results').glob('run-*/result.json'))
    record = json.loads(record_path.read_text())
    assert record['compact_objective'] == SCORE_OBJECTIVE
    assert record['adjusted_cost'] == pytest.approx(record['base_cost'] + record['overlap_cost'])
    families = pd.read_csv(record_path.parent / 'cohort-families.csv')
    assert families.adjusted_cost.sum() == pytest.approx(record['adjusted_cost'])
    assert families.compact_objective.eq(SCORE_OBJECTIVE).all()
    assert families.overlap_penalty.eq(penalty).all()
    restored = lab.decode_library((record_path.parent / 'cohort.json.gz').read_bytes())
    assert restored['origin_suggestion']['policy']['compact_objective'] == SCORE_OBJECTIVE
    assert restored['origin_suggestion']['policy']['overlap_penalty'] == penalty
    assert 'Raw costs are not compared across policies' in (root / 'results/README.md').read_text()
    monkeypatch.setattr(lab, 'suggest_from_library', lambda *a, **k: pytest.fail('Resume must skip solving'))
    lab.run_experiments(spec, root)


def test_v2_retry_uses_adjusted_score_not_extra_memberships(experiment, monkeypatch):
    root, spec, _ = experiment
    spec['fixed'].update(compact_objective=SCORE_OBJECTIVE, overlap_penalty=1.)
    spec['grid'] = {}
    spec['retry_seconds'] = 4
    original = lab.suggest_from_library
    covers = []
    def limited(*args, **kwargs):
        cover, selected = original(*args, **kwargs)
        cover['optimal'] = False
        # Force a retry whose feasible collection has the same coverage, better score,
        # but more repeats. verify_report is separately tested by the real roundtrip.
        cover['adjusted_cost'] = 10 - len(covers)
        cover['extra_memberships'] = len(covers)
        covers.append(cover)
        return cover, selected
    monkeypatch.setattr(lab, 'suggest_from_library', limited)
    monkeypatch.setattr(lab, 'verify_report', lambda *args: None)
    lab.run_experiments(spec, root)
    record = json.loads(next((root / 'results').glob('run-*/result.json')).read_text())
    assert len(covers) == 2 and record['adjusted_cost'] == 9


def test_wait_only_reads_index_until_complete_and_rejects_hunter_errors(experiment, monkeypatch):
    root, spec, payload = experiment
    partial = copy.deepcopy(payload)
    partial['run_status'].update(complete=False, finished_steps=0)
    partial.pop('checksum')
    partial['checksum'] = fingerprint(partial)
    lab.atomic_json(root / 'library.json', partial)
    spec['wait']['enabled'] = True
    calls = []

    def complete(seconds):
        calls.append(seconds)
        lab.atomic_json(root / 'library.json', payload)

    monkeypatch.setattr(lab.time, 'sleep', complete)
    manifest = {'wait_started_at_utc': lab.utc_now()}
    lab.wait_for_libraries(spec, root, manifest, root / 'manifest.json')
    assert calls == [30] and manifest['status'] == 'Waiting'
    partial['run_status']['errors'] = [{'error': 'bad input'}]
    partial.pop('checksum')
    partial['checksum'] = fingerprint(partial)
    lab.atomic_json(root / 'library.json', partial)
    with pytest.raises(ValueError, match='recorded errors'):
        lab.wait_for_libraries(spec, root, manifest, root / 'manifest.json')


def test_complete_flag_cannot_hide_pending_jobs(experiment):
    root, spec, payload = experiment
    payload['jobs'] = {'one': {'status': 'Pending'}}
    payload.pop('checksum')
    payload['checksum'] = fingerprint(payload)
    lab.atomic_json(root / 'library.json', payload)
    with pytest.raises(ValueError, match='job index'):
        lab.wait_for_libraries(spec, root, {'wait_started_at_utc': lab.utc_now()}, root / 'manifest.json')


def test_real_run_roundtrip_resume_and_artifact_tampering(experiment, monkeypatch):
    root, spec, _ = experiment
    spec['save_to_builder'] = True
    original = lab.prepare_library_candidates
    preparations = []

    def prepare(*args):
        preparations.append(True)
        return original(*args)

    monkeypatch.setattr(lab, 'prepare_library_candidates', prepare)
    lab.run_experiments(spec, root)
    assert len(preparations) == 1
    comparison = pd.read_csv(root / 'results/comparison.csv')
    assert comparison.covered.tolist() == [6, 6]
    assert comparison.status.tolist() == ['optimal', 'optimal']
    assert comparison.extra_memberships.tolist() == [0, 0]
    assert comparison.same_assignments_as.notna().sum() == 1
    for directory in (root / 'results').glob('run-*'):
        record = json.loads((directory / 'result.json').read_text())
        assert record['all_placements_below_80'] == 0
        assert len(list(directory.glob('cohort-*.csv'))) == 4
    saved = list((root / 'data/character_families/cohorts').glob('*.gz'))
    assert len(saved) == 2
    mtimes = [path.stat().st_mtime_ns for path in saved]

    def forbidden(*args, **kwargs):
        raise AssertionError('Completed runs must not prepare or solve again')

    monkeypatch.setattr(lab, 'prepare_library_candidates', forbidden)
    lab.run_experiments(spec, root)
    assert json.loads((root / 'results/manifest.json').read_text())['status'] == 'Complete'
    path = next((root / 'results').glob('run-*/cohort-families.csv'))
    path.write_text('modified')
    with pytest.raises(ValueError, match='artifact'):
        lab.run_experiments(spec, root)
    assert json.loads((root / 'results/manifest.json').read_text())['status'] == 'Failed'
    assert all(stamp <= file.stat().st_mtime_ns for stamp, file in zip(mtimes, saved))


def test_interrupted_uncommitted_run_retries_and_pins_inputs(experiment, monkeypatch):
    root, spec, _ = experiment
    original = lab.export_frames
    monkeypatch.setattr(lab, 'export_frames', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        lab.run_experiments(spec, root)
    assert json.loads((root / 'results/manifest.json').read_text())['status'] == 'Interrupted'
    assert not list((root / 'results').glob('run-*/result.json'))
    monkeypatch.setattr(lab, 'export_frames', original)
    lab.run_experiments(spec, root)
    payload = json.loads((root / 'library.json').read_text())
    payload['name'] = 'changed'
    payload.pop('checksum')
    payload['checksum'] = fingerprint(payload)
    lab.atomic_json(root / 'library.json', payload)
    with pytest.raises(ValueError, match='Pinned libraries changed'):
        lab.run_experiments(spec, root)


def test_output_lock_releases_and_excludes_concurrent_writers(tmp_path):
    with lab.output_lock(tmp_path):
        with pytest.raises(RuntimeError, match='Another experiment'):
            with lab.output_lock(tmp_path):
                pass
    with lab.output_lock(tmp_path):
        pass


def test_member_metrics_distinguish_weak_alternative_from_no_strong_placement():
    report = dict(
        families=pd.DataFrame([dict(size=2, family_mean=.85, exclusive_share=.5, basis='Full family')]),
        memberships=pd.DataFrame(dict(character_key=[1, 1, 2], member_fit=[.4, .9, .6])),
        characters=pd.DataFrame(dict(character_key=[1, 2, 3], character=['A', 'B', 'C'], family_count=[2, 1, 0])))
    metrics = lab.report_metrics(report, {1, 3})
    assert metrics['any_placement_below_80'] == 2
    assert metrics['all_placements_below_80'] == 1
    assert metrics['all_placements_below_50'] == 0
    assert metrics['recovered'] == ['B'] and metrics['lost'] == ['C']


def test_shortlist_deduplicates_memberships_and_followups_change_one_control(experiment):
    _, spec, _ = experiment
    run = lab.plan_experiments(spec)[0]
    common = dict(feasible=True, covered=6, all_placements_below_50=0, all_placements_below_80=0,
                  extra_memberships=0, assignment_signature='same', run=run)
    records = [common, dict(common, run=dict(run, id='another'))]
    assert len(lab.choose_followups(records, 3)) == 1
    assert lab.choose_followups(records, 0) == []
    result = lab.followup_plan([common], spec)
    assert len(result) == 2
    for item in result:
        changed = [key for key in run['policy'] if run['policy'][key] != item['policy'][key]]
        assert len(changed) == 1


def test_retry_does_not_discard_a_better_prior_incumbent():
    def cover(extras, count, cost):
        return dict(feasible=True, extra_memberships=extras, covered=6,
                    families=pd.DataFrame({'selection_cost': [cost] * count}))
    assert lab.compare_cover_quality(cover(0, 3, 2), cover(1, 2, 1)) < 0
    assert lab.compare_cover_quality(cover(0, 2, 2), cover(0, 3, 1)) < 0


def test_wait_timeout_and_stale_checkpoint(experiment, monkeypatch):
    root, spec, payload = experiment
    payload['run_status'].update(complete=False, finished_steps=0)
    payload.pop('checksum')
    payload['checksum'] = fingerprint(payload)
    lab.atomic_json(root / 'library.json', payload)
    spec['wait']['enabled'] = True
    spec['wait']['timeout_seconds'] = 1
    with pytest.raises(RuntimeError, match='Timed out'):
        lab.wait_for_libraries(spec, root, {'wait_started_at_utc': '2000-01-01T00:00:00+00:00'}, root / 'm.json')
    monkeypatch.setattr(lab.time, 'time', lambda: time.mktime((2099, 1, 1, 0, 0, 0, 0, 0, -1)))
    with pytest.raises(RuntimeError, match='stale'):
        lab.wait_for_libraries(spec, root, {'wait_started_at_utc': lab.utc_now()}, root / 'm.json')


@pytest.mark.parametrize('infeasible, expected', [(True, 'infeasible'), (False, 'no-feasible-result')])
def test_unsuccessful_solver_runs_never_save_a_cohort(experiment, monkeypatch, infeasible, expected):
    root, spec, _ = experiment
    original = lab.suggest_from_library

    def no_result(*args):
        cover, _ = original(*args)
        cover.update(feasible=False, optimal=False, infeasible=infeasible)
        return cover, []

    monkeypatch.setattr(lab, 'suggest_from_library', no_result)
    lab.run_experiments(spec, root)
    comparison = pd.read_csv(root / 'results/comparison.csv')
    assert comparison.status.tolist() == [expected, expected]
    assert comparison.covered.isna().all()
    assert not list((root / 'results').glob('run-*/cohort.json.gz'))
    assert len(list((root / 'results').glob('run-*/candidate-character-status.csv'))) == 2


def test_retry_preserves_original_solution_when_retry_has_no_incumbent(experiment, monkeypatch):
    root, spec, _ = experiment
    spec['retry_seconds'] = 4
    spec['grid'] = {}
    original = lab.suggest_from_library
    calls = []

    def attempt(*args):
        cover, selected = original(*args)
        calls.append(args[1]['solve_time_limit'])
        if len(calls) == 1:
            cover['optimal'] = False
        else:
            cover.update(feasible=False, optimal=False, infeasible=False)
            selected = []
        return cover, selected

    monkeypatch.setattr(lab, 'suggest_from_library', attempt)
    lab.run_experiments(spec, root)
    record = json.loads(next((root / 'results').glob('run-*/result.json')).read_text())
    assert calls == [3, 4]
    assert record['status'] == 'feasible-limited' and record['covered'] == 6
    assert len(record['attempts']) == 2 and record['attempts'][1]['feasible'] is False


def test_empty_eligibility_is_not_exported_as_a_useful_cohort(experiment):
    root, spec, _ = experiment
    spec['fixed']['family_target'] = 1.
    lab.run_experiments(spec, root)
    comparison = pd.read_csv(root / 'results/comparison.csv')
    assert comparison.status.tolist() == ['no-eligible-characters'] * 2
    assert comparison.eligible_characters.tolist() == [0, 0]
    assert not comparison.feasible.any()
    assert not list((root / 'results').glob('run-*/cohort.json.gz'))


def test_scope_order_does_not_change_planned_run_identity(experiment):
    _, spec, _ = experiment
    spec['scopes'] = {'second': ['old'], 'first': ['old']}
    first = lab.plan_experiments(spec)
    spec['scopes'] = dict(reversed(list(spec['scopes'].items())))
    assert first == lab.plan_experiments(spec)


def test_followups_are_frozen_and_combined_exports_reconcile(experiment):
    root, spec, _ = experiment
    spec['followups']['shortlist'] = 1
    lab.run_experiments(spec, root)
    manifest = json.loads((root / 'results/manifest.json').read_text())
    assert len(manifest['followup_runs']) == 2 and manifest['runs'] == 4
    families = pd.read_csv(root / 'results/all-cohort-families.csv')
    memberships = pd.read_csv(root / 'results/all-cohort-memberships.csv')
    assert len(families) == 8 and len(memberships) == 24
    assert memberships.groupby('run_id').size().tolist() == [6] * 4
    lab.run_experiments(spec, root)
    assert json.loads((root / 'results/manifest.json').read_text())['followup_runs'] == manifest['followup_runs']
