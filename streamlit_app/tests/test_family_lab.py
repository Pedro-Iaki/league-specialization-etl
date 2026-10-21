from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from app_core.families import prepare_membership, stability_check

pytest.importorskip('leidenalg', reason='Install requirements-families.txt for the optional local laboratory')

APP_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def laboratory(tmp_path):
    rows = []
    for names in [('A', 'B', 'C'), ('D', 'E', 'F')]:
        for _ in range(40):
            rows.append({'region': 'na1', 'queue': 'RANKED_SOLO_5x5', 'tier': 'GOLD', 'days_tracked': 5,
                         'as_of_date': '2026-10-20',
                         'members': [{'key': ord(name), 'name': name, 'points': 20000} for name in names]})
    prepared = prepare_membership(pd.DataFrame(rows))
    manifest = {'sha256': 'test-source', 'max_as_of_date': '2026-10-20', 'exported_at_utc': '2026-10-20'}
    (tmp_path / 'membership.parquet').write_bytes(b'fixture handled by prepared input')
    with patch('app_core.family_lab.LOCAL_DIR', tmp_path), patch('app_core.family_lab._prepared', return_value=(*prepared, manifest)):
        yield AppTest.from_file(str(APP_ROOT / 'pages/5_Character_Families.py'), default_timeout=30), tmp_path


def test_constraints_leave_empty_graph_reviewable(laboratory):
    app, _ = laboratory
    app.run()
    assert not app.exception
    assert next(x for x in app.metric if x.label == 'Candidate families').value == '2'
    next(x for x in app.number_input if x.key == 'family_minimum_shared').set_value(1000)
    next(x for x in app.button if x.label == 'Find candidate families').click().run()
    assert not app.exception
    assert next(x for x in app.metric if x.label == 'Candidate families').value == '0'
    assert any('No families meet' in x.value for x in app.info)


def test_save_restore_manual_titles_assignments_and_stability(laboratory):
    app, directory = laboratory
    app.run()
    next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2)
    next(x for x in app.button if x.label == 'Run both stability checks').click().run()
    assert not app.exception
    assert next(x for x in app.metric if x.label == 'Mean Jaccard').value == '100.0%'
    assert next(x for x in app.metric if x.label == 'Below target').value == '0.0%'
    assert next(x for x in app.metric if x.label == 'Assigned rate').value == '100.0%'
    assert next(x for x in app.metric if x.label == 'Coverage').value == '100.0%'
    next(x for x in app.radio if x.key == 'family_stability_view').set_value('Character relationships').run()
    assert not app.exception
    next(x for x in app.slider if x.key == 'family_stability_target').set_value(.5).run()
    assert not app.exception
    next(x for x in app.button if x.label == 'Save scenario locally').click().run()
    assert not app.exception
    path = next((directory / 'scenarios').glob('*.json'))
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert set(payload['stability_checks']) == {'seed', 'bootstrap'}
    assert payload['stability']['repetitions'] == 2
    assert payload['stability']['metric_version'] == 2
    assert len(payload['stability_checks']['bootstrap']['co_membership']['rates']) == 6
    assert payload['stability']['summary']['target'] == .5
    payload['assignments'][0]['family'] = 'Cross'
    payload['families']['Cross'] = {'title': 'Cross-type candidate', 'description': 'Manual review'}
    payload['notes'] = 'Inspect this alternative later.'
    path.write_text(json.dumps(payload), encoding='utf-8')
    next(x for x in app.button if x.label == 'Load scenario').click().run()
    assert not app.exception
    assert next(x for x in app.metric if x.label == 'Manual changes').value == '1'
    assert any('Cross-type candidate' in option for x in app.selectbox if x.label == 'Inspect family' for option in x.options)
    assert next(x for x in app.text_area if x.label == 'Review notes and remaining questions').value == payload['notes']
    assert len([x for x in app.metric if x.label == 'Mean Jaccard']) == 2


