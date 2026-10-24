"""Batch character-family hunting from saved Leiden configurations."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app_core.families import LOCAL_DIR, load_family_reference, load_membership, prepare_membership
from app_core.family_cohort import fingerprint, subset_scores
from app_core.population import reference_fingerprint
from app_core.ui import setup_page


@st.cache_data(show_spinner=False)
def _prepared(snapshot_version: int, manifest_version: int, reference_hash: str):
    frame, manifest = load_membership()
    return (*prepare_membership(frame), manifest)


def render_family_hunter() -> None:
    setup_page('Full Family Sweep')
    st.subheader('Full Family Sweep')
    st.write('Collect families from shared full-roster ensembles. Characters filter results; they do not start a local search.')
    try:
        from app_core.family_hunter import hunt_step, library_payload, save_library
        path = LOCAL_DIR / 'membership.parquet'
        reference_hash = reference_fingerprint(load_family_reference())
        base, characters, points, _, manifest = _prepared(path.stat().st_mtime_ns,
            (LOCAL_DIR / 'manifest.json').stat().st_mtime_ns, reference_hash)
    except ImportError:
        st.error('Install streamlit_app/requirements-families.txt to use the hunter.')
        return
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    files = {path.name: path for path in sorted((LOCAL_DIR / 'scenarios').glob('*.json'))}
    if not files:
        st.info('Save configurations in Character families first. The hunter uses those settings without modifying the scenarios.')
        return
    catalog = dict(zip(characters.character_key, characters.character))
    mode = st.radio('Characters to include in results', ['Every character', 'Selected characters'], horizontal=True, key='hunter_mode')
    anchors = list(catalog) if mode == 'Every character' else st.multiselect('Characters to include', sorted(catalog, key=catalog.get),
                    format_func=catalog.get, key='hunter_anchors')
    title = st.text_input('Library name', 'Tight / medium / broad search', key='hunter_title')
    count = st.number_input('Search steps', min_value=1, max_value=12, value=3, step=1, key='hunter_step_count',
                             help='Each step runs a shared full-roster ensemble. Its character scope filters the families retained from those runs.')
    steps, errors = [], []
    for index in range(count):
        default_name = ['Tight', 'Medium', 'Broad'][index] if index < 3 else f'Step {index + 1}'
        with st.expander(f'{index + 1} · {default_name} configuration', expanded=index == 0):
            name = st.text_input('Step name', default_name, key=f'hunter_name_{index}')
            defaults = ['!Fine-core', '!Working-draft', '!Broad-backbone']
            default = next((key for key in files if key.startswith(defaults[index])), next(iter(files))) if index < 3 else next(iter(files))
            presets = st.multiselect('Saved configurations to draw from', list(files), default=[default], key=f'hunter_presets_{index}',
                                      help='Each run randomly selects one of these configurations and a random seed. Pick one to vary seeds only.')
            columns = st.columns(3)
            runs = columns[0].number_input('Ensemble runs', min_value=2, max_value=10000, value=20, step=1, key=f'hunter_runs_{index}',
                                          help='Runs per step, shared across its selected characters. This is not a per-character run budget or a bootstrap count.')
            spread = columns[1].slider('Resolution variation', 0., 1., 0., .05, key=f'hunter_spread_{index}',
                                       help='Zero preserves the saved value. At 0.2 a value can vary by roughly ×0.82 to ×1.22, within 0.05–5. Tight/medium/broad are intentions, not guaranteed sizes.')
            neighbors = columns[2].number_input('Neighbor share variation ± (percentage points)', min_value=0., max_value=100., value=0., step=1., key=f'hunter_neighbor_share_{index}',
                                                help='Saved neighbor count ÷ saved roster size becomes a share. Vary it by this many percentage points, then scale to the graph’s available peers.')
            restricted = st.checkbox('Use this step for specific characters only', key=f'hunter_restrict_{index}')
            scope = st.multiselect('Characters for this step', anchors, default=anchors, format_func=catalog.get,
                                    key=f'hunter_scope_{index}') if restricted else anchors
            selected_presets = []
            for filename in presets:
                try:
                    scenario = json.loads(files[filename].read_text(encoding='utf-8'))
                    # Keep reproducible definitions, not copied historical bootstrap matrices.
                    compact = {field: scenario[field] for field in ['schema_version', 'settings', 'source', 'assignments', 'families', 'software']}
                    selected_presets.append({'name': filename, 'scenario': compact})
                except (ValueError, OSError, KeyError, TypeError) as error:
                    errors.append(f'{filename}: {error}')
            steps.append({'name': name, 'presets': selected_presets, 'anchors': scope, 'runs': runs,
                          'resolution_spread': spread, 'neighbor_mode': 'fraction', 'neighbor_fraction_spread': neighbors / 100})
            if selected_presets:
                st.dataframe(pd.DataFrame([dict(configuration=p['name'], **p['scenario']['settings'],
                    neighbor_share=p['scenario']['settings']['neighbors'] / len(p['scenario']['assignments'])) for p in selected_presets]),
                             hide_index=True, width='stretch', column_config={
                                 'neighbors': 'Saved neighbors (reference)',
                                 'neighbor_share': st.column_config.NumberColumn('Graph neighbor share', format='percent')})
    with st.expander('Consensus and player-bootstrap evaluation', expanded=True):
        columns = st.columns(3)
        repeats = columns[0].number_input('Player-bootstrap repeats', min_value=2, max_value=10000, value=20, step=1, key='hunter_bootstraps',
                                          help='Resample whole players and rerun each step’s frozen ensemble and consensus pipeline. This is separate from discovery-run agreement.')
        threshold = columns[1].slider('Consensus agreement cutoff', .05, 1., .5, .05, key='hunter_threshold',
                                      help='Keep a consensus connection only when its pair is together in at least this share of the previous round’s runs.')
        rounds = columns[2].number_input('Maximum consensus rounds', min_value=1, max_value=20, value=3, step=1, key='hunter_rounds',
                                         help='Stop early when all partitions agree. Otherwise stop at this limit and label the result as not converged.')
        columns = st.columns(2)
        resolution = columns[0].number_input('Consensus resolution', min_value=.05, max_value=5., value=1., step=.05, key='hunter_consensus_resolution',
                                              help='Granularity when reclustering the agreement matrix. Distinct from the saved configurations’ discovery resolutions.')
        seed = columns[1].number_input('Search / bootstrap seed', min_value=0, max_value=2**31 - 1, value=42, step=1, key='hunter_seed')
        st.caption('Families are harvested from both the original ensemble and consensus rounds, then exact duplicates are combined within each step. '
                   'Tight/medium/broad steps remain separate. Overlap comes from keeping alternative families, not from making one Leiden partition overlap.')
    st.caption(f'{sum(step["runs"] for step in steps):,} discovery partitions plus up to '
               f'{sum(step["runs"] for step in steps) * rounds:,} consensus partitions; the whole process is repeated '
               f'{repeats} times on player samples. Identical work is shared across characters. Completed steps save locally as they finish.')
    for error in errors:
        st.error(error)
    if st.button('Run family hunt', type='primary', disabled=not anchors or bool(errors), key='hunter_run'):
        from app_core.family_hunter import validate_step
        try:
            for step in steps:
                validate_step(step, characters, manifest['sha256'])
        except (ValueError, KeyError, TypeError) as error:
            st.error(str(error))
            return
        progress = st.progress(0., text='Starting hunt')
        sources, failures, saved_path = {}, [], None
        for index, step in enumerate(steps):
            try:
                source = hunt_step(base, characters, points, step, manifest['sha256'],
                    (seed + index) % 2**31, repeats, threshold, rounds, resolution,
                    lambda fraction, message: progress.progress((index + fraction) / len(steps), text=f'{step["name"]}: {message}'))
                sources[fingerprint(source['scenario'])] = source
            except (ValueError, OSError, KeyError, TypeError) as error:
                failures.append({'step': step['name'], 'error': str(error)})
                st.error(f'{step["name"]}: {error}. Completed steps remain saved.')
            if sources:
                status = {'requested_steps': len(steps), 'finished_steps': index + 1,
                          'complete': index + 1 == len(steps) and not failures, 'errors': failures.copy()}
                payload = library_payload(sources, manifest['sha256'], reference_hash, title, status)
                try:
                    saved_path = save_library(LOCAL_DIR / 'hunter', payload, saved_path)
                except OSError as error:
                    st.error(f'Could not save library: {error}. Use the JSON download below to retain completed work.')
                st.session_state['hunter_result'] = {'payload': payload, 'path': str(saved_path) if saved_path else 'Not saved locally', 'errors': failures.copy()}
        progress.empty()
        if sources:
            st.session_state['hunter_result']['errors'] = failures
        else:
            st.warning('No step completed. Previous results, if any, were preserved.')
    result = st.session_state.get('hunter_result')
    if result:
        if (result['payload']['membership_sha256'] != manifest['sha256']
                or result['payload']['reference_sha256'] != reference_hash):
            st.warning('The previous result belongs to another snapshot/reference. Run a new hunt.')
            return
        _results(result, catalog)


def _results(result: dict, catalog: dict) -> None:
    payload = result['payload']
    sources = payload['sources']
    st.subheader('Generated family library')
    rows = []
    for source_id, source in sources.items():
        for family in source['candidate_families']:
            fits, mean = subset_scores(source, family['member_keys'])
            rows.append(dict(source_id=source_id, step=source['name'], family=family['family'], size=len(fits),
                members=', '.join(fits.character), anchors=', '.join(catalog[key] for key in family['anchors']),
                family_consistency=mean, median_member_fit=float(fits.member_fit.median()),
                weakest_member=float(fits.member_fit.min()), members_below_80=int(fits.member_fit.lt(.8).sum()),
                mean_recovery=family['mean_recovery'], p10_recovery=family['p10_recovery'],
                ensemble_agreement=family['ensemble_agreement'], ensemble_frequency=family['ensemble_frequency'],
                consensus_converged=source['converged'], origins=', '.join(family['origins'])))
    frame = pd.DataFrame(rows)
    columns = st.columns(3)
    columns[0].metric('Generated alternatives', len(frame))
    columns[1].metric('Completed steps', len(sources))
    covered = set().union(*(set(family['member_keys']) for source in sources.values() for family in source['candidate_families']))
    columns[2].metric('Characters with alternatives', f'{len(covered)}/{len(catalog)}')
    st.caption('Alternatives are not all accepted families. Family consistency is mean pair co-assignment under player bootstrap; '
               'recovery is the best-matching regenerated family’s Jaccard. Search and evaluation use the same cohort, so these remain exploratory diagnostics. '
               'Neither is a confidence interval or a membership probability.')
    if result['errors']:
        st.warning('This library is partial: some steps failed.')
        st.dataframe(pd.DataFrame(result['errors']), hide_index=True)
    for source in sources.values():
        if not source['converged']:
            st.warning(f'{source["name"]}: discovery consensus hit the round limit. Kept the representative closest to the last round’s agreement matrix.')
        st.caption(f'{source["name"]}: {source["bootstrap_converged"]}/{source["repetitions"]} player-bootstrap runs reached consensus.')
    search = st.multiselect('Filter alternatives by character', sorted(catalog, key=catalog.get), format_func=catalog.get, key='hunter_result_characters')
    shown = frame.copy()
    if search:
        selected = {(source_id, family['family']) for source_id, source in sources.items()
                    for family in source['candidate_families'] if set(search) & set(family['member_keys'])}
        shown = shown.loc[[pair in selected for pair in zip(shown.source_id, shown.family)]]
    labels = {'family_consistency': 'Family consistency', 'p10_recovery': '10th-percentile recovery',
              'mean_recovery': 'Mean family recovery', 'size': 'Family size', 'weakest_member': 'Weakest member fit'}
    sorting = st.selectbox('Sort alternatives by', list(labels), format_func=labels.get, key='hunter_sort')
    shown = shown.sort_values([sorting, 'size'], ascending=[sorting == 'size', True]) if sorting != 'size' else shown.sort_values('size')
    config = {field: st.column_config.NumberColumn(field.replace('_', ' ').title(), format='percent')
              for field in ['family_consistency', 'median_member_fit', 'weakest_member', 'mean_recovery', 'p10_recovery', 'ensemble_agreement', 'ensemble_frequency']}
    st.dataframe(shown.drop(columns='source_id'), hide_index=True, width='stretch', column_config=config,
                  column_order=['step', 'family', 'size', 'family_consistency', 'mean_recovery', 'p10_recovery',
                                'members_below_80', 'weakest_member', 'median_member_fit', 'ensemble_agreement',
                                'ensemble_frequency', 'consensus_converged', 'members', 'anchors', 'origins'])
    st.download_button('Download generated families CSV', frame.to_csv(index=False).encode(), file_name='hunter-families.csv', mime='text/csv')
    st.download_button('Download hunter library JSON', json.dumps(payload, allow_nan=False).encode(), file_name='hunter-library.json', mime='application/json')
    if st.button('Make this library available in the cohort builder', key='hunter_use_library'):
        st.session_state['hunter_sources'] = sources
        st.success('Available in Family cohort builder. Start empty or import into your current draft; existing selections stay fixed.')
    st.caption(f'Saved locally: {result["path"]}')
