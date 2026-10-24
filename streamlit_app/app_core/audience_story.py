"""The opening chapters: a useful output, then the wider audience's engagement."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd

from app_core.audience_segments import (
    load_segment_reference,
    prepare_segments,
    rank_context,
    segment_counts,
)
from app_core.data import DashboardDataError
from app_core.i18n import st, story_text, t, terminology_selector
from app_core.population import effective_sample_size
from app_core.segment_presentation import audience_map_figure, band_label, map_display_table, map_orders
from app_core.story import resource_links, story_card, story_footer, story_prose, story_section, story_start

MAP_DIMENSIONS = ['activity_band', 'engagement_band']
PAGE_CSS = '''<style>
[data-testid="stPlotlyChart"] {padding:0;}
.audience-flow {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;list-style:none;padding:0;margin:1rem 0;}
.audience-flow li {padding:1rem;border-top:2px solid #e2b344;background:#0e1b2b;border-radius:0 0 10px 10px;}
.audience-flow strong {display:block;color:#e8eef6;font-size:.95rem;}
.audience-flow span {display:block;color:#b7c4d4;font-size:.85rem;line-height:1.6;margin-top:.4rem;}
@media(max-width:1100px){.audience-flow{grid-template-columns:repeat(2,minmax(0,1fr));}}
@media(max-width:420px){.audience-flow{grid-template-columns:1fr;}}
</style>'''


def pipeline_page() -> None:
    terminology_selector()
    players = story_start(
        1, story_text('From player behavior to audience decisions.', 'From mastery and rank to audience decisions.'),
        story_text('Understand how much people play, where they stand competitively, and which character families attract them. Then see how those audiences could support customer reporting.',
                   'Connect accumulated mastery, ranked volume, tiers and champion-family interests. A separate synthetic purchase scenario demonstrates how those audiences could support customer reporting.'),
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    story_prose('Player traits come from Riot API observations. Purchase history is simulated; the customer chapter demonstrates a reporting use, not real spending behavior.', css='story-meta')
    prepared = story_segments(players)
    story_section('01 · A useful output', 'An audience split you can inspect')
    if prepared is not None:
        base, reference = prepared
        orders = {dimension: map_orders(base, reference, dimension) for dimension in MAP_DIMENSIONS}
        cells = segment_counts(base, MAP_DIMENSIONS, levels=orders)
        st.plotly_chart(audience_map_figure(cells, reference, orders=orders, compact=True),
                        key='story-audience-preview', width='stretch', config={'displayModeBar': False})
        st.caption('Each tile shows a share of the reference-adjusted audience. Gold marks larger shares; a dash means no observations or limited support.')
        example = under_100_share(base.loc[base.activity_band.eq('A5')])
        if example is not None:
            story_prose(t(story_text(
                'Even among players above 4m accumulated activity points, {p0} have fewer than 100 ranked games recorded.',
                'Even among players above 4m lifetime mastery, {p0} have fewer than 100 ranked games recorded.'),
                p0=f'{example:.1%}'), css='story-prose story-note')
        story_prose('The next chapters add rank, character type and family interests to this view. Focus is an optional detail, not the starting definition.')
    story_section('02 · From source to reporting', 'A traceable route to audience understanding')
    steps = [
        ('Collect observations', 'Riot API rank and character-activity snapshots.'),
        ('Keep dated history', 'Retained observations make time and source limits inspectable.'),
        ('Define audiences', 'Versioned activity, engagement, rank and family measures.'),
        ('Read customer metrics', 'The same definitions accompany an explicitly synthetic purchase scenario.'),
    ]
    items = ''.join(f'<li><strong>{number} · {escape(t(title))}</strong><span>{escape(t(body))}</span></li>'
                    for number, (title, body) in enumerate(steps, 1))
    st.markdown(f'<ol class="audience-flow">{items}</ol>', unsafe_allow_html=True)
    with st.expander('Inspect the engineering and evidence'):
        for column, values in zip(st.columns(3), [
            ('Collection', 'Keep work recoverable', 'Python collection records task state and preserves successful work across interruptions.'),
            ('Analysis', 'Keep definitions inspectable', 'SQL and dbt separate dated source observations from reusable analytical measures.'),
            ('Delivery', 'Keep reporting reproducible', 'Anonymous local snapshots carry version and hash checks; refresh and release are deliberate operations.'),
        ], strict=True):
            with column:
                story_card(*values)
        resource_links()
    story_prose('Start with accumulated activity and recorded competitive play.', css='story-prose story-note')
    story_footer(1)


def audience_page() -> None:
    terminology_selector()
    players = story_start(
        2, 'Accumulated activity and ranked volume tell different stories.',
        story_text('The activity score accumulates across characters and game modes. Ranked games recorded describe competitive volume at the retained observation. Reading both keeps long-run investment distinct from ranked engagement.',
                   'Lifetime mastery covers champions across game modes; total ranked wins and losses give the recorded competitive volume. Neither measure is a recent match-frequency estimate.'),
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    prepared = story_segments(players)
    if prepared is None:
        story_footer(2)
        return
    base, reference = prepared
    units = st.segmented_control('Activity units', ['Score', 'Estimated hours'], default='Score', key='story_activity_units') or 'Score'
    history = story_history_lens(base, reference, key='story_history_lens')
    selected = base if history == 'All' else base.loc[base.history_band.eq(history)]
    orders = {dimension: map_orders(base, reference, dimension) for dimension in MAP_DIMENSIONS}
    cells = segment_counts(selected, MAP_DIMENSIONS, levels=orders)
    story_section('01 · The audience map', 'Read activity and competitive engagement together')
    if history != 'All':
        share = selected.population_weight.sum() / base.population_weight.sum()
        st.caption(t('This history lens retains {p0} of the adjusted base. Tile shares describe that selected audience; band cuts and tier weights stay fixed.', p0=f'{share:.1%}'))
    st.plotly_chart(audience_map_figure(cells, reference, orders=orders, units=units),
                    key='story-engagement-map', width='stretch', config={'displayModeBar': False})
    st.caption('Each tile is a share of the selected reference-adjusted audience. Shares total 100% before display suppression; a dash marks an empty or sparse cell, not zero population interest.')
    if units == 'Estimated hours':
        st.caption('Hour equivalents assume 600 mastery points per match and 30 minutes per match: mastery / 1,200. Rounded axis ranges are approximate; the underlying score cuts do not change.')
    else:
        st.caption(story_text('The accumulated activity score is lifetime mastery across all characters and modes. These readable ranges are fixed, not equal-sized audiences.',
                             'Lifetime mastery spans all champions and modes. Fixed score ranges are presentation bands, not quintiles.'))
    story_section('02 · What this adds', 'High accumulated activity can coexist with low ranked volume')
    overall = under_100_share(selected)
    experienced = under_100_share(selected.loc[selected.activity_band.eq('A5')])
    columns = st.columns(2)
    columns[0].metric('Fewer than 100 ranked games', f'{overall:.1%}' if overall is not None else t('Unavailable'))
    columns[1].metric(story_text('Above 4m activity, fewer than 100 ranked games', 'Above 4m mastery, fewer than 100 ranked games'),
                      f'{experienced:.1%}' if experienced is not None else t('Unavailable'))
    story_prose('The two measures describe different audience needs. They can frame onboarding or content questions; low recorded ranked volume alone does not identify another preferred game mode.')
    with st.expander('Methods, support and chart data'):
        story_segment_methods(base, reference)
        st.caption('The history lens keeps the original full-base weights. Raw shares in downloads retain sparse cells; displayed estimates are masked rather than renormalized.')
        st.dataframe(map_display_table(cells, reference), hide_index=True, width='stretch')
        st.download_button(t('Download audience map (CSV)'), cells.to_csv(index=False).encode('utf-8'),
                           file_name='activity-engagement-audience.csv', mime='text/csv', key='story_engagement_download')
    story_prose('Rank adds competitive context to these activity patterns.', css='story-prose story-note')
    story_footer(2)


def story_history_lens(base: pd.DataFrame, reference: dict, *, key: str) -> str:
    with st.expander('Optional history lens'):
        options = ['All', *map_orders(base, reference, 'history_band')]
        names = {code: t('All retained history markers') if code == 'All' else band_label(reference, 'history_band', code) for code in options}
        history = st.selectbox('Retained history marker', options, format_func=names.__getitem__, key=key)
        st.caption('This is the span since the oldest retained champion last-play marker with positive mastery. It is a lower bound on recorded history, not account creation or tracking duration.')
    return history


def story_segments(players: pd.DataFrame) -> tuple[pd.DataFrame, dict] | None:
    """Use the full matching base; never substitute a legacy paired cohort."""
    try:
        reference = load_segment_reference()
        base, _ = prepare_segments(players, reference)
    except (DashboardDataError, ValueError) as error:
        st.info('This audience view needs the matching family-enriched snapshot and frozen segment reference. The other chapters and explorers remain available.')
        with st.expander('Snapshot details'):
            st.code(str(error))
        return None
    return base, reference


def under_100_share(frame: pd.DataFrame) -> float | None:
    """A supported frequency over the full selected audience, not a reweighted subset."""
    valid = frame.loc[np.isfinite(frame.population_weight) & frame.population_weight.gt(0)]
    counted = valid.loc[valid.total_games.ge(0) & valid.total_games.lt(100)]
    if len(counted) < 30 or effective_sample_size(counted.population_weight) < 20:
        return None
    return float(counted.population_weight.sum() / valid.population_weight.sum())


def story_segment_methods(base: pd.DataFrame, reference: dict) -> None:
    context = rank_context(reference)
    st.markdown('Weights are calibrated once by individual rank tier on the complete profile scope, before history or audience filters. Missing family, type or focus evidence does not remove people from this base.')
    st.markdown(t('Supported tiers cover {p0} of the saved reference; {p1} has no observations. Sparse individual tiers remain a separate limitation.',
                  p0=f'{context.supported_share.sum():.2%}', p1=f'{context.unsupported_share.sum():.2%}'))
    st.markdown('The saved October 10, 2026 NA solo/duo percentages are attributed to [OP.GG tier statistics](https://op.gg/lol/statistics/tiers). They are author-supplied historical values, not a newly verified population census. Rank adjustment does not correct within-tier collection bias.')
    st.markdown('Frequency cells need at least 30 observed profiles and effective support of 20. Empty and sparse cells retain their denominators. These checks are not confidence intervals or estimates of market size.')
    st.caption(t('Technical support: {p0} observed profiles; effective support {p1}. Observation cutoff: {p2}.',
                 p0=f'{len(base):,}', p1=f'{effective_sample_size(base.population_weight):,.1f}', p2=reference['as_of_date']))
    st.caption('Activity ranges are upper-inclusive and lower-exclusive; zero and missing values have separate categories. This snapshot has no zero-game profiles and cannot describe the unranked population.')
