"""Batch comparison page for saved character-family scenarios."""
from __future__ import annotations

import hashlib
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core.families import LOCAL_DIR, load_membership, prepare_membership
from app_core.family_batch import (
    FAMILY_BANDS, STATES, aggregate_coverage, evaluate_scenario, scenario_evidence, smallest_family_cover, target_size_cover,
)
from app_core.family_plots import co_membership_figure, family_consistency_figure
from app_core.family_cohort_view import render_cohort_builder
from app_core.family_cohort import sources_from_cases, fingerprint, subset_scores
from app_core.population import load_reference, reference_fingerprint
from app_core.ui import setup_page


@st.cache_data(show_spinner=False)
def _prepared(snapshot_version: int, manifest_version: int, reference_hash: str):
    frame, manifest = load_membership()
    return (*prepare_membership(frame), manifest)


@st.cache_data(show_spinner=False, max_entries=128)
def _evidence(scenario: dict, source_hash: str, reference_hash: str, repetitions: int, repeat_seed: int,
              _base, _characters, _points):
    return scenario_evidence(scenario, _base, _characters, _points, source_hash, repetitions, repeat_seed)


def render_batch_scenarios() -> None:
    restored = st.session_state.pop('cohort_restore_policy', None)
    if restored:
        controls = {'batch_target': 'family_target', 'batch_trim': 'trim_fraction', 'batch_single': 'single_threshold',
                    'batch_shared': 'shared_threshold', 'batch_gap': 'separation_target',
                    'batch_cover_approach': 'selection_approach', 'batch_cover_basis': 'cover_basis',
                    'batch_coverage_minimum': 'minimum_family_size', 'batch_coverage_maximum': 'maximum_family_size',
                    'batch_ideal_minimum': 'ideal_minimum', 'batch_ideal_maximum': 'ideal_maximum',
                    'batch_size_preference': 'size_preference', 'batch_target_hard_limits': 'hard_size_limits_applied'}
        for widget, field in controls.items():
            if field in restored and st.session_state.get(widget) != restored[field]:
                st.session_state[widget] = restored[field]
        for toggle, widget, field in [('batch_limit_family_cost', 'batch_max_family_cost', 'max_family_cost'),
                                       ('batch_limit_marginal_cost', 'batch_max_marginal_cost', 'max_cost_per_character')]:
            st.session_state[toggle] = restored.get(field) is not None
            if restored.get(field) is not None:
                st.session_state[widget] = restored[field]
    setup_page('Family cohort builder')
    st.subheader('Family cohort builder')
    st.caption('Compare scenario evidence, then curate families with character fit, coverage and overlap in view.')
    path = LOCAL_DIR / 'membership.parquet'
    if not path.exists():
        st.info('Export the local character membership snapshot before comparing scenarios.')
        return
    try:
        import leidenalg  # noqa: F401
        reference_hash = reference_fingerprint(load_reference())
        base, characters, points, _, manifest = _prepared(path.stat().st_mtime_ns,
                                                        (LOCAL_DIR / 'manifest.json').stat().st_mtime_ns, reference_hash)
    except ImportError:
        st.error('Install streamlit_app/requirements-families.txt to use the local laboratory.')
        return
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    files = {p.name: p for p in sorted((LOCAL_DIR / 'scenarios').glob('*.json'))}
    marked = [name for name in files if name.startswith('!')]
    if 'batch_selected_scenarios' not in st.session_state:
        st.session_state['batch_selected_scenarios'] = marked
    else:
        st.session_state['batch_selected_scenarios'] = [name for name in st.session_state['batch_selected_scenarios'] if name in files]
    with st.expander('Evidence library and batch settings', expanded='batch_results' not in st.session_state):
        buttons = st.columns(3)
        for column, label, names in [(buttons[0], 'Select marked scenarios', marked),
                                     (buttons[1], 'Select all saved scenarios', list(files)),
                                     (buttons[2], 'Clear selection', [])]:
            if column.button(label):
                st.session_state['batch_selected_scenarios'] = names
        selected = st.multiselect('Saved scenarios', list(files), key='batch_selected_scenarios',
                                  format_func=lambda name: name.removeprefix('!').split('-Boot')[0].removesuffix('.json'))
        uploads = st.file_uploader('Add scenario JSON files', type='json', accept_multiple_files=True, key='batch_uploads')
        columns = st.columns(4)
        repetitions = columns[0].number_input('Bootstrap repeats', 2, 50, 20, key='batch_repetitions')
        target = columns[1].slider('Family consistency target', 0.0, 1.0, .8, .05, key='batch_target')
        single = columns[2].slider('Single-family threshold', 0.0, 1.0, .8, .05, key='batch_single')
        shared = columns[3].slider('Both-families threshold (each)', 0.0, 1.0, .4, .05, key='batch_shared')
        with st.expander('Bootstrap and family review settings'):
            columns = st.columns(3)
            repeat_seed = columns[0].number_input('Common repeat seed', 0, 2**31-1, 42, key='batch_repeat_seed')
            trim = columns[1].slider('Weakest-member removal', 0.0, .4, .2, .05, key='batch_trim',
                                     help='Same removal fraction for every scenario, rounded up while retaining at least two characters per family.')
            gap = columns[2].slider('Separation review target', 0.0, 1.0, .2, .05, key='batch_gap',
                                    help='Shown in detailed family review. It does not change the three cohesion categories used in the comparison.')
            st.caption('All scenarios use the same repeat count and repeat seed; equal cohorts use identical player resamples. '
                       'Matching saved evidence and computed evidence are cached. Review thresholds and chart choices reuse it. '
                       'Original discovery settings and cohorts remain scenario-specific. Manual edits and saved final views '
                       'are reference material; batch results are regenerated from the original discovery groups.')
        run = st.button('Run batch comparison', type='primary', key='batch_run', disabled=shared > single)
        if shared > single:
            st.warning('The both-families threshold must not exceed the single-family threshold.')
    inputs = []
    for name in selected:
        if name in files:
            inputs.append((name, files[name].read_bytes()))
    inputs += [(f'Uploaded · {upload.name}', upload.getvalue()) for upload in uploads or []]
    request = hashlib.sha256(json.dumps([[(name, hashlib.sha256(content).hexdigest()) for name, content in inputs],
                                         repetitions, repeat_seed, manifest['sha256'], reference_hash], sort_keys=True).encode()).hexdigest()
    if run:
        if not inputs:
            st.info('Select or upload at least one scenario.')
            return
        results, errors = [], []
        progress = st.progress(0, text='Preparing selected scenarios…')
        for index, (name, content) in enumerate(inputs):
            progress.progress(index / len(inputs), text=f'{index+1}/{len(inputs)} · {name}')
            try:
                scenario = json.loads(content)
                # Equivalent saves can share evidence despite differing save times or notes.
                analysis_input = ({k: v for k, v in scenario.items() if k not in {'saved_at_utc', 'notes', 'status'}}
                                  if isinstance(scenario, dict) else scenario)
                evidence = _evidence(analysis_input, manifest['sha256'], reference_hash, repetitions, repeat_seed, base, characters, points)
                case_id = hashlib.sha256((str(index) + name).encode() + content).hexdigest()[:16]
                results.append({'name': name, 'id': case_id, 'scenario': scenario, 'evidence': evidence})
            except (ValueError, OSError, KeyError, TypeError) as error:
                errors.append({'Scenario': name, 'Error': str(error)})
        progress.empty()
        st.session_state['batch_results'] = {'request': request, 'cases': results, 'errors': errors}
    saved = st.session_state.get('batch_results')
    review_policy = {'family_target': target, 'trim_fraction': trim, 'single_threshold': single,
                     'shared_threshold': shared, 'separation_target': gap}
    if shared > single:
        return
    if saved is None:
        st.info('Select scenarios and run the comparison. Missing bootstrap evidence is computed locally; saved files are preserved.')
        render_cohort_builder([], characters, None, review_policy, manifest['sha256'], reference_hash)
        return
    if saved['request'] != request:
        st.info('Selection, scenario files, repeat count or repeat seed changed. Run batch comparison to update the results.')
        render_cohort_builder([], characters, None, review_policy, manifest['sha256'], reference_hash)
        return
    if saved['errors']:
        st.warning('Some scenarios could not be evaluated. Their errors are listed separately; they are not scored as zero.')
        st.dataframe(pd.DataFrame(saved['errors']), hide_index=True, width='stretch')
    cases = saved['cases']
    if not cases:
        render_cohort_builder([], characters, None, review_policy, manifest['sha256'], reference_hash)
        return
    evaluated = [dict(case, result=evaluate_scenario(case['evidence'], target, trim, single, shared, gap)) for case in cases]
    _coverage_overview(evaluated, characters)
    st.caption(f'{len(evaluated)} scenarios evaluated · {repetitions} bootstrap repeats · seed {repeat_seed} · '
               f'snapshot {manifest["sha256"][:12]}. Curation reuses these matrices.')
    with st.expander('Scenario evidence and comparison'):
        _comparison(evaluated, target)
        if st.checkbox('Show individual scenario charts', key='batch_show_details'):
            expand = st.checkbox('Expand all scenario charts', key='batch_expand_all')
            for case in evaluated:
                _scenario_details(case, target, expand)


