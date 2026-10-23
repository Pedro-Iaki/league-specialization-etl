"""Controls and evidence review for independent anchored family sweeps."""
from __future__ import annotations

import json
import gzip
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core.families import LOCAL_DIR, FamilySettings, load_membership, prepare_membership
from app_core.family_cohort import fingerprint, source_matrix, subset_scores
from app_core.population import load_reference, reference_fingerprint
from app_core.ui import setup_page


@st.cache_data(show_spinner=False)
def _prepared(snapshot_version: int, manifest_version: int, reference_hash: str):
    frame, manifest = load_membership()
    return (*prepare_membership(frame), manifest)


@st.cache_data(show_spinner=False, max_entries=4)
def _read(path: str, modified: int):
    from app_core.family_hunter import read_library_file
    return read_library_file(Path(path))


def _choose(label, options, key, format_func=str):
    if st.session_state.get(key) not in options:
        st.session_state.pop(key, None)
    return st.selectbox(label, options, key=key, format_func=format_func)


def _restore(request: dict, name: str, checkpoint_name: str | None = None) -> None:
    st.session_state['as_restore'] = (request, name, checkpoint_name)


def _apply_restore() -> None:
    restored = st.session_state.pop('as_restore', None)
    if restored is None:
        return
    request, name, checkpoint_name = restored
    for key in list(st.session_state):
        if key.startswith('as_') and key not in {'as_result'}:
            del st.session_state[key]
    st.session_state.update(as_name=name, as_count=len(request['steps']), as_mode='Selected characters',
        as_anchors=sorted({key for step in request['steps'] for key in step['anchors']}),
        as_seed=request['root_seed'], as_repeats=request['repeats'], as_threshold=request['threshold'],
        as_rounds=request['rounds'], as_resolution=request['resolution'],
        as_step_ids=[step['id'] for step in request['steps']], as_preset_overrides={})
    if checkpoint_name:
        st.session_state['as_checkpoint'] = checkpoint_name
    for index, step in enumerate(request['steps']):
        for field, value in [('name', step['name']), ('presets', [p['name'] for p in step['presets']]),
                             ('runs', step['runs']), ('budget', step['candidate_neighbors']),
                             ('spread', step.get('resolution_spread', 0.)), ('neighbors', step.get('neighbor_spread', 0)),
                             ('restrict', True), ('scope', step['anchors']),
                             ('expand', step.get('second_degree_fraction', 0.) > 0),
                             ('fraction', step.get('second_degree_fraction', .2) or .2),
                             ('links', step.get('core_connections', 2))]:
            st.session_state[f'as_{field}_{index}'] = value
        st.session_state[f'as_override_{index}'] = step.get('resolution_override') is not None
        st.session_state[f'as_local_resolution_{index}'] = step.get('resolution_override') or 1.
        st.session_state[f'as_neighbor_share_{index}'] = step.get('neighbor_fraction_spread',
            step.get('neighbor_spread', 0) / len(step['presets'][0]['scenario']['assignments'])) * 100
        st.session_state['as_preset_overrides'].update({p['name']: p['scenario'] for p in step['presets']})


