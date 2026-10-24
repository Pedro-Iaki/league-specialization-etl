"""Character-family interests as a lens on the wider activity/rank audience."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.audience_segments import CHARACTER_TYPES, family_cells, rank_context, segment_counts
from app_core.audience_story import PAGE_CSS, story_history_lens, story_segment_methods, story_segments
from app_core.charts import style_figure
from app_core.config import BLUE, GOLD, PLAYSTYLE_ORDER
from app_core.family_audience import breadth_summary, family_catalogue, known_mix, primary_categories, supported_median
from app_core.i18n import focus_label, st, story_text, t, terminology_selector
from app_core.segment_presentation import audience_map_figure, band_label, map_orders
from app_core.story import story_footer, story_prose, story_section, story_start


def characters_page() -> None:
    terminology_selector()
    players = story_start(
        4, story_text('Character families make audience interests recognizable.', 'Champion families make audience interests recognizable.'),
        'Activity and rank describe investment and competitive context. Families add shared character interests; inferred character type adds complementary position context.',
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    prepared = story_segments(players)
    if prepared is None:
        story_footer(4)
        return
    base, reference = prepared
    catalogue = family_catalogue()
    ids = list(catalogue)
    full = primary_categories(base, ids)
    ordered = full.loc[full.family_category.isin(ids)].sort_values(['weighted_mass', 'family_category'], ascending=[False, True])
    ranked_ids = ordered.family_category.tolist()
    options = ['All', *map_orders(base, reference, 'engagement_band')]
    names = {code: t('All ranked volumes') if code == 'All' else band_label(reference, 'engagement_band', code) for code in options}
    engagement = st.selectbox('Ranked games recorded', options, format_func=names.__getitem__, key='story_family_engagement')
    history = story_history_lens(base, reference, key='story_family_history')
    selected = base
    if engagement != 'All':
        selected = selected.loc[selected.engagement_band.eq(engagement)]
    if history != 'All':
        selected = selected.loc[selected.history_band.eq(history)]
    if engagement != 'All' or history != 'All':
        st.caption(t('This selection retains {p0} of the adjusted base. All views below use this selection and the original full-base tier weights.',
                     p0=f'{selected.population_weight.sum() / base.population_weight.sum():.1%}'))
    story_section('01 · The reporting label', 'One primary family, or an explicit evidence state')
    overview = primary_categories(selected, ids, ranked_ids[:5])
    overview = overview.loc[overview.family_category.isin(full.loc[full.profiles.gt(0), 'family_category'].tolist() + ['Other families'])]
    st.plotly_chart(category_chart(overview, catalogue), key='story-family-overview', width='stretch', config={'displayModeBar': False})
    st.caption('Primary means the unique highest affinity. Tied highest scores remain Shared top, not an arbitrary family. Other families combines the remaining primary labels; the denominator includes every selected profile, including missing evidence.')
    story_prose('A family score is the share of active-pool lifetime mastery invested in its members with at least 15,000 points each. All active-pool mastery stays in the denominator. One character can contribute to several families, so affinity scores overlap and must not be added into a composition.')
    story_section('02 · A family lens', 'Where does this family attract invested interest?')
    family_names = {fid: family_label(family) for fid, family in catalogue.items()}
    chosen = st.selectbox('Choose a character family', ranked_ids, format_func=family_names.__getitem__, key='story_family_choice')
    family = catalogue[chosen]
    story_prose(t('Members of {p0}: {p1}.', p0=chosen, p1=', '.join(member['character'] for member in family['members'])))
    st.caption('Family IDs and member lists come from the accepted champion-audience-families-v1 definition. Names are character examples, not psychological personas. Different family sizes create different opportunities to score.')
    mode = st.segmented_control('Family map measure', ['Mean affinity', 'Primary share'], default='Mean affinity', key='story_family_measure') or 'Mean affinity'
    units = st.segmented_control('Activity units', ['Score', 'Estimated hours'], default='Score', key='story_family_units') or 'Score'
    invert = st.toggle('Put rank groups across the chart', key='story_family_invert')
    cells = family_cells(selected, chosen, ['activity_band', 'rank_group'])
    summary = family_cells(selected, chosen, [])
    affinity = mode == 'Mean affinity'
    if summary.empty:
        coverage = np.nan
    else:
        coverage = summary.iloc[0].scored_coverage
    st.caption(t('Scored pools cover {p0} of this selected audience. The map hover shows scoring coverage and support in each cell.', p0=percent(coverage)))
    if affinity:
        st.caption('Mean affinity averages this family score among scored pools, including measured zeros. Empty, below-cutoff, unmapped and unavailable pools are excluded from this mean and remain in the coverage denominator.')
    else:
        st.caption('Primary share counts only unique primary labels for this family, divided by everyone in the cell. Shared top and unavailable evidence stay in the denominator. Cells need supported primary-member counts to display an estimate.')
    context = rank_context(reference)
    labels = {row.rank_group: f'{t(row.rank_group)}<br>{t(f"{row.reference_share:.2%}")}' for row in context.itertuples()}
    orders = {dimension: map_orders(base, reference, dimension) for dimension in ['activity_band', 'rank_group']}
    metric = 'Mean family affinity' if affinity else 'Primary-family share'
    figure = audience_map_figure(
        cells, reference, orders=orders, units=units, labels=labels, maximum=1,
        value='affinity_estimate' if affinity else 'primary_estimate', metric_label=metric,
        x_dimension='rank_group' if invert else 'activity_band', y_dimension='activity_band' if invert else 'rank_group',
    )
    figure.update_xaxes(tickfont_size=10)
    st.plotly_chart(figure, key='story-family-map', width='stretch', config={'displayModeBar': False})
    st.caption('Rank-label percentages are the saved overall reference shares, unchanged by filters. Both map measures use 0–100% scales, but their denominators differ. A dash means unavailable or insufficient support; inversion changes layout only.')
    if units == 'Estimated hours':
        st.caption('Hour equivalents assume 600 mastery points per match and 30 minutes per match: mastery / 1,200. Rounded axis ranges are approximate; the underlying score cuts do not change.')
    if cells.empty or not cells['affinity_estimate' if affinity else 'primary_estimate'].notna().any():
        st.info('This family selection has no supported map cells. Broaden the filters or inspect the support table; no estimates have been substituted.')
    story_section('03 · Complementary context', 'A family is more specific than an inferred character type')
    primary = selected.loc[selected.primary_family_id.eq(chosen)]
    all_primary = selected.loc[selected.family_state.eq('primary')]
    types = list(CHARACTER_TYPES.values())
    typed, type_coverage = known_mix(primary, 'character_type', types)
    baseline, baseline_coverage = known_mix(all_primary, 'character_type', types)
    type_names = {code: story_text(code, role) for role, code in CHARACTER_TYPES.items()}
    st.plotly_chart(mix_chart(typed, baseline, 'character_type', type_names, chosen),
                    key='story-family-types', width='stretch', config={'displayModeBar': False})
    if not typed.estimate.notna().any():
        st.info('No supported type composition is available for this primary-family selection. Missing types have not been reassigned.')
    st.caption(t('Known inferred type covers {p0} of this primary-family audience and {p1} of all primary-family audiences. The chart compares known-type compositions only; missing type is excluded here, not from the family map.',
                 p0=percent(type_coverage), p1=percent(baseline_coverage)))
    st.caption('Type A–E means inferred Top, Jungle, Middle, Bottom and Support preference. It uses the existing Recent-pool point weights, not the family lifetime weighting. It is neither an observed match position nor a combat class.')
    if typed.estimate.notna().any():
        dominant = typed.sort_values('weighted_mass', ascending=False).iloc[0].character_type
        inside = primary_categories(selected.loc[selected.character_type.eq(dominant)], ids)
        supported = inside.loc[inside.family_category.isin(ids) & inside.estimate.notna()].sort_values('weighted_mass', ascending=False).head(3)
        if len(supported) >= 2:
            examples = '; '.join(f'{row.family_category}: {percent(row.estimate)}' for row in supported.itertuples())
            story_prose(t('Within type {p0}, several primary families remain: {p1}. Shares use everyone with that known type in the selection. Type alone does not specify a family.', p0=type_names[dominant], p1=examples))
    family_profile(primary, chosen, units)
    curiosity_lens(primary, all_primary)
    with st.expander('Methods, support and chart data'):
        story_segment_methods(base, reference)
        st.markdown('Active membership follows the existing model: short-history pools use the 30-day rule; mature pools use the 60-day/gain rule. It is not the preferred subset, and the score is not recent match share. Lifetime points use retained snapshots.')
        st.markdown('Affinity cells require at least 30 scored profiles and effective support 20; primary-share cells require the same support among primary members. Suppressed values do not redistribute their denominators. The family/type crosswalk is descriptive and both measures derive from character behavior.')
        table = primary_categories(selected, ids)
        table['Family members'] = table.family_category.map(lambda fid: ', '.join(member['character'] for member in catalogue[fid]['members']) if fid in catalogue else '')
        st.dataframe(table, hide_index=True, width='stretch')
        st.dataframe(cells, hide_index=True, width='stretch')
        st.dataframe(pd.concat([typed.assign(audience=chosen), baseline.assign(audience='All primary audiences')]), hide_index=True, width='stretch')
        st.download_button(t('Download primary family overview (CSV)'), table.to_csv(index=False).encode('utf-8'),
                           file_name='primary-family-audiences.csv', mime='text/csv', key='story_family_overview_download')
        st.download_button(t('Download family map (CSV)'), cells.to_csv(index=False).encode('utf-8'),
                           file_name=f'{chosen}-activity-rank.csv', mime='text/csv', key='story_family_map_download')
        contrasts = pd.concat([family_cells(selected, chosen, [dimension]).assign(dimension=dimension)
                               for dimension in ['activity_band', 'rank_group', 'engagement_band']], ignore_index=True)
        st.caption('Marginal comparisons below use their own activity, rank or ranked-volume denominators; they do not average map tiles equally.')
        st.dataframe(contrasts, hide_index=True, width='stretch')
    story_prose('These audience definitions can now accompany customer measures. The next chapter uses a clearly synthetic purchase scenario to demonstrate that reporting connection.', css='story-prose story-note')
    story_footer(4)


def family_profile(primary: pd.DataFrame, family_id: str, units: str) -> None:
    story_section('Audience profile', 'Combine interests with activity, ranked volume and rank')
    score = supported_median(primary, 'lifetime_mastery_points')
    games = supported_median(primary, 'total_games')
    gap = supported_median(primary, 'family_gap')
    columns = st.columns(3)
    columns[0].metric('Median estimated hours' if units == 'Estimated hours' else 'Median accumulated activity',
                      number(score / 1200 if units == 'Estimated hours' else score))
    columns[1].metric('Median ranked games recorded', number(games))
    columns[2].metric('Median top-versus-next gap', f'{gap * 100:.1f} pp' if np.isfinite(gap) else t('Unavailable'))
    st.caption(t('Median highest affinity in this primary audience: {p0}. The top-versus-next gap describes separation, not certainty.', p0=percent(supported_median(primary, 'top_family_score'))))
    rank = segment_counts(primary, ['rank_group'])
    supported = rank.loc[rank.estimate.notna()].sort_values('weighted_mass', ascending=False)
    if not supported.empty:
        largest = supported.iloc[0]
        story_prose(t('Among unique {p0} primary profiles, the largest supported rank group is {p1} ({p2}). The medians describe this family audience, not the average player or a time-to-rank trajectory.',
                      p0=family_id, p1=t(largest.rank_group), p2=percent(largest.estimate)))
    st.caption('The gap is the highest family score minus the next score, in percentage points. A small gap means the label is less distinctive; shared characters can raise both scores. No minimum gap is imposed, and Shared top is never forced into a primary family.')


def curiosity_lens(primary: pd.DataFrame, baseline: pd.DataFrame) -> None:
    with st.expander('Optional focus and breadth lens'):
        lens = st.radio('Additional detail', ['Off', 'Whole-history focus', 'Pool breadth'], key='story_family_curiosity', horizontal=True)
        if lens == 'Whole-history focus':
            mix, coverage = known_mix(primary, 'lifetime_playstyle', PLAYSTYLE_ORDER)
            reference, baseline_coverage = known_mix(baseline, 'lifetime_playstyle', PLAYSTYLE_ORDER)
            labels = {code: focus_label(code) for code in PLAYSTYLE_ORDER}
            st.plotly_chart(mix_chart(mix, reference, 'lifetime_playstyle', labels, t('Selected family')),
                            key='story-family-focus', width='stretch', config={'displayModeBar': False})
            st.caption(t('Whole-history focus uses the existing four classifications, not the family score or recent match share. Classification coverage: selected family {p0}; all primary audiences {p1}.',
                         p0=percent(coverage), p1=percent(baseline_coverage)))
        elif lens == 'Pool breadth':
            selected, overall = breadth_summary(primary), breadth_summary(baseline)
            st.dataframe(pd.DataFrame({
                'Audience': [t('Selected family'), t('All primary audiences')],
                'Median scored characters': [selected['scored_characters'], overall['scored_characters']],
                'Median positive families': [selected['positive_families'], overall['positive_families']],
            }), hide_index=True, width='stretch')
            st.caption('Scored-character breadth counts all eligible mapped characters in the active pool, not members inside the selected family. Positive-family breadth counts overlapping nonzero coordinates; one shared character can reach several families. Within-family character counts are not available in this snapshot.')


def family_label(family: dict) -> str:
    names = ' / '.join(member['character'] for member in family['members'][:3])
    return t('{p0}: {p1} · {p2} characters', p0=family['family_key'], p1=names, p2=len(family['members']))


def percent(value: float) -> str:
    return f'{value:.1%}' if np.isfinite(value) else t('Unavailable')


def number(value: float) -> str:
    return f'{value:,.0f}' if np.isfinite(value) else t('Unavailable')


def category_chart(cells: pd.DataFrame, catalogue: dict) -> go.Figure:
    labels = [f'{code}<br>{" / ".join(member["character"] for member in catalogue[code]["members"][:2])}'
              if code in catalogue else t(code) for code in cells.family_category]
    fig = go.Figure(go.Bar(x=cells.estimate.tolist(), y=labels, orientation='h', marker_color=GOLD,
                          text=[percent(value) if np.isfinite(value) else '' for value in cells.estimate], textposition='outside',
                          customdata=cells[['profiles', 'effective_players']].to_numpy().tolist(), cliponaxis=False,
                          hovertemplate=(f'%{{y}}<br>%{{x:.1%}}<br>{t("Observed profiles")}: %{{customdata[0]:,}}'
                                         f'<br>{t("Effective support")}: %{{customdata[1]:.1f}}<extra></extra>')))
    for label, row in zip(labels, cells.itertuples(), strict=True):
        if not np.isfinite(row.estimate):
            fig.add_annotation(x=0, y=label, text=t('Limited support') if row.profiles else t('No observations'), showarrow=False, xanchor='left')
    style_figure(fig, height=max(330, len(labels) * 40 + 70))
    fig.update_layout(margin={'l': 135, 'r': 40, 't': 12, 'b': 55})
    fig.update_xaxes(title=t('Primary audience share'), tickformat='.0%', range=[0, 1])
    fig.update_yaxes(autorange='reversed', tickfont_size=10, automargin=True)
    return fig


def mix_chart(selected: pd.DataFrame, baseline: pd.DataFrame, dimension: str, labels: dict, family_id: str) -> go.Figure:
    fig = go.Figure()
    horizontal = dimension == 'lifetime_playstyle'
    for frame, name, color in [(selected, family_id, GOLD), (baseline, t('All primary audiences'), BLUE)]:
        categories = [labels[code].replace(' ', '<br>') if horizontal else labels[code] for code in frame[dimension]]
        fig.add_trace(go.Bar(x=frame.estimate.tolist() if horizontal else categories,
                             y=categories if horizontal else frame.estimate.tolist(), orientation='h' if horizontal else 'v', name=name,
                             marker_color=color, customdata=frame[['profiles', 'effective_players']].to_numpy().tolist(),
                             hovertemplate=(('%{y}<br>%{fullData.name}: %{x:.1%}' if horizontal else '%{x}<br>%{fullData.name}: %{y:.1%}')
                                            + f'<br>{t("Observed profiles")}: %{{customdata[0]:,}}<br>{t("Effective support")}: %{{customdata[1]:.1f}}<extra></extra>')))
    style_figure(fig, height=360 if horizontal else 310)
    if horizontal:
        fig.update_layout(barmode='group', margin={'l': 110, 'r': 15, 't': 65, 'b': 50})
        fig.update_xaxes(title=t('Share among known traits'), range=[0, 1], tickformat='.0%', tickfont_size=10)
        fig.update_yaxes(autorange='reversed', tickfont_size=10, automargin=True)
        return fig
    fig.update_layout(barmode='group', margin={'l': 45, 'r': 10, 't': 45, 'b': 95})
    fig.update_yaxes(title=t('Share among known traits'), range=[0, 1], tickformat='.0%')
    fig.update_xaxes(tickangle=0, tickfont_size=10, tickmode='array', tickvals=list(labels.values()),
                     ticktext=[label.replace(' ', '<br>') for label in labels.values()])
    return fig