def _coverage_overview(cases: list[dict], universe: pd.DataFrame) -> None:
    st.subheader('Small families, complete coverage')
    with st.expander('Coverage settings'):
        minimum = st.number_input('Minimum included family size (characters)', 1, len(universe), 2,
                                   key='batch_coverage_minimum',
                                   help='Set to 3 to exclude pairs, or higher for broader groups. Applies to coverage, the size curve and the suggested cover. Retained-only families must have this many kept members.')
        maximum = st.number_input('Maximum included family size (0 = unlimited)', 0, len(universe), 0,
                                   key='batch_coverage_maximum',
                                   help='Restricts coverage totals and the suggested cover. Uses kept group size for retained-only families. The size curve ignores this upper limit; the all-candidates browser ignores both size limits.')
        if maximum and maximum < minimum:
            st.warning('The maximum is below the minimum, so no families qualify for coverage.')
    available = aggregate_coverage(cases, universe)
    eligible = aggregate_coverage(cases, universe, minimum_family_size=minimum) if minimum > 1 else available
    aggregate = aggregate_coverage(cases, universe, maximum, minimum) if maximum else eligible
    total = aggregate['total_characters']
    columns = st.columns(3)
    for column, label, count in [(columns[0], 'Full families only', aggregate['full_characters']),
                                 (columns[1], 'Full + retained', aggregate['combined_characters'])]:
        column.metric(label, f'{count}/{total}', help=f'{count / total:.1%} of the full character catalog' if total else 'No characters')
        column.caption(f'{count / total:.1%} of characters' if total else 'No character catalog')
    columns[2].metric('Retained members add', aggregate['retained_adds'])
    columns[2].caption(f"{aggregate['uncovered_characters']} still uncovered")
    covers = {label: smallest_family_cover(eligible['families'], universe, include)
              for label, include in [('Full families only', False), ('Full + retained', True)]}
    figure = go.Figure()
    sizes = sorted({0, *eligible['families'].included_characters.tolist()})
    for (label, cover), color in zip(covers.items(), ['#58b798', '#4ea5d9'], strict=True):
        counts = [int(cover['characters'].smallest_family_size.le(size).sum()) for size in sizes]
        figure.add_trace(go.Scatter(x=sizes, y=counts, name=label, mode='lines+markers',
                                    line=dict(color=color, shape='hv'),
                                    hovertemplate='Allow families up to %{x} characters<br>%{y} covered<extra>%{fullData.name}</extra>'))
    figure.add_hline(y=total, line_dash='dot', line_color='#d8a52d', annotation_text='All characters')
    if maximum:
        figure.add_vline(x=maximum, line_dash='dot', line_color='#778797')
    figure.update_layout(title='Coverage as larger families are allowed', height=290,
                         margin=dict(l=5, r=10, t=40, b=5), legend=dict(orientation='h', y=-.25))
    figure.update_xaxes(title='Maximum characters per family', rangemode='tozero', dtick=1 if max(sizes) <= 15 else None)
    figure.update_yaxes(title='Unique characters covered', range=[0, max(1, total) * 1.08])
    with st.expander('Library coverage as larger families are allowed'):
        st.plotly_chart(figure, width='stretch', key='batch_coverage_plot')
    st.caption('Coverage is the union of character IDs across successful scenarios, counted once per character against '
               'the full snapshot catalog. Full families contribute all their members; retained-only families contribute '
               'only the members remaining after weakest-member removal. Below-target families contribute nothing. '
               f'The curve uses families with at least {minimum} included characters, before the optional maximum size limit.')
    suggestion, browser, gaps = st.tabs(['Suggested cover', 'All viable families', 'Characters and gaps'])
    with suggestion:
        _suggested_cover(cases, universe, available['families'], aggregate['families'], covers, minimum, maximum)
    with browser:
        _viable_families(available['families'], cases, universe)
    with gaps:
        view = st.selectbox('Characters to inspect', ['Uncovered with full + retained', 'Uncovered with full only',
                                                     'Added by retained', 'All characters'], key='batch_coverage_view')
        rows = aggregate['coverage']
        if view == 'Uncovered with full + retained':
            rows = rows.loc[~rows.covered_full_or_retained]
        elif view == 'Uncovered with full only':
            rows = rows.loc[~rows.covered_full]
        elif view == 'Added by retained':
            rows = rows.loc[rows.covered_full_or_retained & ~rows.covered_full]
        if rows.empty:
            st.info('No characters in this category for the current batch and family-size limit.')
        else:
            st.dataframe(rows, hide_index=True, width='stretch', column_order=[
                'character', 'coverage_status', 'full_family_matches', 'retained_family_matches', 'full_sources', 'retained_sources'],
                column_config={'character': 'Character', 'coverage_status': 'Coverage',
                               'full_family_matches': 'Full-family matches', 'retained_family_matches': 'Retained-family matches',
                               'full_sources': 'Full-family sources', 'retained_sources': 'Retained-family sources'})
        st.markdown('**Coverage available from each scenario**')
        st.dataframe(aggregate['contributions'], hide_index=True, width='stretch', column_config={
            'scenario': 'Scenario', 'full_characters': 'Full-only unique characters',
            'full_or_retained_characters': 'Full + retained unique characters'})
        st.caption('Scenario rows overlap and must not be added. Repeated matches are references, not independent confirmation.')
        columns = st.columns(2)
        rules = cases[0]['result']['rules']
        context = {'minimum_family_size': minimum, 'maximum_family_size': maximum, 'family_target': rules['family_target'],
                   'trim_fraction': rules['trim_fraction'], 'catalog_characters': total}
        columns[0].download_button('Download character coverage CSV',
                                    aggregate['coverage'].assign(**context).to_csv(index=False).encode(),
                                    file_name='batch-character-coverage.csv', mime='text/csv')
        columns[1].download_button('Download coverage memberships CSV',
                                    aggregate['memberships'].assign(**context).to_csv(index=False).encode(),
                                    file_name='batch-coverage-memberships.csv', mime='text/csv')