def render_anchored_sweep() -> None:
    _apply_restore()
    setup_page('Anchored Family Sweep')
    st.subheader('Anchored Family Sweep')
    st.write('Give each character its own local search. Candidate windows set the search context; Leiden and consensus determine the families inside it.')
    try:
        from app_core.family_anchored import PairStatisticsPool, candidate_neighborhood, run_anchored_sweep, sweep_request, validate_anchored_step, validate_resume
        path = LOCAL_DIR / 'membership.parquet'
        reference_hash = reference_fingerprint(load_reference())
        base, characters, points, _, manifest = _prepared(path.stat().st_mtime_ns,
            (LOCAL_DIR / 'manifest.json').stat().st_mtime_ns, reference_hash)
    except ImportError:
        st.error('Install streamlit_app/requirements-families.txt to use the local laboratory.')
        return
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    with st.expander('Load search configuration'):
        configuration_files = {p.name: p for p in sorted((LOCAL_DIR / 'anchored_requests').glob('*.json'), reverse=True)}
        saved = _choose('Saved anchored configurations', [None] + list(configuration_files), 'as_config_file',
                         lambda value: value or 'Choose a configuration')
        upload = st.file_uploader('Upload anchored configuration', type='json', key='as_config_upload')
        if st.button('Load search configuration', disabled=saved is None and upload is None, key='as_load_config'):
            try:
                data = json.loads(upload.getvalue()) if upload else _read(str(configuration_files[saved]), configuration_files[saved].stat().st_mtime_ns)
                request = data['request']
                if request['membership_sha256'] != manifest['sha256'] or request['reference_sha256'] != reference_hash:
                    raise ValueError('Configuration belongs to another snapshot or population reference.')
                for step in request['steps']:
                    validate_anchored_step(step, characters, manifest['sha256'])
                sweep_request(request['steps'], manifest['sha256'], reference_hash, request['root_seed'], request['repeats'],
                              request['threshold'], request['rounds'], request['resolution'])
                _restore(request, data.get('name', 'Anchored search'))
                st.rerun()
            except (ValueError, OSError, KeyError, TypeError) as error:
                st.error(f'Could not load configuration: {error}')
    presets, errors = {}, []
    for path in sorted((LOCAL_DIR / 'scenarios').glob('*.json')):
        try:
            scenario = _read(str(path), path.stat().st_mtime_ns)
            presets[path.name] = {field: scenario[field] for field in ['schema_version', 'settings', 'source', 'assignments', 'families', 'software']}
        except (ValueError, OSError, KeyError, TypeError) as error:
            errors.append(f'{path.name}: {error}')
    presets.update(st.session_state.get('as_preset_overrides', {}))
    if not presets:
        st.info('Save reference configurations in Character families first.')
        return
    names = dict(zip(characters.character_key, characters.character))
    mode = st.radio('Characters to search', ['Every character', 'Selected characters'], horizontal=True, key='as_mode')
    anchors = list(names) if mode == 'Every character' else st.multiselect('Anchor characters', sorted(names, key=names.get), format_func=names.get, key='as_anchors')
    name = st.text_input('Library name', 'Anchored tight / medium / broad', key='as_name')
    count = st.number_input('Search steps', min_value=1, max_value=12, value=3, step=1, key='as_count')
    ids = st.session_state.setdefault('as_step_ids', [])
    while len(ids) < count:
        ids.append(f'{len(ids) + 1:02d}-{uuid4().hex[:10]}')
    steps = []
    for index in range(count):
        default_name = ['Tight', 'Medium', 'Broad'][index] if index < 3 else f'Step {index + 1}'
        with st.expander(f'{index + 1} · {st.session_state.get(f"as_name_{index}", default_name)}', expanded=index == 0):
            step_name = st.text_input('Step name', default_name, key=f'as_name_{index}')
            prefix = ['!Fine-core', '!Working-draft', '!Broad-backbone'][index] if index < 3 else ''
            default = next((key for key in presets if key.startswith(prefix)), next(iter(presets)))
            # Source definitions from a loaded request stay frozen, even if a scenario file changes.
            choices = st.multiselect('Reference configurations', list(presets), default=[default], key=f'as_presets_{index}')
            with st.expander('Reference configuration values'):
                st.dataframe(pd.DataFrame([dict(configuration=choice, **presets[choice]['settings'],
                    neighbor_share=presets[choice]['settings']['neighbors'] / len(presets[choice]['assignments'])) for choice in choices]),
                             hide_index=True, width='stretch', column_config={
                                 'neighbors': 'Saved neighbors (reference)',
                                 'neighbor_share': st.column_config.NumberColumn('Graph neighbor share', format='percent')})
            columns = st.columns(3)
            budget = columns[0].number_input('Candidate neighbors (excluding anchor)', min_value=1, max_value=172,
                value=[15, 30, 60][index] if index < 3 else 30, key=f'as_budget_{index}',
                help='A budget of 15 supplies at most 16 characters including the anchor. This is not a final family size or proof that outside characters do not fit.')
            runs = columns[1].number_input('Ensemble runs per character', min_value=2, max_value=10000, value=20, key=f'as_runs_{index}')
            spread = columns[2].slider('Resolution variation', 0., 1., 0., .05, key=f'as_spread_{index}',
                help='Zero keeps the saved resolution. At 0.2 it varies by approximately ×0.82–×1.22. Global resolutions may behave differently in a cropped graph.')
            neighbors = st.number_input('Graph neighbor share variation ± (percentage points)', min_value=0., max_value=100., value=0., step=1., key=f'as_neighbor_share_{index}',
                help='Saved graph neighbors ÷ saved roster size becomes a share. It scales to the actual local window, including bootstrap window changes. Example: 70/173 ≈ 40%, giving 6, 12 or 24 graph neighbors in 15/30/60-neighbor windows.')
            override = st.checkbox('Override saved discovery resolution for this local search', value=True, key=f'as_override_{index}')
            local_resolution = st.number_input('Local discovery resolution', min_value=.05, max_value=5., value=1., step=.05,
                key=f'as_local_resolution_{index}', disabled=not override,
                help='Starts at 1.0 because a resolution tuned on the full roster can fragment a small neighborhood. Turn off the override to use each saved value. Variation is applied after this override.')
            restricted = st.checkbox('Apply step to specific characters only', key=f'as_restrict_{index}')
            if restricted:
                if f'as_scope_{index}' in st.session_state:
                    st.session_state[f'as_scope_{index}'] = [key for key in st.session_state[f'as_scope_{index}'] if key in anchors]
                scope = st.multiselect('Characters for this step', anchors, default=anchors, format_func=names.get, key=f'as_scope_{index}')
            else:
                scope = anchors
            with st.expander('Advanced neighborhood controls'):
                expand = st.checkbox('Allow supported second-degree neighbors', key=f'as_expand_{index}')
                fraction = st.slider('Maximum second-degree share of neighbor slots', 0., .5, .2, .05, key=f'as_fraction_{index}', disabled=not expand)
                links = st.number_input('Required provisional-core connections', min_value=2, max_value=6, value=2, key=f'as_links_{index}', disabled=not expand)
                st.caption('The provisional core is the anchor plus its five strongest eligible neighbors. Expansion requires several core links, '
                           'reserves at most the selected share of slots and never goes beyond two hops. It is a search heuristic, not a validated stable core.')
            steps.append({'id': ids[index], 'name': step_name, 'presets': [{'name': choice, 'scenario': presets[choice]} for choice in choices],
                          'anchors': scope, 'runs': runs, 'candidate_neighbors': budget, 'resolution_spread': spread,
                          'neighbor_mode': 'fraction', 'neighbor_fraction_spread': neighbors / 100,
                          'second_degree_fraction': fraction if expand else 0., 'core_connections': links})
            steps[-1]['resolution_override'] = local_resolution if override else None
    with st.expander('Consensus and player-bootstrap evaluation', expanded=True):
        columns = st.columns(3)
        repeats = columns[0].number_input('Player-bootstrap repeats', min_value=2, max_value=10000, value=20, key='as_repeats')
        threshold = columns[1].slider('Consensus agreement cutoff', .05, 1., .5, .05, key='as_threshold')
        rounds = columns[2].number_input('Maximum consensus rounds', min_value=1, max_value=20, value=3, key='as_rounds')
        columns = st.columns(2)
        resolution = columns[0].number_input('Consensus resolution', min_value=.05, max_value=5., value=1., step=.05, key='as_resolution')
        seed = columns[1].number_input('Root random seed', min_value=0, max_value=2**31 - 1, value=42, key='as_seed')
        st.caption('Every player sample rebuilds the neighborhood and repeats the frozen search schedule. Recovery follows the anchor’s own family. '
                   'Discovery and evaluation use the same collected cohort; these are exploratory diagnostics, not independent validation.')
    valid = bool(anchors)
    try:
        for step in steps:
            validate_anchored_step(step, characters, manifest['sha256'])
        request = sweep_request(steps, manifest['sha256'], reference_hash, seed, repeats, threshold, rounds, resolution)
    except (ValueError, KeyError, TypeError) as error:
        st.warning(str(error))
        valid, request = False, None
    for error in errors:
        st.warning(error)
    jobs = sum(len(step['anchors']) for step in steps)
    initial = sum(len(step['anchors']) * step['runs'] for step in steps)
    st.info(f'{jobs:,} independent character-step jobs · {initial:,} initial partitions · up to {initial * rounds:,} consensus partitions, '
            f'plus {repeats} player-bootstrap repeats of that work. Pair statistics can be reused; character search budgets are never shared.')
    if valid:
        with st.expander('Save search configuration'):
            config = {'name': name, 'request': request}
            content = json.dumps(config, allow_nan=False).encode()
            if st.button('Save configuration locally', key='as_save_config'):
                directory = LOCAL_DIR / 'anchored_requests'
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / f'anchored-request-{uuid4().hex[:12]}.json'
                target.write_bytes(content)
                st.success(f'Saved {target.name}')
            st.download_button('Download search configuration', content, file_name='anchored-request.json', mime='application/json')
        with st.expander('Preview a character’s candidate window'):
            anchor = _choose('Preview character', anchors, 'as_preview_anchor', names.get)
            step_id = _choose('Preview step', [step['id'] for step in steps], 'as_preview_step', lambda key: next(step['name'] for step in steps if step['id'] == key))
            step = next(step for step in steps if step['id'] == step_id)
            signature = fingerprint([manifest['sha256'], reference_hash, step, anchor])
            if st.button('Inspect candidate neighborhood', key='as_preview'):
                pool = PairStatisticsPool(base, points, seed)
                stats, _ = pool.get(step, -1)
                window = candidate_neighborhood(stats, characters.character_key.to_numpy(dtype=int), FamilySettings(**step['presets'][0]['scenario']['settings']),
                    step['presets'][0]['scenario']['source']['excluded_keys'], anchor, step['candidate_neighbors'], step['second_degree_fraction'], step['core_connections'])
                st.session_state['as_preview_result'] = {'signature': signature, 'window': window}
            preview = st.session_state.get('as_preview_result')
            if preview and preview['signature'] == signature:
                _window(preview['window'], names, 'as_preview_outside')
    checkpoint_files = {path.name: path for path in sorted([*(LOCAL_DIR / 'hunter').glob('anchored-*.json'),
                      *(LOCAL_DIR / 'hunter').glob('anchored-*.json.gz')], key=lambda path: path.stat().st_mtime, reverse=True)}
    with st.expander('Resume or review a saved anchored sweep'):
        checkpoint_name = _choose('Saved anchored checkpoints', [None] + list(checkpoint_files), 'as_checkpoint', lambda value: value or 'Choose a saved sweep')
        if st.button('Restore this sweep’s configuration', disabled=checkpoint_name is None, key='as_restore_checkpoint'):
            try:
                path = checkpoint_files[checkpoint_name]
                payload = _read(str(path), path.stat().st_mtime_ns)
                from app_core.family_hunter import validate_library
                validate_library(payload, characters, manifest['sha256'], reference_hash)
                _restore(payload['request'], payload['name'], checkpoint_name)
                st.rerun()
            except (ValueError, OSError, KeyError, TypeError) as error:
                st.error(str(error))
        if st.button('Review saved results', disabled=checkpoint_name is None, key='as_review_checkpoint'):
            try:
                path = checkpoint_files[checkpoint_name]
                payload = _read(str(path), path.stat().st_mtime_ns)
                from app_core.family_hunter import validate_library
                validate_library(payload, characters, manifest['sha256'], reference_hash)
                st.session_state['as_result'] = {'payload': payload, 'path': str(path)}
            except (ValueError, OSError, KeyError, TypeError) as error:
                st.error(str(error))
    columns = st.columns(2)
    start = columns[0].button('Run new anchored sweep', type='primary', disabled=not valid, key='as_run')
    resume = columns[1].button('Resume matching checkpoint', disabled=not valid or checkpoint_name is None, key='as_resume')
    if start or resume:
        progress = st.progress(0., text='Starting anchored sweep')
        try:
            prior, path = None, None
            if resume:
                path = checkpoint_files[checkpoint_name]
                prior = _read(str(path), path.stat().st_mtime_ns)
                validate_resume(prior, request, characters)
            result, path = run_anchored_sweep(base, characters, points, request, name, LOCAL_DIR / 'hunter', prior, path,
                lambda fraction, job: progress.progress(min(fraction, 1.), text=f'{names[job["anchor"]]} · {job["step"]} · {job["status"]}'))
            st.session_state['as_result'] = {'payload': result, 'path': str(path)}
        except (ValueError, OSError, KeyError, TypeError) as error:
            st.error(f'Sweep stopped: {error}. Completed jobs remain in the saved checkpoint.')
        finally:
            progress.empty()
    result = st.session_state.get('as_result')
    if result:
        if result['payload']['membership_sha256'] != manifest['sha256'] or result['payload']['reference_sha256'] != reference_hash:
            st.warning('Previous results use another snapshot/reference. Start a new sweep.')
        else:
            _results(result, names)


