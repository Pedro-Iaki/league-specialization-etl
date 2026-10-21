"""Interactive local review page for candidate character families."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core.families import (
    LOCAL_DIR, FamilySettings, discover_families, family_affinities, family_consistency, load_membership,
    prepare_membership, refine_memberships, scenario_payload, stability_check, summarize_family_consistency,
    summarize_stability, validate_scenario,
)
from app_core.family_plots import co_membership_figure, family_consistency_figure
from app_core.population import ALL_TIERS, WEIGHT
from app_core.ui import setup_page


@st.cache_data(show_spinner=False)
def _prepared(snapshot_version: int):
    frame, manifest = load_membership()
    return (*prepare_membership(frame), manifest)


def render_family_lab() -> None:
    setup_page('Character family laboratory')
    st.subheader('Character family laboratory')
    st.markdown('''<style>
    .st-key-family_filters [data-testid=stSliderTickBar] {display:none;}
    .st-key-family_dashboard_summary [data-testid=stMetric] {min-height:0;padding:.35rem .5rem;border-radius:8px;}
    .st-key-family_dashboard_summary [data-testid=stMetricValue] {font-size:1.4rem;}
    .st-key-family_dashboard_summary [data-testid=stMetricLabel] p {font-size:.75rem;}
    .st-key-family_toolbar [data-testid=stMetric] {min-height:0;padding:.3rem .5rem;}
    .st-key-family_toolbar [data-testid=stMetricValue] {font-size:1.4rem;}
    .st-key-family_toolbar [data-testid=stMetricLabel] p {font-size:.75rem;}
    .st-key-family_cohesion [data-testid=stMetric] {min-height:0;padding:.4rem .6rem;}
    .st-key-family_cohesion [data-testid=stMetricValue] {font-size:1.4rem;}
    @media (max-width:640px) {
      .st-key-family_metrics_seed [data-testid=stHorizontalBlock],
      .st-key-family_metrics_bootstrap [data-testid=stHorizontalBlock] {flex-wrap:wrap;gap:.4rem;}
      .st-key-family_metrics_seed [data-testid=stColumn],
      .st-key-family_metrics_bootstrap [data-testid=stColumn] {
        flex:1 1 calc(50% - .4rem)!important;min-width:calc(50% - .4rem)!important;width:calc(50% - .4rem)!important;
      }
    }
    </style>''', unsafe_allow_html=True)
    path = LOCAL_DIR / 'membership.parquet'
    if not path.exists():
        st.info('Export the local membership snapshot before running this laboratory.')
        st.code('.venv/Scripts/python.exe -m pip install -r streamlit_app/requirements-families.txt\n'
                '.venv/Scripts/python.exe streamlit_app/scripts/export_character_families.py')
        return
    try:
        import leidenalg  # noqa: F401
        base, characters, points, reference, manifest = _prepared(path.stat().st_mtime_ns)
    except ImportError:
        st.error('Install streamlit_app/requirements-families.txt in the dashboard environment.')
        return
    except (ValueError, OSError, KeyError) as error:
        st.error(str(error))
        return
    scenario_tools = st.columns(2)
    with scenario_tools[0]:
        _scenario_import(characters, manifest)
    save_slot = scenario_tools[1].expander('Save a scenario')
    filters_slot = st.container()
    family_review_slot = st.container()
    toolbar = st.container()
    summary_slot = st.empty()
    refinement_slot = st.expander('3 · Refine overlapping memberships')
    with st.container():
        st.caption(f"Membership as of {manifest['max_as_of_date']} · {len(base):,} base profiles · "
                   f"{len(characters)} characters · reference coverage {reference['reference_covered_share']:.2%}")
        with st.expander('How to explore and interpret this page'):
            st.markdown('Start with Jaccard, inspect a family and its outside neighbors, then vary resolution and support. '
                        'Compare the breadth-adjusted view and run stability checks before choosing titles. '
                        'Smaller resolution usually favors wider groups. More mutual-neighbor restrictions favor tighter neighborhoods. '
                        'Family IDs are specific to a scenario; names need your review.')
            st.markdown('For questionable placements, first try maximum family size 0 (unlimited), keep pairs/trios visible, '
                        'and compare reciprocal connections on and off. Change one control at a time. A hard size cap can '
                        'split coherent groups; a bridge can reflect a real shared audience without matching a gameplay label. '
                        'Hover over each control’s question mark for its practical effect and tradeoffs.')
            st.markdown('Membership uses the existing active pool: short-history 30-day recency; mature 60-day/gain rules. '
                        'Mastery is accumulated experience within that pool. Character types and families are separate. '
                        'Reference weights are frozen before filters; weighting cannot fix all collection bias. '
                        'The saved reference values are accepted as OP.GG-attributed; legacy seed metadata has not been rewritten here.')
            st.link_button('Population reference source', 'https://op.gg/lol/statistics/tiers')

    with filters_slot, st.container(border=True, key='family_filters'):
        columns = st.columns(4)
        association = columns[0].selectbox('Association method', ['jaccard', 'breadth_adjusted'],
                                     format_func=lambda x: {'jaccard': 'Observed repertoire (Jaccard)',
                                                            'breadth_adjusted': 'Specific affinity (breadth-adjusted)'}[x],
                                     key='family_association',
                                     help='Jaccard finds shared repertoires: shared players divided by players of either character. Breadth-adjusted emphasizes connections stronger than expected among similarly broad pools. The adjusted result answers a different question, not an automatically better one.')
        resolution = columns[1].slider('Family resolution', 0.05, 5.0, 1.0, 0.05, key='family_resolution',
                                  help='Lower values usually form broader families; higher values split them into narrower groups. It controls detail, not accuracy. Compare nearby values before choosing a family name.')
        neighbors = columns[2].slider('Strongest neighbors', 1, 172, 10, key='family_neighbors',
                                  help='Keep up to this many strongest connections for each character. Fewer emphasizes local neighborhoods; more preserves broad links but can create bridges. Fewer is not always better.')
        similarity = columns[3].slider('Minimum Jaccard similarity', 0.0, 1.0, 0.03, 0.01, key='family_minimum_similarity',
                                       help='Minimum shared-audience fraction of the combined audience. 0.10 means 10% of players in either audience belong to both. Raising it removes weaker overlaps. It also applies in adjusted mode.')
        columns = st.columns([1, 1, 2])
        minimum_size = columns[0].number_input('Minimum family size', 2, 173, 3, key='family_minimum_family_size',
                                          help='After discovery, groups smaller than this become Unassigned. It does not merge them into larger families. Use a smaller value when exploring genuine pairs or trios.')
        maximum_size = columns[1].number_input('Maximum family size', 0, 173, 0,
                                          key='family_maximum_family_size',
                                          help='Hard limit on how many characters a detected family may contain. A small cap can split coherent families and distort borderline placements. Start at 0 (unlimited); split broad families after reviewing them.')
        mutual = columns[2].checkbox('Require reciprocal strongest-neighbor connections', key='family_mutual_neighbors',
                                    help='Keep a connection only when both characters place each other among their strongest neighbors. This can reduce one-sided bridges, but may isolate niche characters or remove useful links.')
        advanced, apply = st.columns([3, 1], vertical_alignment='center')
        with advanced.expander('Audience filters and advanced connections'):
            columns = st.columns(3)
            tiers = columns[0].multiselect('Rank tiers', ALL_TIERS, default=ALL_TIERS, key='family_tiers',
                                     help='Choose whose character choices build the families. A rank-specific result may differ from the overall audience.')
            maturity = columns[1].selectbox('Tracking history', ['All', 'Under 30 days', '30 days or more'], key='family_maturity',
                                        help='How long we have observed the profile, not how long the person has played. The two groups use different active-pool rules.')
            weighted = columns[2].checkbox('Use reference population weights', value=True, key='family_population_weighted',
                                       help='Adjust the influence of rank tiers toward the saved reference. Switching this off gives every observed profile equal influence. This cannot remove all collection bias.')
            excluded = st.multiselect('Exclude characters from discovery', characters.character.tolist(), key='family_excluded',
                                       help='Temporarily remove characters and their graph connections. Useful for testing whether one bridge drives a placement. This is a sensitivity check, not a reason to permanently delete awkward cases.')
            columns = st.columns(4)
            mastery = columns[0].number_input('Minimum mastery', 0, 10_000_000, 15000, 5000,
                                    key='family_minimum_mastery',
                                    help='Ignore active characters below this accumulated mastery when building connections. Higher values emphasize established experience but can hide genuine secondary choices.')
            support = columns[1].number_input('Minimum character support', 1, 1000000, 30, key='family_minimum_players',
                                      help='A character needs this many observed qualifying players to enter discovery. Raising it removes poorly supported characters; it does not make the others automatically reliable.')
            shared = columns[2].number_input('Minimum shared profiles', 1, 1000000, 10, key='family_minimum_shared',
                                     help='A connection needs this many observed players who qualify for both characters. Raising it removes rare connections and can hide smaller families.')
            seed = columns[3].number_input('Random seed', 0, 2**31-1, 42, key='family_seed',
                                       help='Controls the algorithm’s repeatable starting randomness. It does not change the evidence. Try several seeds to check whether a placement is fragile; do not pick a lucky seed just for preferred results.')
        submitted = apply.button('Find candidate families', key='family_find')

    with toolbar, st.container(key='family_toolbar'):
        controls = st.columns([2, 1, 1.5, 1.5, 1], vertical_alignment='bottom')
        auto = controls[0].toggle('Automatic stability checks', value=False, key='family_auto_checks',
                                  help='Apply discovery-setting changes immediately and run both seed and player-bootstrap checks. Changing repetitions also refreshes both. Review targets, plot selections, names and other cosmetic edits reuse existing results.')
        repetitions = controls[1].number_input('Repeats per check', 2, 50, 10, key='family_repetitions',
                                               help='Both checks use this many repeats. Start with 10 while exploring; player-bootstrap checks take longer than discovery.')
        target = controls[2].slider('Co-member review target', 0.0, 1.0, 0.8, 0.05, key='family_stability_target',
                                     help='Your working target, not a validated pass/fail boundary. Changing this only updates summaries and plot markers.')
        check_requested = controls[3].button('Run both stability checks', type='primary', key='family_run_checks')
        count_slot = controls[4].empty()

    try:
        settings = FamilySettings(mastery, support, shared, similarity, neighbors, mutual, resolution,
                                  minimum_size, maximum_size, seed, association, weighted)
    except ValueError as error:
        summary_slot.warning(str(error))
        return
    selected = base.tier.isin(tiers).to_numpy()
    if maturity != 'All':
        selected &= (base.days_tracked.lt(30) if maturity == 'Under 30 days' else base.days_tracked.ge(30)).to_numpy()
    excluded_keys = tuple(int(x) for x in characters.loc[characters.character.isin(excluded), 'character_key'])
    context = dict(reference, membership_sha256=manifest['sha256'], exported_at_utc=manifest['exported_at_utc'],
                   tiers=tiers, maturity=maturity, excluded_keys=list(excluded_keys), profiles=int(selected.sum()))
    signature = hashlib.sha256(json.dumps([asdict(settings), context], sort_keys=True).encode()).hexdigest()
    previous = st.session_state.get('family_run')
    changed = previous is None or signature != previous['signature']
    if submitted or previous is None or (changed and (auto or check_requested)):
        if not selected.any():
            summary_slot.warning('No profiles match these filters. Choose at least one supported tier.')
            return
        with st.spinner('Finding candidate families…'):
            weights = base.loc[selected, WEIGHT].to_numpy() if weighted else np.ones(selected.sum())
            try:
                result = discover_families(points[selected], characters, weights, settings, excluded_keys)
            except ValueError as error:
                st.warning(str(error))
                return
        st.session_state['family_run'] = dict(result=result, settings=settings, context=context, selected=selected,
                                             weights=weights, excluded=excluded_keys, signature=signature)
        st.session_state.pop('family_stability_checks', None)
        imported = st.session_state.get('family_imported')
        if imported and imported['source'] == context and imported['settings'] == asdict(settings):
            saved = imported.get('stability_checks', {})
            if not saved and imported.get('stability'):
                legacy = imported['stability']
                saved = {'bootstrap' if legacy.get('mode') == 'Whole-player bootstrap' else 'seed': legacy}
            st.session_state['family_stability_checks'] = {
                key: report for key, report in saved.items()
                if key in {'seed', 'bootstrap'} and report.get('signature') == signature
            }
    run = st.session_state['family_run']
    if run['context']['membership_sha256'] != manifest['sha256']:
        summary_slot.warning('The membership snapshot changed. Run discovery again before reviewing this scenario.')
        return
    pending = signature != run['signature']
    automatic = run['result']['assignments']
    count_slot.metric('Candidate families', automatic.loc[automatic.family.ne('Unassigned'), 'family'].nunique(),
                      help='Automatic family count. Manual edits do not change the stability baseline.')
    checks = st.session_state.get('family_stability_checks', {})
    current_checks = {key: report for key, report in checks.items()
                      if report['signature'] == run['signature'] and report['repetitions'] == repetitions}
    if check_requested or (auto and len(current_checks) < 2):
        summary_slot.info('Updating seed and player-bootstrap stability for the displayed definition...')
        for key, label, bootstrap in [('seed', 'Random seeds only', False), ('bootstrap', 'Whole-player bootstrap', True)]:
            if not check_requested and key in current_checks:
                continue
            with st.spinner(f'Running {label.lower()} - {repetitions} repeats...'):
                report = stability_check(points[run['selected']], characters, run['weights'], run['settings'],
                                         run['result']['assignments'], run['excluded'], repetitions, bootstrap,
                                         discovery=run['result'])
            current_checks[key] = {'signature': run['signature'], 'mode': label, 'repetitions': repetitions,
                                   'metric_version': 2,
                                   'co_membership': report.attrs['co_membership'],
                                   'rows': report.astype(object).where(report.notna(), None).to_dict('records')}
            st.session_state['family_stability_checks'] = current_checks.copy()
    summary_slot.empty()
    with family_review_slot:
        _family_consistency_overview(current_checks.get('bootstrap'), automatic, target, pending)
    with summary_slot.container():
        _stability_dashboard(run, current_checks, target, repetitions, pending)
    with refinement_slot:
        refinement = _refinement_review(current_checks.get('bootstrap'), automatic, run['signature'])
    _consistency_review(current_checks.get('bootstrap'), run['result']['assignments'])
    _review_run(run, characters, points, base, current_checks, target, save_slot, refinement)


def _family_consistency_overview(check: dict | None, automatic: pd.DataFrame, target: float, pending: bool) -> None:
    with st.container(key='family_cohesion'):
        st.markdown('**2 · Consistency of each original family**')
        with st.expander('Family review settings'):
            columns = st.columns(2)
            trim = columns[0].slider('Weakest-member removal for comparison', 0.0, .4, .2, .05, key='family_trim_fraction',
                                     help='Temporarily remove this fraction of the least consistent original members, rounded up, keeping at least two. This is a sensitivity comparison; it does not change any assignment.')
            gap = columns[1].slider('Family separation target', 0.0, 1.0, .2, .05, key='family_overview_gap',
                                    help='Median own-family consistency minus strongest-alternative consistency. A cohesive family can still overlap another family. This is your review target, not validated confidence.')
        if not check or not check.get('co_membership'):
            st.info('Run both stability checks below to see family cohesion and weakest-member sensitivity. Older saved checks need a new run for pair evidence.')
            return
        if pending:
            st.caption('Showing the last computed definition; pending discovery filters have not been applied.')
        families, characters = summarize_family_consistency(check['co_membership'], automatic, target, trim, gap)
        if families.empty:
            st.info('No accepted original families to compare.')
            return
        cohesive = families.mean_consistency.ge(target) & families.median_separation.ge(gap)
        sensitive = families.pattern.eq('Sensitive to weakest members')
        columns = st.columns(3)
        columns[0].metric('Cohesive & separated', f'{int(cohesive.sum())}/{len(families)}')
        columns[1].metric('Weak-member sensitive', int(sensitive.sum()))
        columns[2].metric('Loose / overlapping', int((~cohesive & ~sensitive).sum()))
        figure = family_consistency_figure(families, characters, target)
        st.plotly_chart(figure, width='stretch', key='family_cohesion_plot', config={'displayModeBar': False})
        st.caption(f"{check['repetitions']} player-bootstrap repeats · each point is a character; pink is below {target:.0%}. "
                   'Gold is the mean pair consistency of the complete family; blue recalculates it within the retained members. '
                   'A large gain suggests peripheral drag; a low retained score suggests broader instability or subgroups. '
                   'High cohesion with little separation can reflect families repeatedly merging.')
        with st.expander('Family metrics and possible problem characters'):
            st.dataframe(families, hide_index=True, width='stretch', column_order=[
                'family', 'pattern', 'characters', 'mean_consistency', 'retained_consistency', 'uplift_pp',
                'weak_members', 'removed_count', 'removed_members', 'median_separation',
                'median_consistency', 'p10_consistency', 'weak_share', 'retained_count'], column_config={
                **{column: st.column_config.NumberColumn(label, format='percent') for column, label in [
                    ('mean_consistency', 'Full-family consistency'), ('median_consistency', 'Median member'),
                    ('p10_consistency', 'P10 member'), ('weak_share', 'Share below target'),
                    ('median_separation', 'Median separation'), ('retained_consistency', 'Retained consistency')]},
                'uplift_pp': st.column_config.NumberColumn('Gain (pp)', format='%+.1f'),
                'removed_members': 'Weakest members removed for comparison', 'pattern': 'Review pattern',
                'family': 'Family', 'characters': 'Characters', 'weak_members': 'Below target',
                'removed_count': 'Removed', 'retained_count': 'Retained',
            })
            st.caption('Weakest members are selected from these same repeats. The comparison diagnoses sensitivity; '
                       'it is not independent validation of a cleaned family. Small groups may lose more than the selected fraction '
                       'because removal rounds up; pairs are never reduced. Original membership and all full-group values remain visible.')


def _refinement_review(check: dict | None, automatic: pd.DataFrame, signature: str) -> dict | None:
    st.caption('Generate a separate final membership view from the original groups and their player-bootstrap pair evidence. '
               'The strongest alternative is the only secondary candidate; at most two families are retained per character.')
    columns = st.columns(2)
    single = columns[0].slider('Single-family threshold', 0.0, 1.0, .8, .05, key='family_refine_single')
    shared = columns[1].slider('Both-families threshold (each)', 0.0, 1.0, .4, .05, key='family_refine_shared')
    st.caption('Rules run in this order: both scores meet the shared threshold → Both; otherwise the original score '
               'meets the single threshold → Primary only; otherwise the alternative meets it → Secondary only; otherwise Indecisive. '
               'The higher-scoring family becomes final primary when both qualify. Zero evidence never creates membership.')
    available = bool(check and check.get('co_membership'))
    if shared > single:
        st.warning('The both-families threshold must not exceed the single-family threshold.')
    generate = st.button('Generate final assignments', key='family_refine_generate', disabled=not available or shared > single)
    if not available:
        st.info('Run the player-bootstrap check to generate final assignments.')
        return None
    source = hashlib.sha256(json.dumps([signature, check['co_membership']], sort_keys=True).encode()).hexdigest()
    request = {'source': source, 'rules': {'single_threshold': single, 'shared_threshold': shared}}
    if generate:
        st.session_state['family_refinement_request'] = request
    if st.session_state.get('family_refinement_request') != request or shared > single:
        st.info('Generate final assignments for the current bootstrap evidence and thresholds. Changing either requires regeneration.')
        return None
    consistency, _ = family_consistency(check['co_membership'], automatic)
    final = refine_memberships(consistency, single, shared)
    for column, state in zip(st.columns(4), ['Primary only', 'Secondary only', 'Both', 'Indecisive'], strict=True):
        column.metric(state, int(final.state.eq(state).sum()))
    st.dataframe(final, hide_index=True, width='stretch', height=300, column_order=[
        'character', 'state', 'final_primary', 'final_secondary', 'own_consistency',
        'alternative_consistency', 'original_family', 'alternative_family', 'assigned_rate'], column_config={
        'character': 'Character', 'state': 'Assignment state', 'final_primary': 'Final primary',
        'final_secondary': 'Final secondary', 'original_family': 'Original family', 'alternative_family': 'Original alternative',
        'own_consistency': st.column_config.NumberColumn('Original consistency', format='percent'),
        'alternative_consistency': st.column_config.NumberColumn('Alternative consistency', format='percent'),
        'assigned_rate': st.column_config.NumberColumn('Assigned rate', format='percent'),
    })
    memberships = []
    for row in final.itertuples():
        for position, family in [('Primary', row.final_primary), ('Secondary', row.final_secondary)]:
            if pd.notna(family):
                memberships.append({'character_key': row.character_key, 'character': row.character,
                                    'family': family, 'position': position,
                                    'consistency': row.own_consistency if family == row.original_family else row.alternative_consistency})
    st.download_button('Download final assignment review CSV', final.to_csv(index=False).encode(),
                       file_name='refined-family-assignments.csv', mime='text/csv', key='family_refine_download')
    st.caption('These scores are not exclusive probabilities. Dual qualification can reflect unstable merges as well as shared audiences; '
               'review separation and the pair heatmap. This operation does not independently validate its output. '
               'The final view is saved separately from the original discovery and the manual assignment editor; existing affinity charts use that editor.')
    return dict(request, rows=final.astype(object).where(final.notna(), None).to_dict('records'), memberships=memberships)


def _stability_dashboard(run: dict, checks: dict, target: float, repetitions: int, pending: bool) -> None:
    automatic = run['result']['assignments']
    assigned = automatic.family.ne('Unassigned')
    with st.container(key='family_dashboard_summary'):
        st.caption(f"{int(assigned.sum())}/{len(automatic)} characters assigned · "
                            f"{run['settings'].association} · resolution {run['settings'].resolution:g} · "
                            f"{run['settings'].neighbors} neighbors · review target {target:.0%}")
        if pending:
            st.info('Showing the last computed definition. Apply pending settings with Find candidate families or Run both stability checks.')
        panels = st.columns(2)
        for panel, key, label in zip(panels, ['seed', 'bootstrap'], ['Random seeds', 'Player bootstrap'], strict=True):
            with panel:
                st.markdown(f'**{label}** · {repetitions} repeats')
                check = checks.get(key)
                summary = summarize_stability(pd.DataFrame(check['rows']), automatic, target) if check else None
                if check:
                    check['summary'] = {k: v for k, v in summary.items() if k not in {'rows', 'families'}}
                values = [summary['mean_jaccard'] if summary else None,
                          summary['below_target_share'] if summary else None,
                          summary['mean_assigned_rate'] if summary else None,
                          summary['initial_coverage'] if summary else float(assigned.mean())]
                labels = ['Mean Jaccard', 'Below target', 'Assigned rate', 'Coverage']
                helps = [
                    'Mean co-member Jaccard across initially assigned characters. Higher means more consistent family neighbors.',
                    'Fraction of scored characters below your review target. This target is a review choice, not a universal pass/fail boundary.',
                    'Mean assignment retention: how often initially assigned characters stay in any accepted family. They can still change neighbors.',
                    'Initially assigned characters divided by all snapshot characters. This is character coverage, not player reach.',
                ]
                with st.container(key=f'family_metrics_{key}'):
                    for column, value, name, help_text in zip(st.columns([1.25, 1, 1, 1]), values, labels, helps, strict=True):
                        column.metric(name, f'{value:.1%}' if value is not None else '—', help=help_text)
                if summary and summary['scored_characters']:
                    scored = summary['rows'].loc[lambda x: x.family.ne('Unassigned') & x.mean_comember_jaccard.notna()]
                    st.plotly_chart(_stability_distribution(scored, target, compact=True), width='stretch',
                                    key=f'family_compact_{key}', config={'displayModeBar': False})
                    st.caption(f"{summary['below_target']}/{summary['scored_characters']} below target · "
                               f"median {summary['median_jaccard']:.1%} · P10 {summary['p10_jaccard']:.1%}")
                elif check:
                    st.caption('No initially assigned characters have a co-member score.')
                else:
                    st.caption('Not run for these settings and repeat count. Enable automatic checks or run both above.')


def _stability_distribution(scored: pd.DataFrame, target: float, *, compact: bool = False) -> go.Figure:
    figure = go.Figure()
    labels = ['Jaccard', 'Assigned'] if compact else ['Co-member Jaccard', 'Assignment retention']
    for field, label in zip(['mean_comember_jaccard', 'assigned_rate'], labels, strict=True):
        available = scored.loc[scored[field].notna()]
        figure.add_trace(go.Box(x=available[field], name=label, orientation='h',
                               boxpoints='all', jitter=0.35, pointpos=0, boxmean=True,
                               text=available.character + ' · ' + available.family,
                               marker=dict(size=3 if compact else 6),
                               hovertemplate='%{text}<br>%{x:.1%}<extra>%{fullData.name}</extra>'))
    figure.update_layout(height=110 if compact else 340, showlegend=False,
                         margin=dict(l=5, r=5, t=5, b=5), font=dict(size=10 if compact else 12))
    figure.update_xaxes(title=None if compact else 'Character-level stability', range=[-0.03, 1.03], tickformat='.0%')
    figure.update_yaxes(categoryorder='array', categoryarray=labels, automargin=True)
    figure.add_shape(type='line', x0=target, x1=target, y0=-0.45, y1=0.45, xref='x', yref='y',
                     line=dict(dash='dot', color='#d8a52d'))
    return figure


def _consistency_review(check: dict | None, automatic: pd.DataFrame) -> None:
    st.subheader('Family cores and flexible members')
    if not check or not check.get('co_membership'):
        st.info('Run both stability checks to collect pair consistency. Older saved checks retain their summaries but need a new run for this view.')
        return
    try:
        rows, rates = family_consistency(check['co_membership'], automatic)
    except (ValueError, KeyError, TypeError) as error:
        st.warning(f'Pair consistency unavailable: {error}. Run both stability checks again.')
        return
    st.caption(f"Player bootstrap · {check['repetitions']} repeats. Own consistency is the average frequency of joining "
               'the other original family members; alternative consistency uses the strongest other original family. '
               'All repeats count, including unassigned outcomes. Separation is own minus alternative, in percentage points. '
               'Self-pairs and shared Unassigned labels never count as companionship.')
    with st.expander('Adjust review highlights'):
        columns = st.columns(3)
        minimum = columns[0].slider('Strong own-family consistency', 0.0, 1.0, .8, .05, key='family_core_minimum')
        gap = columns[1].slider('Clear separation from alternatives', 0.0, 1.0, .2, .05, key='family_core_gap')
        retention = columns[2].slider('Reliable assigned rate', 0.0, 1.0, .8, .05, key='family_core_retention')
    def signal(row):
        if pd.isna(row.own_consistency):
            return 'No original peers'
        if row.assigned_rate < retention:
            return 'Frequent unassignment'
        if row.separation < -gap:
            return 'Alternative stronger'
        if row.own_consistency < minimum:
            return 'Weak own-family ties'
        if pd.notna(row.separation) and row.separation < gap:
            return 'Close alternative'
        return 'Strong core signal'
    rows['review_signal'] = rows.apply(signal, axis=1)
    families = sorted(set(rows.family) - {'Unassigned'})
    choices = ['All families'] + families + (['Unassigned'] if rows.family.eq('Unassigned').any() else [])
    selected = st.selectbox('Original family to review', choices, key='family_core_selection')
    selected_rows = rows if selected == 'All families' else rows.loc[rows.family.eq(selected)]
    selected_rows = selected_rows.sort_values(['family', 'own_consistency', 'character'], ascending=[True, False, True])
    display_rows = selected_rows.assign(separation=selected_rows.separation * 100)
    st.dataframe(display_rows, hide_index=True, width='stretch', height=350,
                 column_order=['character', 'family', 'own_consistency', 'alternative_family', 'alternative_consistency',
                               'separation', 'assigned_rate', 'review_signal'],
                 column_config={
                     'character': 'Character', 'family': 'Original family', 'alternative_family': 'Strongest alternative',
                     'own_consistency': st.column_config.ProgressColumn('Own-family consistency', min_value=0, max_value=1, format='percent'),
                     'alternative_consistency': st.column_config.ProgressColumn('Alternative consistency', min_value=0, max_value=1, format='percent'),
                     'separation': st.column_config.NumberColumn('Separation (pp)', format='%+.1f', help='Subtract the two percentages: 80% minus 30% is +50 percentage points.'),
                     'assigned_rate': st.column_config.NumberColumn('Assigned rate', format='percent'),
                     'review_signal': 'Review highlight',
                 })
    st.caption('Highlights are adjustable review prompts, not membership verdicts. A coherent subgroup inside a divided '
               'family can have a low own-family average; look for blocks in the heatmap. Equally strong alternatives use the first family ID.')
    figure = co_membership_figure(rows, rates, selected)
    st.plotly_chart(figure, width='stretch', key='family_core_heatmap')
    st.caption('Darker blocks identify repeatable companionship. Order follows strongest remaining pair links within '
               'each original family; family boundaries are marked in the full view. Hover for exact pair rates. '
               'The diagonal is hidden. Select one family for readable labels; use the full view for bridges between families.')
    export_rows = rows.assign(separation_pp=rows.separation * 100).drop(columns='separation')
    st.download_button('Download character consistency CSV', export_rows.to_csv(index=False).encode(),
                       file_name='character-family-consistency.csv', mime='text/csv', key='family_core_download')


def _review_run(run: dict, characters: pd.DataFrame, points: np.ndarray, base: pd.DataFrame,
                checks: dict, target: float, save_slot, refinement: dict | None) -> None:
    result, settings, signature = run['result'], run['settings'], run['signature']
    automatic = result['assignments']
    st.subheader('Discovery overview')
    overview = []
    for family, group in automatic.loc[automatic.family.ne('Unassigned')].groupby('family'):
        indices = group.index.to_numpy()
        strength = result['stats']['jaccard'][np.ix_(indices, indices)].sum(axis=1)
        leaders = group.iloc[np.argsort(-strength)[:5]].character.tolist()
        overview.append({'family': family, 'characters': len(group), 'representative_characters': ', '.join(leaders)})
    if overview:
        st.dataframe(pd.DataFrame(overview), hide_index=True, width='stretch')
    st.caption(f"Displayed run: {run['context']['profiles']:,} profiles · "
               f"mastery ≥ {settings.minimum_mastery:,} · resolution {settings.resolution:g} · "
               f"{settings.association} · {'reference weighted' if settings.population_weighted else 'collected sample'}")
    imported = st.session_state.get('family_imported')
    imported_match = imported and imported['source'] == run['context'] and imported['settings'] == asdict(settings)
    initial = pd.DataFrame(imported['assignments']) if imported_match else automatic[['character_key', 'character', 'family']]
    st.subheader('Review assignments and name families')
    st.caption('Edit a family ID to move a character, create a new ID, or use Unassigned. '
               'These are manual overrides; discovery and stability diagnostics retain their automatic basis.')
    edited = st.data_editor(initial, disabled=['character_key', 'character'], hide_index=True,
                            width='stretch', height=300, key=f'family_assignments_{signature}',
                            column_config={'family': st.column_config.TextColumn('Family ID', required=True, max_chars=80)})
    if edited.family.isna().any() or not edited.family.map(lambda x: isinstance(x, str) and 0 < len(x.strip()) <= 80).all():
        st.warning('Use a nonempty family ID or Unassigned for every character.')
        return
    edited['family'] = edited.family.str.strip()
    families = sorted(set(edited.family) - {'Unassigned'})
    titles = pd.DataFrame([{'family': family, 'title': imported['families'].get(family, {}).get('title', family) if imported_match else family,
                            'description': imported['families'].get(family, {}).get('description', '') if imported_match else ''}
                           for family in families], columns=['family', 'title', 'description'])
    titles = st.data_editor(titles, disabled=['family'], hide_index=True, width='stretch',
                            key=f'family_titles_{signature}', column_config={
                                'title': st.column_config.TextColumn('Family title', required=True, max_chars=120),
                                'description': st.column_config.TextColumn('Why these characters belong together', max_chars=1000)})
    cols = st.columns(3)
    cols[0].metric('Assigned characters', int(edited.family.ne('Unassigned').sum()))
    cols[1].metric('Discovery edges', len(result['edges']))
    cols[2].metric('Manual changes', int(edited.family.ne(automatic.family).sum()))
    if families:
        _family_views(edited, titles, result, run, points, base)
    else:
        st.info('No families meet these constraints. Relax support, similarity, neighbor reciprocity or family size.')
    st.subheader('Detailed stability results')
    if checks:
        detail = st.selectbox('Detailed check', list(checks),
                              format_func=lambda key: {'seed': 'Random seeds', 'bootstrap': 'Player bootstrap'}[key],
                              key='family_detail_check')
        stability = checks[detail]
        st.caption(f"{stability['mode']} ? {stability['repetitions']} repeats. Co-member Jaccard compares family neighbors, "
                   'regardless of family ID. Diagnostics refer to automatic assignments, including when manual edits exist.')
        _stability_overview(stability, automatic, target)
    else:
        st.info('Run both checks above, or enable automatic stability checks.')
    with save_slot:
        _save_review(run, edited, titles, imported if imported_match else None, checks, refinement)


def _stability_overview(stability: dict, automatic: pd.DataFrame, target: float) -> None:
    summary = summarize_stability(pd.DataFrame(stability['rows']), automatic, target)
    st.caption(f"{summary['below_target']} of {summary['scored_characters']} scored characters below {target:.0%}; "
               f"{summary['initially_assigned']} of {summary['total_characters']} initially assigned. "
               'Each character has equal weight; initially unassigned characters have no original co-member score. '
               'These diagnostics measure repeatability, rather than gameplay correctness.')
    rows = summary['rows']
    scored = rows.loc[rows.family.ne('Unassigned') & rows.mean_comember_jaccard.notna()]
    if scored.empty:
        st.info('No initially assigned characters have a co-member score. Relax discovery constraints and repeat the check.')
    else:
        view = st.radio('Stability view', ['Distribution', 'Character relationships'], horizontal=True,
                         key='family_stability_view',
                         help='Distribution shows spread and outliers. Character relationships shows whether unstable neighbors coincide with characters losing their assignments.')
        figure = go.Figure()
        if view == 'Distribution':
            figure = _stability_distribution(scored, target)
            st.caption('Boxes show the middle half, the internal line is the median, and the dashed line is the mean. '
                       'Every point is a character. Vertical jitter only separates overlapping points; scores are unchanged.')
        else:
            for family, group in scored.groupby('family', sort=True):
                figure.add_trace(go.Scatter(x=group.mean_comember_jaccard, y=group.assigned_rate,
                                           mode='markers', name=family, text=group.character,
                                           marker=dict(size=9, opacity=0.7),
                                           hovertemplate='%{text}<br>Co-member Jaccard %{x:.1%}'
                                                         '<br>Assignment retention %{y:.1%}<extra>%{fullData.name}</extra>'))
            figure.update_layout(height=420, legend_title='Original family')
            figure.update_xaxes(title='Co-member Jaccard', range=[-0.03, 1.03], tickformat='.0%')
            figure.update_yaxes(title='Assignment retention', range=[-0.03, 1.03], tickformat='.0%')
            figure.add_vline(x=target, line_dash='dot', line_color='#d8a52d')
            st.caption('Upper right is consistently assigned with consistent neighbors. Upper left stays assigned '
                       'but changes neighbors. Lower values also indicate loss of accepted assignments. Exact ties overlap; hover to inspect.')
        figure.update_layout(margin=dict(l=10, r=10, t=15, b=10))
        st.plotly_chart(figure, width='stretch')
        st.caption('The dotted vertical line marks your co-member review target. Assignment retention measures '
                   'whether a character stays assigned anywhere, rather than whether it keeps the same neighbors.')
    with st.expander('Stability by original family'):
        if summary['families'].empty:
            st.info('No original families to summarize.')
        else:
            st.dataframe(summary['families'].sort_values('mean_comember_jaccard', na_position='last'),
                         hide_index=True, width='stretch', column_config={
                             'mean_comember_jaccard': st.column_config.NumberColumn('Mean co-member Jaccard', format='percent'),
                             'below_target_share': st.column_config.NumberColumn('Share below target', format='percent'),
                             'mean_assigned_rate': st.column_config.NumberColumn('Mean assignment retention', format='percent')})
    with st.expander('Per-character stability details'):
        st.dataframe(rows.sort_values('mean_comember_jaccard', na_position='last'), hide_index=True, width='stretch',
                     column_config={
                         'mean_comember_jaccard': st.column_config.NumberColumn('Co-member Jaccard', format='percent'),
                         'assigned_rate': st.column_config.NumberColumn('Assigned rate', format='percent')})


def _family_views(edited, titles, result, run, points, base):
    label_map = dict(zip(titles.family, titles.title.fillna(''), strict=True))
    family = st.selectbox('Inspect family', sorted(set(edited.family) - {'Unassigned'}),
                          format_func=lambda f: f'{f} · {label_map[f]}')
    selected = edited.family.eq(family).to_numpy()
    member_names = edited.loc[selected, 'character'].tolist()
    st.write(', '.join(member_names))
    stats = result['stats']
    order = np.flatnonzero(selected)
    # Include outside neighbors so a proposed family can be challenged visually.
    outside = np.flatnonzero(~selected)
    outside = sorted(outside, key=lambda i: -stats['jaccard'][i, selected].mean())[:8]
    order = np.r_[order, outside].astype(int)
    names = edited.iloc[order].character.tolist()
    fig = go.Figure(go.Heatmap(z=stats['jaccard'][np.ix_(order, order)], x=names, y=names,
                               zmin=0, zmax=1, colorscale='Blues', colorbar_title='Jaccard',
                               hovertemplate='%{y} ↔ %{x}<br>Jaccard %{z:.1%}<extra></extra>'))
    fig.update_layout(height=min(950, max(450, len(order)*23)), margin=dict(l=10, r=10, t=10, b=20))
    st.plotly_chart(fig, width='stretch')
    st.caption('Selected family first; up to eight strongest outside neighbors follow. '
               'The matrix shows observed Jaccard even when discovery uses adjusted edges. Diagonal omitted.')
    focus = st.selectbox('Inspect character connections', member_names)
    i = int(edited.index[edited.character.eq(focus)][0])
    connections = edited[['character', 'family']].copy()
    connections['shared_profiles'] = stats['raw'][i].astype(int)
    connections['jaccard'] = stats['jaccard'][i]
    connections['selected_to_other'] = stats['direction'][i]
    connections['other_to_selected'] = stats['direction'][:, i]
    connections['breadth_log2_ratio'] = stats['adjusted'][i]
    st.dataframe(connections.drop(index=i).sort_values('jaccard', ascending=False).head(25),
                 hide_index=True, width='stretch')
    affinities = family_affinities(points[run['selected']], edited, run['settings'].minimum_mastery)
    values = affinities[family].to_numpy()
    known = np.isfinite(values)
    weights = run['weights'][known]
    c1, c2, c3 = st.columns(3)
    c1.metric('Mean affinity among known pools', f'{np.average(values[known], weights=weights):.1%}' if known.any() else 'Unavailable')
    c2.metric('At least one qualifying family member',
              f'{np.average(values[known] > 0, weights=weights):.1%}' if known.any() else 'Unavailable')
    c3.metric('Profiles with known positive pool', f'{known.mean():.1%}')
    st.caption('Affinity sums qualifying characters’ Lifetime mastery divided by the full active-pool mastery. '
               'Below-cutoff and unassigned mass stays in the denominator. Prevalence and affinity answer different questions.')
    # Same all-member calculation grouped by rank, without joining public anonymous rows.
    rows = []
    tiers = base.loc[run['selected'], 'tier'].to_numpy()
    for tier in ALL_TIERS:
        mask = known & (tiers == tier)
        if mask.any():
            rows.append({'tier': tier, 'known_profiles': int(mask.sum()),
                         'mean_affinity': np.average(values[mask], weights=run['weights'][mask]),
                         'member_prevalence': np.average(values[mask] > 0, weights=run['weights'][mask])})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    with st.expander('Discovery edges and assignment support'):
        st.dataframe(result['edges'].sort_values('edge_weight', ascending=False), hide_index=True, width='stretch')
        st.dataframe(result['assignments'], hide_index=True, width='stretch')


def _suggest_scenario_name(run: dict, checks: dict, target: float) -> str:
    automatic = run['result']['assignments']
    assigned = automatic.family.ne('Unassigned')
    summaries = {key: summarize_stability(pd.DataFrame(check['rows']), automatic, target)
                 for key, check in checks.items()}
    def percentage(value):
        return f'{value * 100:.0f}' if value is not None else 'na'
    bootstrap, seed = summaries.get('bootstrap', {}), summaries.get('seed', {})
    settings = run['settings']
    parts = [f'F{automatic.loc[assigned, "family"].nunique()}',
             f'B{percentage(bootstrap.get("mean_jaccard"))}', f'S{percentage(seed.get("mean_jaccard"))}',
             f'U{percentage(bootstrap.get("below_target_share"))}', f'C{percentage(float(assigned.mean()))}',
             'J' if settings.association == 'jaccard' else 'BA',
             f'r{settings.resolution:g}', f'k{settings.neighbors}', f'j{settings.minimum_similarity:g}',
             'recip' if settings.mutual_neighbors else 'either']
    return '-'.join(parts).replace('.', 'p')


def _save_review(run, assignments, titles, imported, checks, refinement):
    st.subheader('Save a scenario for later use')
    if refinement is not None:
        st.caption('Includes the generated final membership view, thresholds and source evidence alongside the original/manual mapping.')
    elif st.session_state.get('family_refinement_request'):
        st.caption('No current final membership view is included. Regenerate under Refine overlapping memberships to include it.')
    notes = st.text_area('Review notes and remaining questions', value=imported.get('notes', '') if imported else '',
                         key=f"family_notes_{run['signature']}")
    name_column, auto_column = st.columns([3, 1], vertical_alignment='bottom')
    if auto_column.button('Auto-name scenario', key='family_autoname',
                          help='F = automatic families; B = bootstrap mean Jaccard; S = seed mean Jaccard; U = bootstrap share below the current review target; C = character coverage. Percentages are rounded; na means not measured. Also includes association, resolution, neighbors, minimum Jaccard and reciprocal/either connections. Full settings remain in the JSON.'):
        st.session_state['family_scenario_name'] = _suggest_scenario_name(run, checks, st.session_state['family_stability_target'])
    name = name_column.text_input('Scenario name', 'candidate-families', max_chars=80, key='family_scenario_name')
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in name):
        st.warning('Use letters, numbers, hyphens and underscores for the scenario name.')
        return
    if titles.title.isna().any() or titles.title.str.strip().eq('').any():
        st.warning('Give every family a title before saving.')
        return
    labels = {row.family: {'title': row.title, 'description': row.description or ''} for row in titles.itertuples()}
    # Keep the legacy single-check field readable by older review tools.
    stability = checks.get('bootstrap', checks.get('seed'))
    payload = scenario_payload(run['settings'], run['context'], assignments, labels, notes, stability)
    payload['stability_checks'] = checks
    automatic = run['result']['assignments'][['character_key', 'character', 'family']]
    payload['automatic_assignments'] = automatic.to_dict('records')
    payload['manual_overrides'] = assignments.loc[assignments.family.ne(automatic.family)].to_dict('records')
    if refinement is not None:
        payload['refinement'] = refinement
    content = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False, default=_json_value)
    st.download_button('Download complete scenario JSON', content, file_name=f'{name}.json', mime='application/json')
    st.download_button('Download named character mapping CSV',
                       assignments.assign(title=assignments.family.map({k: v['title'] for k, v in labels.items()})).to_csv(index=False),
                       file_name=f'{name}-mapping.csv', mime='text/csv')
    if refinement is not None:
        membership_rows = pd.DataFrame(refinement['memberships'], columns=['character_key', 'character', 'family', 'position', 'consistency'])
        st.download_button('Download refined memberships CSV', membership_rows.to_csv(index=False).encode(),
                           file_name=f'{name}-refined-memberships.csv', mime='text/csv')
    if st.button('Save scenario locally'):
        directory = LOCAL_DIR / 'scenarios'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{name}-{datetime_suffix()}.json'
        # Exclusive creation prevents accidental overwrite of a prior review.
        with path.open('x', encoding='utf-8') as target:
            target.write(content)
        st.success(f'Saved {path.relative_to(LOCAL_DIR.parent.parent)}')


def _scenario_import(characters: pd.DataFrame, manifest: dict) -> None:
    with st.expander('Load a saved scenario'):
        directory = LOCAL_DIR / 'scenarios'
        options = sorted(directory.glob('*.json')) if directory.exists() else []
        local = st.selectbox('Local saved scenarios', options, format_func=lambda p: p.name) if options else None
        upload = st.file_uploader('Or upload scenario JSON', type='json')
        if st.button('Load scenario'):
            if upload is None and local is None:
                st.warning('Select or upload a scenario first.')
                return
            try:
                payload = json.loads(upload.getvalue() if upload is not None else local.read_text(encoding='utf-8'))
                validate_scenario(payload, characters, manifest['sha256'])
                settings = FamilySettings(**payload['settings'])
                for key, value in asdict(settings).items():
                    st.session_state[f'family_{key}'] = value
                st.session_state['family_tiers'] = payload['source']['tiers']
                st.session_state['family_maturity'] = payload['source']['maturity']
                keys = payload['source']['excluded_keys']
                st.session_state['family_excluded'] = characters.loc[characters.character_key.isin(keys), 'character'].tolist()
                st.session_state['family_imported'] = payload
                st.session_state.pop('family_refinement_request', None)
                if payload.get('refinement'):
                    refinement = payload['refinement']
                    single = float(refinement['rules']['single_threshold'])
                    shared = float(refinement['rules']['shared_threshold'])
                    st.session_state['family_refine_single'] = single
                    st.session_state['family_refine_shared'] = shared
                    # Recompute the final rows from matching pair evidence instead of trusting saved output rows.
                    st.session_state['family_refinement_request'] = {'source': refinement['source'], 'rules': refinement['rules']}
                saved_checks = payload.get('stability_checks', {})
                saved_check = next(iter(saved_checks.values()), payload.get('stability'))
                if saved_check:
                    st.session_state['family_repetitions'] = int(saved_check['repetitions'])
                    if saved_check.get('summary'):
                        st.session_state['family_stability_target'] = float(saved_check['summary']['target'])
                st.session_state.pop('family_run', None)
                st.session_state.pop('family_stability_checks', None)
                # Clear old editor deltas before restoring the saved review.
                for key in list(st.session_state):
                    if key.startswith(('family_assignments_', 'family_titles_', 'family_notes_')):
                        del st.session_state[key]
                st.rerun()
            except (ValueError, KeyError, TypeError) as error:
                st.error(f'Cannot load scenario: {error}')


def _json_value(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    raise TypeError(f'Cannot serialize {type(value).__name__}')


def datetime_suffix():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