def _suggested_cover(cases: list[dict], universe: pd.DataFrame, available: pd.DataFrame,
                      limited: pd.DataFrame, covers: dict, minimum: int, maximum: int) -> None:
    approach = st.radio('Selection approach', ['Smallest available', 'Target-size cover'], horizontal=True,
                         key='batch_cover_approach')
    mode = st.radio('Families allowed in suggested cover', list(covers), index=1, horizontal=True,
                     key='batch_cover_basis')
    target = approach == 'Target-size cover'
    context = {'selection_approach': approach, 'cover_basis': mode, 'catalog_characters': len(universe)}
    apply_limits = True
    if target:
        columns = st.columns(2)
        low = columns[0].number_input('Ideal minimum family size', min_value=1, value=10, key='batch_ideal_minimum')
        high = columns[1].number_input('Ideal maximum family size', min_value=1, value=15, key='batch_ideal_maximum')
        preference = st.slider('Preference for ideal size', 0.0, 1.0, .5, .1, key='batch_size_preference',
                                help='0 favors fewer families and consistency. Higher values pay more attention to each character\'s closest selected family size. This is a soft preference, not a coverage cutoff.')
        st.caption('Lower preference: fewer families. Higher preference: closer to the ideal range. '
                   'Size penalties are proportional: halving a below-range family and doubling an above-range family '
                   'each add one size-distance unit. Families outside the preferred range remain available for coverage.')
        with st.expander('Cost limits and stopping rule'):
            columns = st.columns(2)
            limit_family = columns[0].checkbox('Limit family cost', key='batch_limit_family_cost')
            family_limit = columns[0].number_input('Maximum family cost', min_value=.01, value=5.0, step=.25,
                key='batch_max_family_cost', disabled=not limit_family,
                help='Exclude candidates above this cost before selection and refinement. Lower values favor stronger families closer to the ideal size.')
            limit_marginal = columns[1].checkbox('Limit cost per additional character', key='batch_limit_marginal_cost')
            marginal_limit = columns[1].number_input('Maximum cost per additional character', min_value=.01, value=1.0, step=.05,
                key='batch_max_marginal_cost', disabled=not limit_marginal,
                help='Stop when the cheapest next family costs more than this per newly covered character. A cost-3 family adding 12 characters costs 0.25 each; adding just one costs 3.')
            st.caption('Both limits are optional. The marginal rule allows partial coverage rather than adding families '
                       'for an expensive final few characters. It also blocks zero-coverage additions during refinement; '
                       'replacements must meet the same cost limit for the coverage they restore.')
        family_cost_limit = family_limit if limit_family else None
        marginal_cost_limit = marginal_limit if limit_marginal else None
        apply_limits = st.checkbox('Apply coverage size limits to target cover', key='batch_target_hard_limits',
                                     help='Off by default: the target cover uses every viable candidate, even outside the hard limits in Coverage settings. Turn on only if you want those exclusions to override coverage.')
        if high < low:
            st.warning('The ideal maximum must be at least the ideal minimum.')
            return
        cover = target_size_cover(limited if apply_limits else available, universe, mode == 'Full + retained', low, high, preference,
                                  family_cost_limit, marginal_cost_limit)
        context.update(ideal_minimum=low, ideal_maximum=high, size_preference=preference,
                       max_family_cost=family_cost_limit, max_cost_per_character=marginal_cost_limit,
                       size_distance_method='log2_ratio_to_ideal_interval')
        columns = st.columns(4)
        columns[0].metric('Suggested families', len(cover['families']))
        columns[1].metric('Suggested coverage', f'{cover["covered"]}/{len(universe)}')
        columns[2].metric('Covered in ideal-sized families', cover['ideal_characters'])
        columns[3].metric('Covered outside ideal range', cover['outside_ideal_characters'])
        columns = st.columns(2)
        columns[0].metric('No eligible family', cover['no_eligible_characters'])
        columns[1].metric('Left uncovered by marginal limit', cover['cost_limited_characters'])
        if cover['family_cost_excluded_characters']:
            columns[0].caption(f'{cover["family_cost_excluded_characters"]} lost all options to the family-cost ceiling.')
        st.caption('Consistency remains the eligibility gate. Selection rewards newly covered characters per family cost, '
                   'then tests additions, removals and swaps to improve family count, consistency and each character\'s '
                   'best selected size fit while preserving the covered set and respecting cost limits. This is a heuristic suggestion, not a guaranteed optimum. '
                   'Coverage totals and the curve above follow Coverage settings; this cover applies those hard size limits only when checked.')
        outside = cover['characters'].loc[cover['characters'].suggested_family_id.notna() & ~cover['characters'].in_ideal_range]
        st.caption(f'{len(outside)} covered characters have no selected family in the ideal range; '
                   f'{int((~outside.ideal_option_available).sum())} of them have no ideal-sized option anywhere in the eligible pool. '
                   'Other exceptions reflect selection tradeoffs and any active marginal-cost limit.')
    else:
        cover = (smallest_family_cover(limited, universe, mode == 'Full + retained') if maximum else covers[mode])
        columns = st.columns(3)
        columns[0].metric('Smallest size limit for full coverage', cover['minimum_size_cap'] if cover['complete'] else 'Unavailable')
        columns[1].metric('Suggested families', len(cover['families']))
        columns[2].metric('Suggested coverage', f'{cover["covered"]}/{len(universe)}')
        st.caption('For each character, find its smallest viable family within the selected size limits. The suggestion '
                   'keeps at least one of these smallest options for every coverable character. The size limit needed '
                   'for complete coverage is exact within this batch; the overlapping subset is chosen greedily and '
                   'does not minimize the number of families. No new families are invented.')
    context.update(minimum_family_size=minimum if apply_limits else 1, maximum_family_size=maximum if apply_limits else 0,
                   hard_size_limits_applied=apply_limits)
    if not cover['complete']:
        missing = cover['characters'].loc[cover['characters'].suggested_family_id.isna(), 'character']
        if target:
            st.warning(f'{len(missing)} characters remain uncovered under the current eligibility and cost limits. '
                       'Inspect their reasons and cheapest remaining options below.')
        else:
            st.warning('Complete coverage is unavailable with these candidates and the current size limits. '
                       f'Uncovered: {", ".join(missing)}.')
    _candidate_table(cover['families'])
    source = cases[0]['scenario']['source']
    render_cohort_builder(cases, universe, cover, dict(context, **cases[0]['result']['rules']),
                          source['membership_sha256'], source['reference_sha256'])
    with st.expander('Character fit and suggested families' if target else 'Smallest option for each character'):
        rows = cover['characters']
        if target and st.checkbox('Show only covered characters outside the ideal range', value=True, key='batch_target_exceptions'):
            rows = rows.loc[rows.suggested_family_id.notna() & ~rows.in_ideal_range]
        st.dataframe(rows, hide_index=True, width='stretch', column_order=[
            'character', *(['coverage_status', 'suggested_family_size', 'proportional_distance', 'target_distance', 'ideal_option_available'] if target else ['smallest_family_size']),
            'suggested_scenario', 'suggested_family'], column_config={
            'character': 'Character', 'smallest_family_size': 'Smallest viable family size',
            'suggested_family_size': 'Selected family size',
            'target_distance': st.column_config.NumberColumn('Size gap',
                help='Number of members below the ideal minimum or above the ideal maximum; zero within the preferred range.'),
            'proportional_distance': st.column_config.NumberColumn('Proportional size gap', format='%.2f'),
            'ideal_option_available': 'Any ideal-sized candidate available',
            'suggested_scenario': 'Suggested scenario', 'suggested_family': 'Suggested family'})
    if target:
        with st.expander('Uncovered characters and cheapest remaining options'):
            missing = cover['characters'].loc[cover['characters'].suggested_family_id.isna()]
            if missing.empty:
                st.info('Every character is covered under the current settings.')
            else:
                st.dataframe(missing, hide_index=True, width='stretch', column_order=[
                    'character', 'coverage_status', 'coverage_reason', 'cheapest_remaining_family',
                    'cheapest_remaining_scenario', 'cheapest_remaining_cost_per_character', 'cheapest_remaining_blocked_by'], column_config={
                    'character': 'Character', 'coverage_status': 'Coverage', 'coverage_reason': 'Reason',
                    'cheapest_remaining_family': 'Lowest cost per additional character: family', 'cheapest_remaining_scenario': 'Source scenario',
                    'cheapest_remaining_blocked_by': 'Option blocked by',
                    'cheapest_remaining_cost_per_character': st.column_config.NumberColumn('Cost / additional character', format='%.3f')})
                st.caption('Remaining family options are ordered by cost per currently uncovered character. '
                           'This ranks coverage expansion, not the individual character’s fit. Use the cohort resolver for that comparison. '
                           'A family can exceed either or both limits; the first blocking limit is shown. '
                           'Options overlap, so their additional-character counts must not be added.')
                _candidate_table(cover['remaining_options'])
            st.download_button('Download remaining coverage options CSV',
                _candidate_export(cover['remaining_options'], cases).assign(**context).to_csv(index=False).encode(),
                file_name='batch-remaining-coverage-options.csv', mime='text/csv')
    export = _candidate_export(cover['families'], cases).assign(**context)
    columns = st.columns(2)
    columns[0].download_button('Download suggested families CSV', export.to_csv(index=False).encode(),
                                file_name='batch-suggested-family-cover.csv', mime='text/csv')
    join = [column for column in export if column not in cover['characters'].columns]
    options = cover['characters'].merge(export[join], how='left', left_on='suggested_family_id', right_on='family_id').assign(**context)
    columns[1].download_button('Download character cover CSV', options.to_csv(index=False).encode(),
                                file_name='batch-character-cover-options.csv', mime='text/csv')