def test_automatic_checks_follow_discovery_changes_and_reuse_cosmetic_results(laboratory):
    app, _ = laboratory
    with patch('app_core.family_lab.stability_check', wraps=stability_check) as check:
        app.run()
        assert check.call_count == 0
        next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
        next(x for x in app.toggle if x.key == 'family_auto_checks').set_value(True).run()
        assert not app.exception
        assert check.call_count == 2
        assert {call.args[-1] for call in check.call_args_list} == {False, True}
        assert len([x for x in app.metric if x.label == 'Mean Jaccard' and x.value == '100.0%']) == 2
        next(x for x in app.slider if x.key == 'family_resolution').set_value(1.2).run()
        assert not app.exception
        assert app.session_state['family_run']['settings'].resolution == 1.2
        assert check.call_count == 4
        next(x for x in app.slider if x.key == 'family_stability_target').set_value(.75).run()
        next(x for x in app.slider if x.key == 'family_core_minimum').set_value(.9).run()
        next(x for x in app.slider if x.key == 'family_core_gap').set_value(.3).run()
        next(x for x in app.selectbox if x.key == 'family_core_selection').set_value('AR02').run()
        next(x for x in app.selectbox if x.key == 'family_detail_check').set_value('bootstrap').run()
        next(x for x in app.selectbox if x.label == 'Inspect family').set_value('AR02').run()
        assert not app.exception
        assert check.call_count == 4
        next(x for x in app.number_input if x.key == 'family_repetitions').set_value(3).run()
        assert not app.exception
        assert check.call_count == 6
        checks = app.session_state['family_stability_checks']
        assert all(report['repetitions'] == 3 for report in checks.values())
        assert all(report['summary']['target'] == .75 for report in checks.values())


def test_older_saved_checks_without_pair_counts_remain_readable(laboratory):
    app, directory = laboratory
    app.run()
    next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
    next(x for x in app.button if x.key == 'family_run_checks').click().run()
    next(x for x in app.button if x.label == 'Save scenario locally').click().run()
    path = next((directory / 'scenarios').glob('*.json'))
    payload = json.loads(path.read_text(encoding='utf-8'))
    for check in payload['stability_checks'].values():
        check.pop('co_membership')
    payload['stability'].pop('co_membership')
    path.write_text(json.dumps(payload), encoding='utf-8')
    next(x for x in app.button if x.label == 'Load scenario').click().run()
    assert not app.exception
    assert len([x for x in app.metric if x.label == 'Mean Jaccard' and x.value == '100.0%']) == 2
    assert any('Older saved checks' in x.value for x in app.info)
    next(x for x in app.button if x.key == 'family_run_checks').click().run()
    assert not app.exception
    assert any(x.key == 'family_core_selection' for x in app.selectbox)


def test_manual_mode_marks_pending_settings_and_applies_them_before_running_both(laboratory):
    app, _ = laboratory
    with patch('app_core.family_lab.stability_check', wraps=stability_check) as check:
        app.run()
        next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
        next(x for x in app.button if x.key == 'family_run_checks').click().run()
        original_signature = app.session_state['family_run']['signature']
        assert check.call_count == 2
        assert not any('Updating seed and player-bootstrap' in x.value for x in app.info)
        next(x for x in app.slider if x.key == 'family_resolution').set_value(1.2).run()
        assert app.session_state['family_run']['signature'] == original_signature
        assert any('last computed definition' in x.value for x in app.info)
        assert check.call_count == 2
        next(x for x in app.button if x.key == 'family_run_checks').click().run()
        assert not app.exception
        assert app.session_state['family_run']['signature'] != original_signature
        assert check.call_count == 4
        next(x for x in app.number_input if x.key == 'family_repetitions').set_value(3).run()
        assert check.call_count == 4
        assert all(x.value == '—' for x in app.metric if x.label == 'Mean Jaccard')


def test_legacy_single_check_loads_and_auto_only_computes_missing_method(laboratory):
    app, directory = laboratory
    app.run()
    next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
    next(x for x in app.button if x.key == 'family_run_checks').click().run()
    next(x for x in app.button if x.label == 'Save scenario locally').click().run()
    path = next((directory / 'scenarios').glob('*.json'))
    payload = json.loads(path.read_text(encoding='utf-8'))
    del payload['stability_checks']
    path.write_text(json.dumps(payload), encoding='utf-8')
    with patch('app_core.family_lab.stability_check', wraps=stability_check) as check:
        next(x for x in app.button if x.label == 'Load scenario').click().run()
        assert not app.exception
        assert check.call_count == 0
        assert set(app.session_state['family_stability_checks']) == {'bootstrap'}
        next(x for x in app.toggle if x.key == 'family_auto_checks').set_value(True).run()
        assert not app.exception
        assert check.call_count == 1
        assert check.call_args.args[-1] is False
        assert set(app.session_state['family_stability_checks']) == {'seed', 'bootstrap'}


def test_automatic_empty_family_checks_remain_unavailable(laboratory):
    app, _ = laboratory
    app.run()
    next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
    next(x for x in app.number_input if x.key == 'family_minimum_shared').set_value(1000).run()
    next(x for x in app.toggle if x.key == 'family_auto_checks').set_value(True).run()
    assert not app.exception
    assert next(x for x in app.metric if x.label == 'Candidate families').value == '0'
    assert all(x.value == '—' for x in app.metric if x.label == 'Mean Jaccard')
    assert all(x.value == '0.0%' for x in app.metric if x.label == 'Coverage')


