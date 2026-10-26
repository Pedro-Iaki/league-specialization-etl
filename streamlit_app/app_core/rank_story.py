"""Competitive context on the frozen, full-base audience map."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app_core.audience_segments import RANK_GROUPS, rank_context, segment_counts
from app_core.audience_story import PAGE_CSS, story_history_lens, story_segment_methods, story_segments
from app_core.i18n import st, story_text, t, terminology_selector
from app_core.segment_presentation import audience_map_figure, band_label, map_display_table, map_orders
from app_core.story import story_footer, story_prose, story_section, story_start


def tiers_page() -> None:
    terminology_selector()
    players = story_start(
        3, story_text('Put activity in competitive context.', 'Put mastery in tier context.'),
        'Compare accumulated activity within each rank group. Recorded ranked volume and retained history let you inspect different audiences while keeping the same activity ranges.',
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    prepared = story_segments(players)
    if prepared is None:
        story_footer(3)
        return
    base, reference = prepared
    units = st.segmented_control('Activity units', ['Score', 'Estimated hours'], default='Score', key='story_rank_units') or 'Score'
    engagement_options = ['All', *map_orders(base, reference, 'engagement_band')]
    engagement_names = {code: t('All ranked volumes') if code == 'All' else band_label(reference, 'engagement_band', code)
                        for code in engagement_options}
    engagement = st.selectbox('Ranked games recorded', engagement_options,
                             format_func=engagement_names.__getitem__, key='story_rank_engagement')
    history = story_history_lens(base, reference, key='story_rank_history')
    invert = st.toggle('Put rank groups across the chart', key='story_rank_invert')
    selected = base
    if engagement != 'All':
        selected = selected.loc[selected.engagement_band.eq(engagement)]
    if history != 'All':
        selected = selected.loc[selected.history_band.eq(history)]
    orders = {dimension: map_orders(base, reference, dimension) for dimension in ['activity_band', 'rank_group']}
    cells = segment_counts(selected, ['activity_band', 'rank_group'], conditional_on=['rank_group'], levels=orders)
    context = rank_context(reference).set_index('rank_group').loc[RANK_GROUPS]
    labels = {}
    for group in RANK_GROUPS:
        prevalence = t(f'{context.loc[group, "reference_share"]:.2%}')
        labels[group] = f'{t(group)}<br>{prevalence}'
    story_section('01 · Competitive context', 'How is activity distributed within each rank group?')
    st.caption('Rank-label percentages describe the saved overall reference population, not the filtered audience. Each rank group is distributed across activity ranges; inversion changes the layout only.')
    figure = audience_map_figure(
        cells, reference, orders=orders, units=units, labels=labels,
        x_dimension='rank_group' if invert else 'activity_band',
        y_dimension='activity_band' if invert else 'rank_group', metric_label='Share within rank', maximum=1,
    )
    figure.update_xaxes(tickfont_size=10)
    st.plotly_chart(figure, key='story-rank-map', width='stretch', config={'displayModeBar': False})
    st.caption('Shares within each rank group total 100% before suppression. A dash marks no observations or limited support. Colors use the same 0–100% scale for every filter.')
    st.caption('Saved reference: October 10, 2026 · NA ranked solo/duo · [OP.GG tier statistics](https://op.gg/lol/statistics/tiers). Lowest: Iron–Silver; Medium: Gold–Platinum; High: Emerald; Highest: Diamond–Challenger.')
    st.caption(t('Highest-group behavior represents {p0} of the overall reference; {p1} has no observations and {p2} has sparse individual-tier support. Missing tiers are not assigned the behavior of observed tiers.',
                 p0=f'{context.loc["Highest", "supported_share"]:.2%}',
                 p1=f'{context.loc["Highest", "unsupported_share"]:.2%}',
                 p2=f'{context.loc["Highest", "sparse_tier_share"]:.2%}'))
    if units == 'Estimated hours':
        st.caption('Hour equivalents assume 600 mastery points per match and 30 minutes per match: mastery / 1,200. Rounded axis ranges are approximate; the underlying score cuts do not change.')
    filtered = engagement != 'All' or history != 'All'
    if filtered:
        share = selected.population_weight.sum() / base.population_weight.sum()
        st.caption(t('The selected audience retains {p0} of the adjusted base. Rank reference labels stay fixed; its actual rank mix is shown in Methods, support and chart data.', p0=f'{share:.1%}'))
    if not cells.estimate.notna().any():
        st.info('This selection has no supported cells. Broaden the filters to inspect a comparison; no audience estimates have been substituted.')
    story_section('02 · What this adds', 'Activity and rank describe different audience dimensions')
    top = cells.loc[cells.activity_band.eq('A5')].set_index('rank_group').estimate
    if np.isfinite(top.loc[['Lowest', 'Highest']]).all():
        story_prose(t(story_text(
            'Above 4m accumulated activity points: {p0} of the Lowest group and {p1} of the Highest group in this selection.',
            'Above 4m lifetime mastery: {p0} of the Lowest tier group and {p1} of the Highest tier group in this selection.'),
            p0=f'{top.loc["Lowest"]:.1%}', p1=f'{top.loc["Highest"]:.1%}'), css='story-prose story-note')
    else:
        story_prose('The Lowest–Highest comparison above 4m is unavailable for this selection. Read supported cells without treating missing estimates as zero.')
    story_prose('These are different players observed at one cutoff. The comparison does not show people climbing ranks, time needed to climb, or a benefit from specializing. Activity across game modes and recorded ranked volume can answer different content and engagement questions.')
    with st.expander('Methods, support and chart data'):
        story_segment_methods(base, reference)
        st.markdown('The denominator of each tile is all selected weighted profiles in its rank group. Engagement and history filters preserve full-base individual-tier weights; they do not recalibrate the remaining audience.')
        st.dataframe(pd.DataFrame(reference['tier_support']).rename(columns={
            'tier': 'Current tier', 'sample_players': 'Observed profiles',
            'population_share': 'Reference share', 'represented': 'Observed tier'}), hide_index=True, width='stretch')
        if filtered:
            mix = segment_counts(selected, ['rank_group'], levels={'rank_group': RANK_GROUPS})
            display = mix[['rank_group', 'estimate', 'status']].copy()
            display.columns = ['Rank group', 'Selected audience share', 'Availability']
            display['Selected audience share'] = display['Selected audience share'].map(lambda value: f'{value:.1%}' if np.isfinite(value) else t('Unavailable'))
            st.dataframe(display, hide_index=True, width='stretch')
            st.caption('Selected-audience shares use its whole weighted denominator. Sparse group shares are hidden without redistributing them to supported groups.')
        st.dataframe(map_display_table(cells, reference), hide_index=True, width='stretch')
        st.download_button(t('Download rank audience map (CSV)'), cells.to_csv(index=False).encode('utf-8'),
                           file_name='activity-within-rank.csv', mime='text/csv', key='story_rank_download')
    story_prose('Next, character types and family interests add what these audiences prefer to play.', css='story-prose story-note')
    story_footer(3)