def _candidate_table(families: pd.DataFrame) -> None:
    remaining = 'cost_per_new_character' in families
    order = ['cost_per_new_character', 'selection_cost', 'family_id'] if remaining else ['included_characters', 'qualifying_consistency']
    st.dataframe(families.sort_values(order, ascending=True if remaining else [True, False]),
                  hide_index=True, width='stretch', column_order=[
        'member_names', 'included_characters', *(['new_characters', 'cost_per_new_character', 'blocked_by'] if remaining else []),
        *(['proportional_distance', 'target_distance', 'selection_cost'] if 'target_distance' in families else []),
        'qualifying_consistency', 'family', 'basis', 'median_separation', 'scenario'], column_config={
        'scenario': 'Source scenario', 'family': st.column_config.TextColumn('Family', width='small'),
        'basis': 'Coverage basis', 'included_characters': st.column_config.NumberColumn('Characters', width='small'),
        'member_names': st.column_config.TextColumn('Members', width='large'),
        'qualifying_consistency': st.column_config.NumberColumn('Pair consistency', format='percent', width='small'),
        'target_distance': st.column_config.NumberColumn('Size gap',
            help='Number of members below the ideal minimum or above the ideal maximum; zero within the preferred range.'),
        'selection_cost': st.column_config.NumberColumn('Greedy family cost', format='%.2f',
                                                       help='1 + (1 - consistency) + 10 x preference x proportional size distance. Lower is better before accounting for newly covered characters.'),
        'proportional_distance': st.column_config.NumberColumn('Proportional size gap', format='%.2f',
            help='Zero inside the ideal range. One means half the minimum or twice the maximum; two means a factor of four.'),
        'new_characters': 'Additional characters', 'blocked_by': 'First blocking limit',
        'cost_per_new_character': st.column_config.NumberColumn('Cost / additional character', format='%.3f'),
        'median_separation': st.column_config.NumberColumn('Original median separation', format='percent')})