def _window(window: dict, names: dict, key: str) -> None:
    rows = pd.DataFrame(window['rows'])
    rows.insert(0, 'character', rows.character_key.map(names))
    rows['supporting_core'] = rows.supporting_core.map(lambda keys: ', '.join(names[key] for key in keys))
    st.caption(f'{window["status"]} · {len(window["indices"]) - 1}/{window["budget"]} neighbor slots filled · '
               f'{window["direct_available"]} eligible direct neighbors. Outside the window does not mean incompatible.')
    outside = st.checkbox('Include outside-window characters and exclusions', key=key)
    if not outside:
        rows = rows.loc[rows.included]
    st.dataframe(rows.sort_values(['included', 'direct_rank', 'character'], ascending=[False, True, True]), hide_index=True, width='stretch')


def _results(result: dict, names: dict) -> None:
    payload = result['payload']
    sources = payload['sources']
    st.subheader('Anchored sweep results')
    jobs = pd.DataFrame(payload['jobs'].values())
    jobs['character'] = jobs.anchor.map(names)
    target = st.slider('Member-fit review target', 0., 1., .8, .05, key='as_member_target',
                       help='Changes review flags and peer support without rerunning the sweep.')
    rows = []
    for source_id, source in sources.items():
        for family in source['candidate_families']:
            fits, mean = subset_scores(source, family['member_keys'], target)
            rows.append(dict(source_id=source_id, family=family['family'], anchor=source['anchor'], character=names[source['anchor']],
                step=source['scenario']['anchored']['step']['name'], candidate_neighbors=source['candidate_neighbors'],
                set_id=fingerprint(family['member_keys'])[:12], size=len(fits), family_consistency=mean,
                weak_members=int(fits.member_fit.lt(target).sum()), weakest_member=float(fits.member_fit.min()),
                anchor_fit=family['anchor_fit'], mean_recovery=family['mean_recovery'], median_recovery=family['median_recovery'],
                p10_recovery=family['p10_recovery'], boundary_retention=family['boundary_retention'],
                ensemble_agreement=family['ensemble_agreement'], ensemble_frequency=family['ensemble_frequency'],
                converged=source['converged'], members=', '.join(names[key] for key in family['member_keys'])))
    rows = pd.DataFrame(rows)
    columns = st.columns(4)
    terminal = jobs.status.isin(['Completed', 'Unsupported / excluded', 'Isolated', 'No accepted family'])
    columns[0].metric('Finished character-step jobs', f'{int(terminal.sum())}/{len(jobs)}')
    columns[1].metric('Unique member sets', rows.set_id.nunique() if not rows.empty else 0)
    columns[2].metric('Evidence variants', len(rows))
    columns[3].metric('Failed jobs', int(jobs.status.eq('Failed').sum()))
    st.caption(f'{jobs.loc[jobs.status.eq("Completed"), "anchor"].nunique()}/{jobs.anchor.nunique()} requested characters have generated alternatives.')
    if not payload['run_status']['complete']:
        st.warning('This sweep is partial. Resume matching work; character coverage is not a job-completion measure.')
    st.caption(f'{payload.get("elapsed_seconds", 0):.1f} seconds in this run · {payload.get("pair_computations", 0)} pair-statistic calculations. '
               'Equal member sets can retain different anchor-specific evidence. Scores are not pooled across sources.')
    with st.expander('Job status by character and step'):
        st.dataframe(jobs, hide_index=True, width='stretch')
    if rows.empty:
        st.info('No families have been generated in the completed work.')
    else:
        selected = st.multiselect('Filter results by search character', sorted(set(rows.anchor), key=names.get), format_func=names.get, key='as_result_anchors')
        shown = rows.loc[rows.anchor.isin(selected)] if selected else rows
        selected_steps = st.multiselect('Filter results by step', list(dict.fromkeys(rows.step)), key='as_result_steps')
        if selected_steps:
            shown = shown.loc[shown.step.isin(selected_steps)]
        config = {field: st.column_config.NumberColumn(field.replace('_', ' ').title(), format='percent')
                  for field in ['family_consistency', 'weakest_member', 'anchor_fit', 'mean_recovery', 'median_recovery', 'p10_recovery', 'boundary_retention',
                                'ensemble_agreement', 'ensemble_frequency', 'member_fit', 'peer_support', 'weakest_pair',
                                'available_member_fit', 'neighborhood_eligibility', 'minimum_consistency', 'maximum_consistency']}
        config.update(character='Search character', step='Step', candidate_neighbors='Neighbor budget', family='Candidate',
                      size='Members', weak_members='Below review target', set_id='Member-set ID', scored_peers='Evaluated peers')
        sort = st.selectbox('Rank evidence variants by', ['family_consistency', 'p10_recovery', 'anchor_fit', 'weakest_member', 'size'],
                             format_func=lambda value: value.replace('_', ' ').title(), key='as_result_sort')
        shown = shown.sort_values(sort, ascending=sort == 'size')
        st.dataframe(shown, column_order=['character', 'step', 'candidate_neighbors', 'family', 'size', 'family_consistency',
            'anchor_fit', 'p10_recovery', 'mean_recovery', 'weak_members', 'weakest_member', 'boundary_retention',
            'ensemble_agreement', 'ensemble_frequency', 'converged', 'set_id', 'members'],
            column_config=config, hide_index=True, width='stretch')
        with st.expander('Identical member sets across search jobs'):
            grouped = shown.groupby('set_id').agg(variants=('source_id', 'size'), size=('size', 'first'),
                minimum_consistency=('family_consistency', 'min'), maximum_consistency=('family_consistency', 'max'),
                search_characters=('character', lambda values: ', '.join(sorted(set(values)))), members=('members', 'first')).reset_index()
            st.dataframe(grouped, hide_index=True, width='stretch', column_config=config)
            st.caption('These are evidence ranges, not a combined stability estimate. Every requested character-step job was still run.')
        options = [(row.source_id, row.family) for row in shown.itertuples()]
        if options:
            lookup = {(row.source_id, row.family): row for row in shown.itertuples()}
            choice = _choose('Inspect an evidence variant', options, 'as_inspect', lambda key: f'{lookup[key].character} · {lookup[key].step} · {lookup[key].family} · {lookup[key].size} characters')
            source = sources[choice[0]]
            family = next(row for row in source['candidate_families'] if row['family'] == choice[1])
            fits, _ = subset_scores(source, family['member_keys'], target)
            fits['neighborhood_eligibility'] = fits.character_key.map(lambda key: source['neighborhood_eligibility'][str(key)])
            st.dataframe(fits.sort_values('member_fit'), hide_index=True, width='stretch', column_config=dict(config, character='Character'))
            if not source['converged']:
                st.warning('Discovery consensus hit its round limit; this source retains an actual representative partition.')
            st.caption(f'{source["bootstrap_converged"]}/{source["repetitions"]} bootstrap runs reached consensus. '
                       'Boundary retention measures full-network connection strength inside the family, not stability.')
            if st.checkbox('Show pair heatmap', key='as_heatmap'):
                matrix = source_matrix(source, family['member_keys'])
                np.fill_diagonal(matrix, np.nan)
                labels = [names[key] for key in family['member_keys']]
                figure = go.Figure(go.Heatmap(z=matrix, x=labels, y=labels, zmin=0, zmax=1, colorscale='Blues'))
                figure.update_layout(height=max(300, min(750, len(labels) * 20 + 100)))
                st.plotly_chart(figure, width='stretch', key='as_pair_heatmap')
            with st.expander('Original candidate window and exclusions'):
                _window(source['window'], names, 'as_inspect_outside')
        st.download_button('Download anchored family metrics CSV', rows.to_csv(index=False).encode(), file_name='anchored-families.csv', mime='text/csv')
    content = json.dumps(payload, allow_nan=False).encode()
    st.download_button('Download anchored library JSON', content, file_name='anchored-library.json', mime='application/json')
    if len(content) > 8_000_000:
        st.download_button('Download compressed anchored library', gzip.compress(content, compresslevel=1),
                           file_name='anchored-library.json.gz', mime='application/gzip')
    if st.button('Make anchored library available in the builder', disabled=not sources, key='as_use_library'):
        st.session_state['hunter_sources'] = sources
        st.success('Available in Family cohort builder. Import into your existing draft or start empty; selected families remain unchanged.')
    st.caption(f'Saved checkpoint: {result["path"]}')