def test_save_expander_and_auto_name_use_displayed_run(laboratory):
    app, _ = laboratory
    app.run()
    assert any(x.label == 'Save a scenario' for x in app.expander)
    assert any(x.label == 'Load a saved scenario' for x in app.expander)
    assert not any(x.key == 'family_show_save' for x in app.toggle)
    next(x for x in app.button if x.key == 'family_autoname').click().run()
    assert next(x for x in app.text_input if x.key == 'family_scenario_name').value == 'F2-Bna-Sna-Una-C100-J-r1-k10-j0p03-either'
    next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
    next(x for x in app.button if x.key == 'family_run_checks').click().run()
    next(x for x in app.button if x.key == 'family_autoname').click().run()
    name = next(x for x in app.text_input if x.key == 'family_scenario_name')
    assert name.value == 'F2-B100-S100-U0-C100-J-r1-k10-j0p03-either'
    name.set_value('my-reviewed-core').run()
    next(x for x in app.text_area if x.label == 'Review notes and remaining questions').set_value('Keep this draft').run()
    app.run()
    assert not app.exception
    assert next(x for x in app.text_input if x.key == 'family_scenario_name').value == 'my-reviewed-core'
    assert next(x for x in app.text_area if x.label == 'Review notes and remaining questions').value == 'Keep this draft'


def test_family_review_and_refinement_reuse_checks_and_restore_saved_rules(laboratory):
    app, directory = laboratory
    with patch('app_core.family_lab.stability_check', wraps=stability_check) as check:
        app.run()
        next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
        next(x for x in app.button if x.key == 'family_run_checks').click().run()
        assert next(x for x in app.metric if x.label == 'Cohesive & separated').value == '2/2'
        next(x for x in app.button if x.key == 'family_refine_generate').click().run()
        assert not app.exception
        assert next(x for x in app.metric if x.label == 'Primary only').value == '6'
        assert check.call_count == 2
        next(x for x in app.slider if x.key == 'family_trim_fraction').set_value(.3).run()
        next(x for x in app.slider if x.key == 'family_refine_shared').set_value(.5).run()
        assert not any(x.label == 'Primary only' for x in app.metric)
        next(x for x in app.button if x.key == 'family_refine_generate').click().run()
        assert check.call_count == 2
        next(x for x in app.button if x.label == 'Save scenario locally').click().run()
        payload = json.loads(next((directory / 'scenarios').glob('*.json')).read_text(encoding='utf-8'))
        assert len(payload['refinement']['memberships']) == 6
        assert len(payload['refinement']['rows']) == 6
        assert payload['refinement']['rules'] == {'single_threshold': .8, 'shared_threshold': .5}
        # Changing the discovery invalidates the generated final view.
        next(x for x in app.slider if x.key == 'family_resolution').set_value(1.2).run()
        next(x for x in app.button if x.key == 'family_run_checks').click().run()
        assert not any(x.label == 'Primary only' for x in app.metric)
        next(x for x in app.button if x.label == 'Load scenario').click().run()
        assert not app.exception
        assert next(x for x in app.slider if x.key == 'family_refine_shared').value == .5
        assert next(x for x in app.metric if x.label == 'Primary only').value == '6'


def test_indecisive_refinement_exports_no_spurious_nan_memberships(laboratory):
    app, directory = laboratory
    app.run()
    next(x for x in app.number_input if x.key == 'family_repetitions').set_value(2).run()
    next(x for x in app.button if x.key == 'family_run_checks').click().run()
    checks = app.session_state['family_stability_checks']
    rates = checks['bootstrap']['co_membership']['rates']
    checks['bootstrap']['co_membership']['rates'] = [[value if i == j else value * .3 for j, value in enumerate(row)]
                                                    for i, row in enumerate(rates)]
    app.session_state['family_stability_checks'] = checks
    next(x for x in app.button if x.key == 'family_refine_generate').click().run()
    assert not app.exception
    assert next(x for x in app.metric if x.label == 'Indecisive').value == '6'
    next(x for x in app.button if x.label == 'Save scenario locally').click().run()
    assert not app.exception
    payload = json.loads(next((directory / 'scenarios').glob('*.json')).read_text(encoding='utf-8'))
    assert payload['refinement']['memberships'] == []
    assert all(row['final_primary'] is None for row in payload['refinement']['rows'])