def _candidate_export(families: pd.DataFrame, cases: list[dict]) -> pd.DataFrame:
    context = pd.DataFrame([{'scenario_id': case['id'], **_export_context(case)} for case in cases])
    return families.drop(columns='member_keys').merge(context, on='scenario_id', how='left')


def _viable_families(families: pd.DataFrame, cases: list[dict], universe: pd.DataFrame) -> None:
    st.caption('All qualifying candidates, including alternatives omitted from the suggestion and families outside the size '
               'limits. Families can overlap or repeat across scenarios. High mean cohesion can include a weak member or '
               'a group that repeatedly merges with another; inspect separation and the heatmap before choosing.')
    columns = st.columns(2)
    basis = columns[0].selectbox('Candidate basis', ['Full + retained', 'Full families only', 'Retained only'],
                                  key='batch_candidate_basis')
    search = columns[1].multiselect('Find families containing any of these characters',
                                      universe.sort_values('character').character.tolist(), key='batch_candidate_search')
    rows = families
    if basis != 'Full + retained':
        rows = rows.loc[rows.basis.eq('Full family' if basis == 'Full families only' else 'Retained members only')]
    if search:
        keys = set(universe.loc[universe.character.isin(search), 'character_key'])
        rows = rows.loc[rows.member_keys.map(lambda members: bool(keys.intersection(members)))]
    st.write(f'{len(rows)} viable families shown · {len(families)} available in this batch')
    _candidate_table(rows)
    if search and not rows.empty:
        sources = sources_from_cases(cases)
        source_ids = {case['id']: fingerprint(case['scenario']) for case in cases}
        keys = set(universe.loc[universe.character.isin(search), 'character_key'])
        fits = []
        for family in rows.itertuples():
            scores, mean = subset_scores(sources[source_ids[family.scenario_id]], family.member_keys)
            fits.extend(scores.loc[scores.character_key.isin(keys)].assign(
                family=family.family, scenario=family.scenario, basis=family.basis, family_mean=mean).to_dict('records'))
        st.markdown('**Character fit within the included members**')
        st.dataframe(pd.DataFrame(fits), hide_index=True, width='stretch', column_order=[
            'character', 'family', 'scenario', 'basis', 'member_fit', 'family_mean', 'peer_support', 'weakest_pair'],
            column_config={field: st.column_config.NumberColumn(label, format='percent') for field, label in [
                ('member_fit', 'Character fit'), ('family_mean', 'Family consistency'),
                ('peer_support', 'Peers reaching 80%'), ('weakest_pair', 'Weakest pair')]})
        st.caption('Each row scores one searched character against the actual included peers. Retained-family scores exclude removed members.')
    st.download_button('Download all viable families CSV', _candidate_export(families, cases).to_csv(index=False).encode(),
                         file_name='batch-all-viable-families.csv', mime='text/csv')
    if rows.empty:
        st.info('No viable families match these filters.')
        return
    with st.expander('Inspect a viable family'):
        rows = rows.sort_values(['included_characters', 'qualifying_consistency'], ascending=[True, False])
        lookup = rows.set_index('family_id')
        selected = st.selectbox('Viable family', rows.family_id.tolist(), key='batch_candidate_inspect',
                                 format_func=lambda key: f'{lookup.loc[key, "included_characters"]} characters · '
                                                        f'{lookup.loc[key, "scenario"]} · {lookup.loc[key, "family"]} · '
                                                        f'{lookup.loc[key, "basis"]}')
        family = lookup.loc[selected]
        st.write(family.member_names)
        result = next(case['result'] for case in cases if case['id'] == family.scenario_id)
        members = result['characters'].loc[result['characters'].character_key.isin(family.member_keys)]
        st.plotly_chart(co_membership_figure(members, result['rates']), width='stretch', key='batch_candidate_heatmap')
        st.caption('Only included members are shown. Retained-only candidates exclude the removed outliers. '
                   'This reuses the source scenario\'s bootstrap pairs; it does not refit or jointly validate families from different scenarios.')


