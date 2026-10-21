"""Interactive curation of whole families over cached scenario evidence."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core.families import LOCAL_DIR, family_consistency
from app_core.family_cohort import (
    candidate_library, cohort_payload, edit_draft, fingerprint, new_draft, overlap_table,
    score_candidates, sources_from_cases, subset_scores, summarize_cohort, validate_cohort,
)
from app_core.family_plots import co_membership_figure


@st.cache_data(show_spinner=False, max_entries=8)
def _library(sources: dict, rules: dict):
    return candidate_library(sources, rules)


def _commit(draft: dict, rerun: bool = True) -> None:
    st.session_state['cohort_undo'] = copy.deepcopy(st.session_state.get('family_cohort'))
    st.session_state['family_cohort'] = draft
    st.session_state['cohort_revision'] = st.session_state.get('cohort_revision', 0) + 1
    if rerun:
        st.rerun()


def _start(sources, universe, policy, membership_hash, reference_hash, selected=None) -> None:
    fresh = new_draft(sources, universe, policy, membership_hash, reference_hash, selected)
    if selected:
        rows = score_candidates(selected, sources, set(), policy)
        flags = dict(zip(rows.id, rows.policy_flags))
        for row in fresh['selected']:
            row['added_as_exception'] = bool(flags.get(row['id']))
        fresh['origin_coverage'] = len(set().union(*(set(row['member_keys']) for row in selected)))
    _commit(fresh, False)


def _undo() -> None:
    st.session_state['family_cohort'] = st.session_state.pop('cohort_undo')
    st.session_state['cohort_revision'] = st.session_state.get('cohort_revision', 0) + 1


def _apply_candidate(preview: dict, candidate_id: str, prefix: str) -> None:
    # Read the submitted value in the callback, including a text edit sent with the click.
    next(row for row in preview['selected'] if row['id'] == candidate_id)['exception_note'] = st.session_state.get(f'{prefix}_exception_note', '')
    _commit(preview, False)


def _next_missing(missing: list, current) -> None:
    position = missing.index(current) if current in missing else -1
    st.session_state['cohort_resolve_character'] = missing[(position + 1) % len(missing)]


def _choose(label: str, options: list, key: str, format_func=str):
    # Dynamic queues shrink after edits. Keep a valid selection without invalid widget state.
    if st.session_state.get(key) not in options:
        st.session_state.pop(key, None)
    return st.selectbox(label, options, key=key, format_func=format_func)


def _percent(value) -> str:
    return f'{value:.1%}' if pd.notna(value) else 'Unscored'


def _table(rows: pd.DataFrame, columns: list | None = None) -> None:
    config = {field: st.column_config.NumberColumn(label, format='percent') for field, label in [
        ('member_fit', 'Character fit'), ('family_mean', 'Family consistency'), ('best_fit', 'Best selected fit'),
        ('worst_fit', 'Weakest selected fit'), ('peer_support', 'Peers reaching target'),
        ('weakest_pair', 'Weakest pair'), ('weakest_member', 'Weakest member'),
    ]}
    config.update({
        'scenario': st.column_config.TextColumn('Source scenario', width='medium'),
        'title': 'Family title', 'size': 'Included characters', 'new_characters': 'New coverage',
        'already_covered': 'Already covered', 'policy_flags': 'Current exclusion reasons',
        'selection_status': 'Selection', 'cost_per_new_character': st.column_config.NumberColumn('Cost / new character', format='%.3f'),
        'selection_cost': st.column_config.NumberColumn('Family cost', format='%.2f'),
        'proportional_distance': st.column_config.NumberColumn('Proportional size gap', format='%.2f'),
        'fits': st.column_config.TextColumn('Fit in each family', width='large'),
        'family': 'Original family', 'basis': 'Included basis', 'in_ideal_range': 'Preferred size',
        'weak_members': 'Members below target', 'exclusive_characters': 'Exclusive coverage',
        'repeated_characters': 'Repeated members', 'added_as_exception': 'Added as exception',
        'exception_note': 'Review note', 'family_count': 'Selected families',
        'profiles': 'Source profiles', 'rank_tiers': 'Source rank tiers', 'repetitions': 'Bootstrap repeats',
    })
    st.dataframe(rows, hide_index=True, width='stretch', column_order=columns, column_config=config)


def render_cohort_builder(cases: list[dict], universe: pd.DataFrame, cover: dict | None,
                          policy: dict, membership_hash: str, reference_hash: str) -> None:
    st.subheader('Build your family cohort')
    existing = st.session_state.get('family_cohort')
    if existing:
        if existing['policy'].get('trim_fraction') != policy.get('trim_fraction', existing['policy'].get('trim_fraction')):
            st.info('The library trim rule changed. Existing selected member sets stay fixed; new retained options use the current rule.')
        existing['policy'].update(policy)
        target_key = f'cohort_member_target_{st.session_state.get("cohort_revision", 0)}'
        if target_key in st.session_state:
            existing['member_target'] = st.session_state[target_key]
    _save_load(universe, membership_hash, reference_hash)
    current_sources = sources_from_cases(cases)
    draft = st.session_state.get('family_cohort')
    actions = st.columns(3)
    if current_sources and cover is not None:
        candidates = _library(current_sources, policy)
        source_by_case = {case['id']: fingerprint(case['scenario']) for case in cases}
        suggestions = {(source_by_case[row.scenario_id], row.family, row.basis)
                       for row in cover['families'].itertuples()}
        selected = [row for row in candidates if (row['source_id'], row['family'], row['basis']) in suggestions]
        label = 'Replace draft with this suggestion' if draft else 'Start from suggested cover'
        actions[0].button(label, key='cohort_start_suggestion', on_click=_start,
                          args=(current_sources, universe, policy, membership_hash, reference_hash, selected))
        actions[1].button('Start empty', key='cohort_start_empty', on_click=_start,
                          args=(current_sources, universe, policy, membership_hash, reference_hash))
    actions[2].button('Undo last edit', disabled=not st.session_state.get('cohort_undo'),
                      key='cohort_undo_button', on_click=_undo)
    if not draft:
        st.info('Start from a suggestion, start empty after running a batch, or load a saved cohort above.')
        return
    if draft['membership_sha256'] != membership_hash or draft['reference_sha256'] != reference_hash:
        st.warning('This draft belongs to another snapshot/reference. Save it above, then start a new draft for this source.')
        return
    if current_sources and fingerprint(current_sources) != fingerprint(draft['sources']):
        st.info('This draft retains its original evidence library. The current batch differs. Save the draft before '
                'explicitly replacing it from the new suggestion; existing memberships have been preserved.')
    effective = dict(draft['policy'], **policy)
    draft['policy'] = effective
    target = st.slider('Member-fit review target', 0., 1., float(draft['member_target']), .05,
                       key=f'cohort_member_target_{st.session_state.get("cohort_revision", 0)}',
                       help='Flags a character when its average bootstrap companionship with other included members is below this value. It does not exclude families automatically.')
    draft['member_target'] = target
    candidates = _library(draft['sources'], effective)
    report = summarize_cohort(draft)
    _summary(report, len(universe))
    if not report['families'].empty:
        family_rows = report['families']
        st.caption(f'{int(family_rows.family_mean.ge(effective["family_target"]).sum())} families meet the family target · '
                   f'{int(family_rows.weak_members.gt(0).sum())} have members below the member-fit target · '
                   f'{int(family_rows.added_as_exception.sum())} were added as manual exceptions. These flags can overlap.')
    st.caption('Draft metrics update after every edit. Suggestion settings do not replace your selections. '
               'Consistency comes from each source scenario separately; adding a family adds all its included members.')
    _quick_add(draft, candidates, report)
    _selected_families(draft, report)
    section = st.radio('Cohort workspace', ['Resolve characters', 'Overlap and coverage', 'Family library'],
                        horizontal=True, key='cohort_workspace')
    if section == 'Resolve characters':
        _resolve(draft, candidates, report)
    elif section == 'Overlap and coverage':
        _overlap(draft, report)
    else:
        _browse(draft, candidates, report)


def _summary(report: dict, total: int) -> None:
    counts = report['summary']
    columns = st.columns(5)
    for column, label, value in zip(columns, ['Cohort families', 'Cohort coverage', 'Missing characters',
                                             'Repeated characters', 'Below member-fit target'],
                                     [counts['families'], f'{counts["covered"]}/{total}', counts['missing'],
                                      counts['repeated'], counts['weak_fit']], strict=True):
        column.metric(label, value)
    st.caption(f'{counts["membership_rows"]} memberships · {counts["extra_memberships"]} extra memberships · '
               f'{counts["ideal_characters"]} characters in a preferred-size family · '
               f'{counts["unscored"]} covered characters have no scored fit. Repeated characters and extra memberships are different counts.')


def _quick_add(draft: dict, candidates: list[dict], report: dict) -> None:
    with st.expander('Add a family manually'):
        show_below = st.checkbox('Include below-target original families', key='cohort_quick_below')
        rows = score_candidates(candidates, draft['sources'], _covered(report), draft['policy'], draft['member_target'])
        if not show_below and not rows.empty:
            rows = rows.loc[rows.family_mean.ge(draft['policy']['family_target'])]
        if rows.empty:
            st.info('No families in the current library scope.')
            return
        lookup = rows.set_index('id')
        choice = _choose('Add a family', rows.id.tolist(), 'cohort_quick_choice',
                         lambda key: _candidate_label(lookup.loc[key]))
        candidate = next(row for row in candidates if row['id'] == choice)
        _candidate_detail(draft, candidate, report, 'quick')


def _candidate_label(row) -> str:
    return f'{row["family"]} · {row["size"]} characters · {_percent(row["family_mean"])} · {row["scenario"]} · {row["basis"]}'


def _covered(report: dict) -> set:
    return set(report['characters'].loc[report['characters'].family_count.gt(0), 'character_key'])


def _selected_families(draft: dict, report: dict) -> None:
    st.markdown('**Current cohort**')
    if report['families'].empty:
        st.info('The draft is empty. Add a family or resolve a missing character below.')
        return
    _table(report['families'], ['title', 'family', 'scenario', 'basis', 'size', 'family_mean', 'weakest_member',
                                'weak_members', 'exclusive_characters', 'repeated_characters', 'added_as_exception',
                                'policy_flags', 'exception_note'])
    with st.expander('Inspect, rename or remove a selected family'):
        lookup = {row['id']: row for row in draft['selected']}
        selected = _choose('Selected family', list(lookup), 'cohort_selected_family', lambda key: lookup[key]['title'])
        family = lookup[selected]
        revision = st.session_state.get('cohort_revision', 0)
        title = st.text_input('Display title', family['title'], key=f'cohort_title_{selected}_{revision}')
        note = st.text_area('Family review note', family.get('exception_note', ''), key=f'cohort_family_note_{selected}_{revision}')
        if st.button('Save family title and note', key='cohort_rename'):
            if not title.strip():
                st.error('Enter a nonempty title.')
            else:
                changed = copy.deepcopy(draft)
                next(row for row in changed['selected'] if row['id'] == selected).update(title=title.strip(), exception_note=note)
                _commit(changed)
        if st.checkbox('Show selected-family scores and heatmap', key='cohort_show_selected_plots'):
            _family_plot(draft, family, 'selected')
        _remove(draft, family, report, 'selected')


def _resolve(draft: dict, candidates: list[dict], report: dict) -> None:
    columns = st.columns(2)
    scope = columns[0].selectbox('Characters to resolve', ['Missing', 'Below member-fit target', 'In multiple families', 'All characters'],
                                  key='cohort_resolve_scope')
    order = columns[1].selectbox('Character queue order', ['Alphabetical', 'Fewest distinct viable options'], key='cohort_queue_order')
    rows = report['characters']
    if scope == 'Missing':
        rows = rows.loc[rows.family_count.eq(0)]
    elif scope == 'Below member-fit target':
        rows = rows.loc[rows.family_count.gt(0) & (rows.best_fit.lt(draft['member_target']) | rows.best_fit.isna())]
    elif scope == 'In multiple families':
        rows = rows.loc[rows.family_count.gt(1)]
    keys = rows.sort_values('character').character_key.tolist()
    if order != 'Alphabetical':
        viable = score_candidates(candidates, draft['sources'], set(), draft['policy'], draft['member_target'])
        groups = [set(row.member_keys) for row in viable.loc[viable.family_mean.ge(draft['policy']['family_target'])].itertuples()] if not viable.empty else []
        distinct = {tuple(sorted(group)) for group in groups}
        keys.sort(key=lambda key: (sum(key in group for group in distinct), rows.set_index('character_key').loc[key, 'character']))
    # Preserve the just-resolved character until the reader explicitly advances.
    previous = st.session_state.get('cohort_resolve_character')
    all_names = {row['character_key']: row['character'] for row in draft['catalog']}
    if previous in all_names and previous not in keys:
        keys.append(previous)
    if not keys:
        st.success('No characters in this review queue.')
        return
    key = _choose('Resolve a character', keys, 'cohort_resolve_character', lambda item: all_names[item])
    current = report['characters'].set_index('character_key').loc[key]
    st.caption(f'{current.family_count} selected families · best selected fit {_percent(current.best_fit)}')
    if current.family_count:
        _table(report['memberships'].loc[report['memberships'].character_key.eq(key)], ['title', 'member_fit', 'family_mean', 'peer_support', 'weakest_pair'])
    columns = st.columns(2)
    missing = report['characters'].loc[report['characters'].family_count.eq(0)].sort_values('character').character_key.tolist()
    columns[0].button('Next missing character', key='cohort_next_missing', disabled=not missing,
                       on_click=_next_missing, args=(missing, key))
    with columns[1].expander('Keep unresolved / review note'):
        note = st.text_area('Character review note', draft['character_notes'].get(str(key), ''),
                            key=f'cohort_note_{key}_{st.session_state.get("cohort_revision", 0)}')
        if st.button('Save review note', key='cohort_save_character_note'):
            changed = copy.deepcopy(draft)
            changed['character_notes'][str(key)] = note
            _commit(changed)
    below = st.checkbox('Inspect below-target original families', key='cohort_resolve_below')
    options = score_candidates(candidates, draft['sources'], _covered(report), draft['policy'], draft['member_target'], key)
    if not below and not options.empty:
        options = options.loc[options.family_mean.ge(draft['policy']['family_target'])]
    if options.empty:
        st.info('No containing families in this scope. Enable below-target originals or add more scenario evidence to the library.')
    else:
        _candidate_comparison(draft, options, candidates, report, key, 'resolve')
    with st.expander('Original-family trimming context'):
        originals = [row for row in candidates if row['basis'] == 'Full family' and key in row['member_keys']]
        context = [{'source': draft['sources'][row['source_id']]['name'], 'family': row['family'],
                    'retained_mean': row['retained_consistency'], 'removed_by_trim': key in row['removed_keys']}
                   for row in originals]
        st.dataframe(pd.DataFrame(context), hide_index=True, width='stretch')
        st.caption('A character removed by trimming is not a member of that retained candidate, even if the retained mean passes.')


def _candidate_comparison(draft: dict, rows: pd.DataFrame, candidates: list[dict], report: dict,
                          key, prefix: str) -> None:
    ordering = st.selectbox('Rank family options by', ['Character fit', 'Closest preferred size', 'Family consistency',
                                                     'Most new coverage', 'Lowest cost per additional character'], key=f'{prefix}_rank')
    sorts = {'Character fit': (['member_fit', 'proportional_distance', 'family_mean', 'id'], [False, True, False, True]),
             'Closest preferred size': (['proportional_distance', 'member_fit', 'id'], [True, False, True]),
             'Family consistency': (['family_mean', 'member_fit', 'id'], [False, False, True]),
             'Most new coverage': (['new_characters', 'member_fit', 'id'], [False, False, True]),
             'Lowest cost per additional character': (['cost_per_new_character', 'member_fit', 'id'], [True, False, True])}
    fields, directions = sorts[ordering]
    rows = rows.sort_values(fields, ascending=directions, na_position='last').copy()
    selected_ids = {row['id'] for row in draft['selected']}
    rows['selection_status'] = np.where(rows.id.isin(selected_ids), 'Selected',
                                         np.where(rows.eligible, 'Eligible, not selected', 'Manual exception required'))
    _table(rows, ['family', 'scenario', 'basis', 'member_fit', 'family_mean', 'size', 'in_ideal_range',
                  'new_characters', 'already_covered', 'selection_status', 'policy_flags', 'peer_support',
                  'weakest_pair', 'selection_cost', 'cost_per_new_character', 'profiles', 'rank_tiers', 'repetitions'])
    st.caption('Character fit averages companionship with included peers, excluding self. Smaller groups can score highly more easily. '
               'Source cohorts/settings differ; scores compare alternatives and are not calibrated membership probabilities.')
    lookup = rows.set_index('id')
    choice = _choose('Inspect family option', rows.id.tolist(), f'{prefix}_candidate', lambda value: _candidate_label(lookup.loc[value]))
    candidate = next(row for row in candidates if row['id'] == choice)
    _candidate_detail(draft, candidate, report, prefix, key)


def _candidate_detail(draft: dict, candidate: dict, report: dict, prefix: str, character_key=None) -> None:
    with st.container(border=True):
        source = draft['sources'][candidate['source_id']]
        fits, mean = subset_scores(source, candidate['member_keys'], draft['member_target'])
        selected = next((row for row in draft['selected'] if row['source_id'] == candidate['source_id']
                         and set(row['member_keys']) == set(candidate['member_keys'])), None)
        st.markdown(f'**{candidate["title"]}**')
        st.caption(f'{source["name"]} · {source["repetitions"]} bootstrap repeats · seed {source["repeat_seed"]} · '
                   f'{source["profiles"]:,} profiles · {"/".join(source["scenario"]["source"]["tiers"])} · '
                   f'{source["scenario"]["source"]["maturity"]} tracking history')
        st.write(f'{len(fits)} included characters · family consistency {_percent(mean)} · '
                 f'original median separation {_percent(candidate.get("original_separation"))}')
        if character_key is not None:
            member = fits.loc[fits.character_key.eq(character_key)].iloc[0]
            st.write(f'**{member.character}: {_percent(member.member_fit)} character fit** · '
                     f'{_percent(member.peer_support)} of peers reach the review target')
            positions = {key: i for i, key in enumerate(source['co_membership']['character_keys'])}
            matrix = np.asarray(source['co_membership']['rates'])
            pairs = fits.loc[fits.character_key.ne(character_key), ['character_key', 'character']].copy()
            pairs['pair_consistency'] = [matrix[positions[character_key], positions[key]] for key in pairs.character_key]
            pairs = pairs.sort_values('pair_consistency')
            figure = go.Figure(go.Bar(x=pairs.pair_consistency, y=pairs.character, orientation='h',
                                      hovertemplate='%{y}: %{x:.1%}<extra></extra>'))
            figure.add_vline(x=draft['member_target'], line_dash='dot')
            figure.update_layout(height=max(180, min(600, len(pairs) * 20 + 60)), margin=dict(l=5, r=5, t=20, b=5),
                                 title=f'{member.character}: consistency with each included peer')
            figure.update_xaxes(range=[0, 1.02], tickformat='.0%')
            st.plotly_chart(figure, width='stretch', key=f'{prefix}_peer_plot')
        covered = _covered(report)
        st.write('Newly covered: ' + (', '.join(fits.loc[~fits.character_key.isin(covered), 'character']) or 'None'))
        st.write('Already covered: ' + (', '.join(fits.loc[fits.character_key.isin(covered), 'character']) or 'None'))
        with st.expander('Included-member scores and source heatmap'):
            _table(fits)
            if st.checkbox('Show source heatmap', key=f'{prefix}_show_heatmap'):
                full = st.checkbox('Show full original family including removed members', key=f'{prefix}_full_heatmap')
                baseline = pd.DataFrame(source['automatic'])
                keys = (baseline.loc[baseline.family.eq(candidate['family']), 'character_key'].tolist()
                        if full else candidate['member_keys'])
                # Reindex matrix together with baseline, preserving plot row positions after filtering.
                _, aligned = family_consistency(source['co_membership'], baseline)
                rows = baseline.loc[baseline.character_key.isin(keys)].copy()
                if full:
                    rows['character'] += np.where(rows.character_key.isin(candidate['member_keys']), ' [included]', ' [removed]')
                st.plotly_chart(co_membership_figure(rows, aligned), width='stretch', key=f'{prefix}_source_heatmap')
        if selected:
            st.info('This source/member-set family is already selected.')
            _remove(draft, selected, report, prefix)
            return
        if any(set(row['member_keys']) == set(candidate['member_keys']) for row in draft['selected']):
            st.warning('An identical member set from another source is selected. Adding this keeps both evidence sources and adds no unique coverage.')
        replace = _choose('Replace selected family (optional)', [None] + [row['id'] for row in draft['selected']],
                          f'{prefix}_replace', lambda key: 'Add without replacing' if key is None else next(row['title'] for row in draft['selected'] if row['id'] == key))
        working = edit_draft(draft, remove_id=replace) if replace else draft
        before_add = summarize_cohort(working)
        scored = score_candidates([candidate], draft['sources'], _covered(before_add), draft['policy'], draft['member_target']).iloc[0]
        flags = scored.policy_flags
        if flags:
            st.warning('Manual exception: ' + flags)
        if scored.new_characters:
            st.caption(f'Family cost {scored.selection_cost:.3f} · cost per additional character {scored.cost_per_new_character:.3f}')
        else:
            st.caption('Adds no new coverage. Cost per additional character: N/A. You may still add it for a different fit.')
        note = st.text_input('Reason / review note', key=f'{prefix}_exception_note')
        added = dict(candidate, exception_note=note, added_as_exception=bool(flags), exception_flags_at_add=flags)
        preview = edit_draft(draft, added, replace)
        after = summarize_cohort(preview)
        _impact(report, after, draft, character_key)
        st.button('Add as manual exception' if flags else ('Replace family' if replace else 'Add family'),
                   key=f'{prefix}_add', disabled=pd.isna(mean), type='primary',
                   on_click=_apply_candidate, args=(preview, candidate['id'], prefix))


def _impact(before: dict, after: dict, draft: dict, key=None) -> None:
    columns = st.columns(4)
    for column, field, label in zip(columns, ['covered', 'missing', 'families', 'repeated'],
                                     ['Coverage after edit', 'Missing after edit', 'Families after edit', 'Repeated after edit'], strict=True):
        value = after['summary'][field]
        column.metric(label, f'{value}/{len(draft["catalog"])}' if field == 'covered' else value,
                      delta=value - before['summary'][field])
    lost = _covered(before) - _covered(after)
    if lost:
        names = {row['character_key']: row['character'] for row in draft['catalog']}
        st.warning('Would become uncovered: ' + ', '.join(sorted(names[item] for item in lost)))
    if key is not None:
        old = before['characters'].set_index('character_key').loc[key, 'best_fit']
        new = after['characters'].set_index('character_key').loc[key, 'best_fit']
        st.caption(f'This character’s best selected fit: {_percent(old)} → {_percent(new)}')


def _remove(draft: dict, family: dict, report: dict, prefix: str) -> None:
    changed = edit_draft(draft, remove_id=family['id'])
    after = summarize_cohort(changed)
    lost = _covered(report) - _covered(after)
    names = {row['character_key']: row['character'] for row in draft['catalog']}
    st.caption(f'Removing this family would uncover {len(lost)} characters: ' + (', '.join(sorted(names[key] for key in lost)) or 'None'))
    st.button('Remove family', key=f'{prefix}_remove', on_click=_commit, args=(changed, False))


def _family_plot(draft: dict, family: dict, prefix: str) -> None:
    fits, _ = subset_scores(draft['sources'][family['source_id']], family['member_keys'], draft['member_target'])
    fits = fits.sort_values('member_fit')
    figure = go.Figure(go.Bar(x=fits.member_fit, y=fits.character, orientation='h',
                              hovertemplate='%{y}: %{x:.1%}<extra></extra>'))
    figure.add_vline(x=draft['member_target'], line_dash='dot')
    figure.update_layout(height=max(200, min(650, 22 * len(fits) + 60)), margin=dict(l=5, r=5, t=20, b=5), title='Included-member fit')
    figure.update_xaxes(range=[0, 1.02], tickformat='.0%')
    st.plotly_chart(figure, width='stretch', key=f'{prefix}_member_plot')
    source = draft['sources'][family['source_id']]
    baseline = pd.DataFrame(source['automatic'])
    _, aligned = family_consistency(source['co_membership'], baseline)
    st.plotly_chart(co_membership_figure(baseline.loc[baseline.character_key.isin(family['member_keys'])], aligned),
                    width='stretch', key=f'{prefix}_heatmap')


def _overlap(draft: dict, report: dict) -> None:
    counts = report['characters'].family_count
    figure = go.Figure(go.Bar(x=['Missing', 'One family', 'Two families', 'Three or more'],
                              y=[int(counts.eq(0).sum()), int(counts.eq(1).sum()), int(counts.eq(2).sum()), int(counts.ge(3).sum())]))
    figure.update_layout(height=240, title='Characters by selected-family count', margin=dict(l=5, r=5, t=40, b=5))
    st.plotly_chart(figure, width='stretch', key='cohort_membership_histogram')
    scope = st.selectbox('Membership list', ['Repeated characters', 'Missing', 'Covered once', 'All characters'], key='cohort_overlap_scope')
    rows = report['characters']
    if scope == 'Repeated characters':
        rows = rows.loc[rows.family_count.gt(1)]
    elif scope == 'Missing':
        rows = rows.loc[rows.family_count.eq(0)]
    elif scope == 'Covered once':
        rows = rows.loc[rows.family_count.eq(1)]
    _table(rows, ['character', 'family_count', 'best_fit', 'worst_fit', 'fits', 'note'])
    overlaps = overlap_table(draft)
    if overlaps.empty:
        return
    metric = st.radio('Overlap measure', ['Jaccard', 'Directional containment', 'Shared count'], horizontal=True, key='cohort_overlap_measure')
    field = {'Jaccard': 'jaccard', 'Directional containment': 'containment', 'Shared count': 'shared'}[metric]
    ids = [row['id'] for row in draft['selected']]
    labels = [f'{index + 1}. {row["title"]}' for index, row in enumerate(draft['selected'])]
    matrix = overlaps.pivot(index='row_id', columns='column_id', values=field).reindex(index=ids, columns=ids)
    shared = overlaps.pivot(index='row_id', columns='column_id', values='shared').reindex(index=ids, columns=ids)
    union = overlaps.pivot(index='row_id', columns='column_id', values='union').reindex(index=ids, columns=ids)
    figure = go.Figure(go.Heatmap(z=matrix.to_numpy(), x=labels, y=labels, colorscale='Blues',
                                  zmin=0, zmax=None if field == 'shared' else 1,
                                  customdata=np.stack([shared.to_numpy(), union.to_numpy()], axis=-1),
                                  hovertemplate='%{y}<br>%{x}<br>Overlap %{z:.3f}<br>Shared %{customdata[0]} · union %{customdata[1]}<extra></extra>'))
    figure.update_layout(title='Membership overlap', height=max(350, min(750, len(ids) * 28 + 120)))
    figure.update_yaxes(autorange='reversed')
    st.plotly_chart(figure, width='stretch', key='cohort_overlap_heatmap')
    st.caption('Set overlap of characters in selected families. This is not bootstrap consistency or player-audience overlap. '
               'Directional containment divides shared characters by the row family’s size.')
    columns = st.columns(2)
    first = columns[0].selectbox('Compare family', ids, format_func=lambda key: labels[ids.index(key)], key='cohort_pair_first')
    second = columns[1].selectbox('With family', ids, format_func=lambda key: labels[ids.index(key)], key='cohort_pair_second')
    pair = overlaps.loc[overlaps.row_id.eq(first) & overlaps.column_id.eq(second)].iloc[0]
    st.write(f'{pair.shared} shared characters: {pair.shared_characters or "None"}')
    if first != second and pair.containment == 1:
        st.info('The row family is completely contained in the column family. Review its fit/size contribution before removing it.')
    _table(report['families'], ['title', 'size', 'exclusive_characters', 'repeated_characters', 'family_mean', 'weak_members'])
    figure = go.Figure()
    for field, label, color in [('exclusive_characters', 'Exclusive coverage', '#58b798'), ('repeated_characters', 'Shared membership', '#4ea5d9')]:
        figure.add_trace(go.Bar(x=report['families'][field], y=report['families'].title, orientation='h', name=label, marker_color=color))
    figure.update_layout(barmode='stack', height=max(250, len(ids) * 26 + 80), title='Coverage contribution by family')
    st.plotly_chart(figure, width='stretch', key='cohort_contribution_plot')


def _browse(draft: dict, candidates: list[dict], report: dict) -> None:
    st.caption('Browse source families regardless of suggestion size/cost exclusions. Retained groups contain only their kept members.')
    names = {row['character_key']: row['character'] for row in draft['catalog']}
    search = st.multiselect('Find families containing any characters', sorted(names, key=names.get), format_func=names.get, key='cohort_browser_characters')
    below = st.checkbox('Include below-target originals in library', key='cohort_browser_below')
    rows = score_candidates(candidates, draft['sources'], _covered(report), draft['policy'], draft['member_target'])
    if not below and not rows.empty:
        rows = rows.loc[rows.family_mean.ge(draft['policy']['family_target'])]
    if search and not rows.empty:
        rows = rows.loc[rows.member_keys.map(lambda keys: bool(set(keys) & set(search)))]
    if rows.empty:
        st.info('No families match this scope.')
        return
    if len(search) == 1:
        _candidate_comparison(draft, score_candidates(rows.to_dict('records'), draft['sources'], _covered(report), draft['policy'], draft['member_target'], search[0]),
                              candidates, report, search[0], 'browser')
    else:
        _table(rows, ['title', 'family', 'scenario', 'basis', 'family_mean', 'size', 'new_characters', 'policy_flags'])
        if search:
            long = pd.concat([score_candidates(rows.to_dict('records'), draft['sources'], _covered(report), draft['policy'], draft['member_target'], key)
                              for key in search], ignore_index=True)
            _table(long, ['character', 'family', 'scenario', 'basis', 'member_fit', 'family_mean', 'peer_support', 'size'])
        lookup = rows.set_index('id')
        choice = _choose('Inspect library family', rows.id.tolist(), 'cohort_library_candidate', lambda key: _candidate_label(lookup.loc[key]))
        _candidate_detail(draft, next(row for row in candidates if row['id'] == choice), report, 'library')


def _save_load(universe: pd.DataFrame, membership_hash: str, reference_hash: str) -> None:
    with st.expander('Save / load cohort'):
        directory = LOCAL_DIR / 'cohorts'
        files = {path.name: path for path in sorted(directory.glob('*.json'), reverse=True)}
        upload = st.file_uploader('Upload cohort JSON', type='json', key='cohort_upload')
        saved = st.selectbox('Saved cohorts', [None] + list(files), format_func=lambda name: name or 'Choose a saved cohort', key='cohort_load_file')
        if st.button('Load cohort', disabled=upload is None and saved is None, key='cohort_load'):
            try:
                data = upload.getvalue() if upload is not None else files[saved].read_bytes()
                loaded = validate_cohort(json.loads(data), universe, membership_hash, reference_hash)
                # Apply the saved controls before widgets are created on the next page run.
                st.session_state['cohort_restore_policy'] = copy.deepcopy(loaded['policy'])
                for key in list(st.session_state):
                    if key.startswith(('cohort_title_', 'cohort_family_note_', 'cohort_note_')):
                        del st.session_state[key]
                _commit(loaded)
            except (ValueError, OSError) as error:
                st.error(f'Could not load cohort: {error}')
        draft = st.session_state.get('family_cohort')
        if not draft:
            return
        version = st.session_state.get('cohort_revision', 0)
        name = st.text_input('Cohort name', draft['name'], key=f'cohort_name_{version}')
        notes = st.text_area('Cohort notes', draft['notes'], key=f'cohort_notes_{version}')
        draft.update(name=name, notes=notes)
        payload = cohort_payload(draft)
        content = json.dumps(payload, indent=2, allow_nan=False).encode()
        columns = st.columns(2)
        if columns[0].button('Save cohort locally', key='cohort_save'):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                filename = f'cohort-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:6]}.json'
                (directory / filename).write_bytes(content)
                st.success(f'Saved {filename}')
            except OSError as error:
                st.error(f'Could not save cohort: {error}')
        columns[1].download_button('Download cohort JSON', content, file_name='family-cohort.json', mime='application/json')
        report = summarize_cohort(draft)
        context = {'membership_sha256': draft['membership_sha256'], 'reference_sha256': draft['reference_sha256'],
                   'member_fit_target': draft['member_target'], 'family_target': draft['policy']['family_target']}
        families = report['families'].drop(columns='removed_keys', errors='ignore').copy()
        memberships = report['memberships'].copy()
        provenance = pd.DataFrame([{'source_id': key, 'source_scenario': source['name'],
                                       'bootstrap_repeats': source['repetitions'], 'repeat_seed': source['repeat_seed'],
                                       'profiles': source['profiles'],
                                       'rank_tiers': '/'.join(source['scenario']['source']['tiers']),
                                       'tracking_history': source['scenario']['source']['maturity']}
                                  for key, source in draft['sources'].items()])
        if not memberships.empty:
            memberships = memberships.merge(provenance, on='source_id', how='left')
        if not families.empty:
            names = {row['character_key']: row['character'] for row in draft['catalog']}
            families['member_names'] = families.member_keys.map(lambda keys: ', '.join(names[key] for key in keys))
            families['member_keys'] = families.member_keys.map(json.dumps)
            families = families.merge(provenance, on='source_id', how='left')
        for label, frame, filename in [('Download cohort families CSV', families, 'cohort-families.csv'),
                                       ('Download cohort memberships CSV', memberships, 'cohort-memberships.csv'),
                                       ('Download character review CSV', report['characters'], 'cohort-character-review.csv'),
                                       ('Download family overlap CSV', overlap_table(draft), 'cohort-overlap.csv')]:
            st.download_button(label, frame.assign(**context).to_csv(index=False).encode(), file_name=filename, mime='text/csv')