def _comparison(cases: list[dict], target: float) -> None:
    st.subheader('Scenario comparison')
    rows = [{'Scenario': case['name'], **case['result']['summary'], **_export_context(case)} for case in cases]
    comparison = pd.DataFrame(rows)
    st.dataframe(comparison, hide_index=True, width='stretch', column_order=[
        'Scenario', 'families', *FAMILY_BANDS, *STATES, 'characters', 'character_coverage'], column_config={
            'Scenario': st.column_config.TextColumn('Scenario', width='medium'), 'families': 'Families',
            'Full family meets target': f'Full ≥ {target:.0%}', 'Retained members only': 'Retained only',
            'Below target': 'Below', 'No peer score': 'No score', 'characters': 'Characters',
            'character_coverage': st.column_config.NumberColumn('Character coverage', format='percent'),
        })
    st.caption(f'Full: original mean pair consistency ≥ {target:.0%}. Retained only: full mean is below target, '
               'but the blue-diamond mean after weakest-member removal reaches it. Below: neither reaches target. '
               'No peer score is separate. Separation is available in detail and does not change these categories. '
               'Final assignments use the shared batch rules; Both is evaluated before the two single-family states.')
    for column, fields, title, colors in zip(st.columns(2), [FAMILY_BANDS, STATES],
                                            ['Original-family consistency', 'Final assignment states'],
                                            [['#58b798', '#4ea5d9', '#d38574', '#778797'],
                                             ['#58b798', '#d8a52d', '#4ea5d9', '#778797']], strict=True):
        figure = go.Figure()
        labels = [f'{index+1} · {case["name"].removeprefix("!").split("-Boot")[0][:42]}' for index, case in enumerate(cases)]
        for field, color in zip(fields, colors, strict=True):
            legend_label = {'Full family meets target': 'Full', 'Retained members only': 'Retained only',
                            'Below target': 'Below', 'No peer score': 'No score'}.get(field, field)
            figure.add_trace(go.Bar(x=comparison[field], y=labels, name=legend_label, orientation='h',
                                    marker_color=color, text=comparison[field].where(comparison[field].ne(0), ''),
                                    textposition='auto', customdata=comparison.Scenario,
                                    hovertemplate='%{customdata}<br>%{fullData.name}: %{x}<extra></extra>'))
        figure.update_layout(title=title, barmode='stack', height=min(1100, max(320, len(cases)*42+120)),
                             legend=dict(orientation='h', y=-.18), margin=dict(l=5, r=5, t=40, b=20))
        figure.update_yaxes(autorange='reversed', tickfont=dict(size=10))
        figure.update_xaxes(title='Families' if fields == FAMILY_BANDS else 'Characters', rangemode='tozero', dtick=1 if fields == FAMILY_BANDS else None)
        column.plotly_chart(figure, width='stretch', key=f'batch_comparison_{title}')
    columns = st.columns(3)
    columns[0].download_button('Download comparison CSV', comparison.to_csv(index=False).encode(),
                               file_name='batch-scenario-comparison.csv', mime='text/csv')
    for column, name, field, filename in [(columns[1], 'Download all final assignments', 'final', 'batch-final-assignments.csv'),
                                         (columns[2], 'Download all family metrics', 'families', 'batch-family-consistency.csv')]:
        export = pd.concat([case['result'][field].assign(scenario=case['name'], **_export_context(case)) for case in cases], ignore_index=True)
        column.download_button(name, export.to_csv(index=False).encode(), file_name=filename, mime='text/csv')


def _export_context(case: dict) -> dict:
    source, evidence = case['scenario']['source'], case['evidence']
    return dict(case['result']['rules'], bootstrap_repeats=evidence['repetitions'], repeat_seed=evidence['repeat_seed'],
                profiles=evidence['profiles'], rank_tiers='/'.join(source['tiers']), tracking_history=source['maturity'],
                membership_sha256=source['membership_sha256'], reference_sha256=source['reference_sha256'])


def _scenario_details(case: dict, target: float, expanded: bool) -> None:
    result, evidence, scenario = case['result'], case['evidence'], case['scenario']
    summary = result['summary']
    label = (f'{case["name"]} · full {summary[FAMILY_BANDS[0]]} / retained {summary[FAMILY_BANDS[1]]} '
             f'/ below {summary[FAMILY_BANDS[2]]}')
    section = st.container(border=True) if expanded else st.expander(label)
    with section:
        if expanded:
            st.markdown(f'**{label}**')
        st.caption(f"{evidence['repetitions']} player-bootstrap repeats · seed {evidence['repeat_seed']} · "
                   f"{evidence['evidence_origin']} · {evidence['profiles']:,} profiles · "
                   f"{len(scenario['source']['tiers'])} rank tiers · {scenario['source']['maturity']} tracking history. "
                   'Cohorts and discovery settings can differ between scenarios.')
        st.markdown('**Consistency of each original family**')
        if result['families'].empty:
            st.info('No accepted original families in this scenario.')
        else:
            st.plotly_chart(family_consistency_figure(result['families'], result['characters'], target),
                            width='stretch', key=f'batch_family_plot_{case["id"]}')
            st.caption('Gold = full-family mean pair consistency; blue = retained members only. Small points show characters. '
                       'Removal is a diagnostic on the same repeats, not independent validation. High cohesion can still overlap another family.')
            st.dataframe(result['families'], hide_index=True, width='stretch', column_order=[
                'family', 'consistency_band', 'characters', 'mean_consistency', 'retained_consistency',
                'uplift_pp', 'removed_members', 'median_separation', 'pattern'], column_config={
                    'family': 'Family', 'consistency_band': 'Cohesion category', 'characters': 'Characters',
                    'mean_consistency': st.column_config.NumberColumn('Full mean', format='percent'),
                    'retained_consistency': st.column_config.NumberColumn('Retained mean', format='percent'),
                    'uplift_pp': st.column_config.NumberColumn('Gain (pp)', format='%+.1f'),
                    'median_separation': st.column_config.NumberColumn('Median separation', format='percent'),
                    'removed_members': 'Weakest members', 'pattern': 'Review pattern',
                })
        st.markdown('**Bootstrap co-membership heatmap**')
        choices = ['All families'] + sorted(set(result['characters'].family))
        selected = st.selectbox('Heatmap family', choices, key=f'batch_heatmap_family_{case["id"]}')
        st.plotly_chart(co_membership_figure(result['characters'], result['rates'], selected),
                        width='stretch', key=f'batch_heatmap_{case["id"]}')
        st.caption('Darker blocks mean characters repeatedly stay together. The hidden diagonal excludes self-pairs; '
                   'two unassigned characters never count as companions. Select one family for readable labels.')
        with st.expander('Final character assignments'):
            st.dataframe(result['final'], hide_index=True, width='stretch', height=350, column_order=[
                'character', 'state', 'final_primary', 'final_secondary', 'own_consistency', 'alternative_consistency',
                'original_family', 'alternative_family', 'assigned_rate'], column_config={
                    'character': 'Character', 'state': 'State', 'final_primary': 'Final primary', 'final_secondary': 'Final secondary',
                    'original_family': 'Original family', 'alternative_family': 'Original alternative',
                    'own_consistency': st.column_config.NumberColumn('Original consistency', format='percent'),
                    'alternative_consistency': st.column_config.NumberColumn('Alternative consistency', format='percent'),
                    'assigned_rate': st.column_config.NumberColumn('Assigned rate', format='percent'),
                })
