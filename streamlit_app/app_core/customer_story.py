"""A customer-reporting demonstration using the preserved synthetic scenario."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.audience_segments import CHARACTER_TYPES, load_segment_reference
from app_core.audience_story import PAGE_CSS
from app_core.charts import style_figure
from app_core.config import BLUE, GOLD
from app_core.customer_audiences import customer_summary, family_customer_summary, prepare_customers
from app_core.data import DashboardDataError, load_optional_dataset
from app_core.family_affinity import STATE_LABELS
from app_core.family_audience import family_catalogue
from app_core.i18n import st, story_text, t, terminology_selector
from app_core.segment_presentation import band_label, dimension_label, map_orders
from app_core.story import story_footer, story_prose, story_section, story_start

LENSES = {'All scenario profiles': None, 'Accumulated activity': 'activity_band',
          'Recorded ranked volume': 'engagement_band', 'Rank group': 'rank_group', 'Character type': 'character_type'}


def transactions_page() -> None:
    terminology_selector()
    story_start(5, 'Explore audiences with simulated purchases.',
                'Use the same family, activity and rank definitions to compare participation, purchaser spending and the distribution of cash in a fictional purchase scenario.')
    st.markdown(PAGE_CSS, unsafe_allow_html=True)
    st.info('Synthetic customer demonstration. Purchases and group differences are generated from editable assumptions; they are not observed Riot customer behavior or evidence of targeting effectiveness.')
    try:
        business = load_optional_dataset('business_players')
        if business is None:
            raise DashboardDataError('Business snapshot is absent.')
        reference = load_segment_reference()
        base = prepare_customers(business, reference)
    except (DashboardDataError, ValueError) as error:
        st.info('This customer view needs the matching family-enriched business snapshot, frozen scenario metadata and audience reference. Navigation remains available.')
        with st.expander('Snapshot details'):
            st.code(str(error))
        story_footer(5)
        return
    scenario = business.attrs['business_scenario']
    start, end = scenario['purchase_window_start'], scenario['purchase_window_end']
    st.caption(t('Synthetic purchases: {p0} through {p1}, inclusive (60 days, USD cash). Current audience traits: {p2}; original scenario profiles frozen: {p3}. These later traits describe current audiences, not preferences at the purchase date.',
                 p0=start, p1=end, p2=reference['as_of_date'], p3=scenario['as_of_date']))
    catalogue = family_catalogue()
    ids = list(catalogue)
    complete = family_customer_summary(base, ids)
    order = complete.loc[complete.family_category.isin(ids)].sort_values(['profiles', 'family_category'], ascending=[False, True]).family_category.tolist()
    top = order[:6]
    chart_order = [*top, 'Other families', *STATE_LABELS.values()]
    overview = family_customer_summary(base, ids, top)
    chart_order = [code for code in chart_order if code in set(overview.family_category)]
    lens_names = {name: story_text(name, 'Lifetime mastery' if name == 'Accumulated activity' else 'Tier group' if name == 'Rank group' else name) for name in LENSES}
    lens = st.selectbox('Refine the scenario audience', list(LENSES), format_func=lens_names.__getitem__, key='story_customer_lens')
    dimension = LENSES[lens]
    selected = base
    if dimension:
        levels = (list(CHARACTER_TYPES.values()) + ['Unavailable'] if dimension == 'character_type'
                  else map_orders(base, reference, dimension))
        if dimension == 'rank_group' and base.rank_group.eq('Unrecognized').any():
            levels = [*levels, 'Unrecognized']
        names = {code: (story_text(code, dict(zip(CHARACTER_TYPES.values(), CHARACTER_TYPES, strict=True)).get(code, code))
                        if dimension == 'character_type' else t(code) if dimension == 'rank_group'
                        else band_label(reference, dimension, code)) for code in levels}
        chosen = st.selectbox('Current audience range', levels, format_func=names.__getitem__, key=f'story_customer_{dimension}')
        selected = base.loc[base[dimension].eq(chosen)]
        st.caption(t('Current audience lens: {p0} · {p1}. The recorded audience traits and fixed ranges are used; the original scenario rows and purchase window stay unchanged.',
                     p0=dimension_label(dimension) if dimension != 'character_type' else t('Character type'), p1=names[chosen]))
    summary = family_customer_summary(selected, ids, top).set_index('family_category').reindex(chart_order).reset_index()
    total = customer_summary(selected.assign(total='All'), ['total'])
    aggregate = total.iloc[0] if len(total) else None
    columns = st.columns(3)
    columns[0].metric('Share of scenario profiles retained', f'{len(selected) / len(base):.1%}')
    columns[1].metric('Synthetic purchaser share', percent(aggregate.purchaser_estimate) if aggregate is not None else t('Unavailable'))
    columns[2].metric('Synthetic cash per purchaser (USD)', dollars(aggregate.cash_per_purchaser_estimate) if aggregate is not None else t('Unavailable'))
    st.caption(t('Selected scenario: {p0} profiles, {p1} cash purchasers and {p2} simulated cash. These are unweighted scenario totals, not population or market estimates.',
                 p0=f'{len(selected):,}', p1=f'{int(selected.cash_buyer.sum()):,}', p2=dollars(selected.cash_cents.sum() / 100)))
    if selected.empty:
        st.info('No scenario profiles match this range. Choose another range; missing audiences are not replaced with broader results.')
    story_section('01 · Participation and amount', 'Who buys, and how much do purchasers spend?')
    story_prose('Purchaser share measures how common cash purchases are. Cash per purchaser measures the amount among those with cash events. Reading both separates participation from purchase amount.')
    left, right = st.columns(2)
    with left:
        st.plotly_chart(customer_chart(summary, catalogue, 'purchaser_estimate'), key='story-customer-purchasers', width='stretch', config={'displayModeBar': False})
        st.caption('Synthetic purchaser share: cash-event purchasers divided by all profiles in each audience, including nonbuyers. Groups need 30 profiles; a supported zero remains zero.')
    with right:
        st.plotly_chart(customer_chart(summary, catalogue, 'cash_per_purchaser_estimate'), key='story-customer-amount', width='stretch', config={'displayModeBar': False})
        st.caption('Synthetic cash per purchaser: fiat USD divided by cash-event purchasers in the same window. Groups need 30 purchasers as well as 30 profiles; no purchasers means an undefined amount.')
    st.caption('The six largest primary-family audiences in the complete scenario determine the order, before any refinement. Other families combines the remaining exclusive primary labels. Shared top and missing-evidence states stay separate; sparse values are hidden without changing denominators.')
    supported = summary.loc[summary.family_category.isin(ids) & summary.purchaser_estimate.notna() & summary.cash_per_purchaser_estimate.notna()]
    if not supported.empty:
        example = supported.iloc[0]
        story_prose(t('Illustration: {p0} has {p1} purchaser share and {p2} cash per purchaser in this generated window. This is a way to frame a customer question, not an audience-targeting recommendation.',
                      p0=example.family_category, p1=percent(example.purchaser_estimate), p2=dollars(example.cash_per_purchaser_estimate)), css='story-prose story-note')
    story_section('02 · Size and cash contribution', 'How does audience presence compare with its cash contribution?')
    st.plotly_chart(customer_chart(summary, catalogue, 'composition'), key='story-customer-composition', width='stretch', config={'displayModeBar': False})
    st.caption('Synthetic composition: profile shares divide by all selected scenario profiles; cash shares divide by all selected fiat USD. Exclusive labels count each customer and their cash once, including Shared top and unavailable family evidence. Sparse groups remain in both totals.')
    if not selected.empty and selected.cash_cents.sum() == 0:
        st.info('This selection has no cash events. Purchaser share is zero where supported; cash per purchaser and the cash composition are undefined.')
    story_prose('A real purchase feed could help teams compare audience reach, payer participation and spending scale. These generated shapes demonstrate the reporting structure. A causal promotion or product decision would still require suitable real outcomes and a comparison design.')
    with st.expander('How the demonstration is connected'):
        st.markdown('Real keyed profiles → versioned audience definitions → private player-and-queue association → one anonymous row per scenario customer → grouped cash reporting. Current audience fields are prefixed audience_; original frozen scenario traits are retained separately. No anonymous row-order join is used.')
        st.markdown('The seeded generator conditions purchases on frozen rank, role, mastery, focus and other configured traits. Family labels were attached later; they are not an independently validated cause of spending. Related traits can carry the designed relationships into these comparisons.')
        st.markdown('Only fiat events contribute USD cash. Buying virtual currency and later acquiring content are separate events; content acquisitions add no second cash revenue. Nonbuyers remain in the purchaser-share denominator. Integer cents are summed before ratios are calculated.')
        st.caption(t('Scenario {p0} · generator {p1} · seed {p2} · complete cohort {p3}. Generation and export dates do not replace the purchase or audience dates.',
                     p0=scenario['scenario_id'], p1=scenario['generator_version'], p2=scenario['generator_seed'], p3=f'{scenario["player_count"]:,}'))
        st.caption(t('Current audience snapshots span {p0} through {p1}; their as-of cutoff is {p2}. The current classification must not be read as a historical spending predictor.',
                     p0=str(pd.to_datetime(base.audience_snapshot_date).min().date()),
                     p1=str(pd.to_datetime(base.audience_snapshot_date).max().date()), p2=reference['as_of_date']))
        st.markdown('Definitions: [synthetic transactions](https://github.com/Pedro-Iaki/league-specialization-etl/blob/main/docs/wiki/simulated-transactions.md) · [editable scenario assumptions](https://github.com/Pedro-Iaki/league-specialization-etl/blob/main/src/sample/scenario.py).')
    with st.expander('Methods, support and chart data'):
        st.caption('All results here use one row per frozen scenario customer, not gameplay population weights. The complete family table preserves raw figures and masked estimates; chart suppression never reallocates cash or customers to supported groups.')
        full = family_customer_summary(selected, ids)
        full['Family members'] = full.family_category.map(lambda fid: ', '.join(member['character'] for member in catalogue[fid]['members']) if fid in catalogue else '')
        st.dataframe(full, hide_index=True, width='stretch')
        st.dataframe(summary, hide_index=True, width='stretch')
        st.download_button(t('Download synthetic family customer summary (CSV)'), full.to_csv(index=False).encode('utf-8'),
                           file_name='synthetic-family-customers.csv', mime='text/csv', key='story_customer_download')
    story_prose('The final chapter opens the engineering and evidence behind these audience definitions and reports.', css='story-prose story-note')
    story_footer(5, 'business.py', 'Business sample explorer')


def percent(value: float) -> str:
    return f'{value:.1%}' if np.isfinite(value) else t('Unavailable')


def dollars(value: float) -> str:
    return f'${value:,.2f}' if np.isfinite(value) else t('Unavailable')


def customer_chart(summary: pd.DataFrame, catalogue: dict, metric: str) -> go.Figure:
    labels = [f'{code}<br>{" / ".join(member["character"] for member in catalogue[code]["members"][:2])}'
              if code in catalogue else t(code) for code in summary.family_category]
    fields = [('audience_estimate', 'Scenario profiles', BLUE), ('cash_share_estimate', 'Synthetic cash', GOLD)] if metric == 'composition' else [
        (metric, 'Synthetic cash per purchaser (USD)' if metric == 'cash_per_purchaser_estimate' else 'Synthetic purchaser share', GOLD)]
    fig = go.Figure()
    for field, name, color in fields:
        values = summary[field]
        text = [(dollars(value) if metric == 'cash_per_purchaser_estimate' else percent(value)) if np.isfinite(value) else '' for value in values]
        amount = metric == 'cash_per_purchaser_estimate'
        fig.add_trace(go.Bar(x=values.tolist(), y=labels, orientation='h', name=t(name), marker_color=color,
                             text=text, textposition='outside', cliponaxis=False,
                             customdata=summary[['profiles', 'cash_purchasers', 'cash_usd']].to_numpy().tolist(),
                             hovertemplate=(f'%{{y}}<br>{t(name)}: ' + ('USD %{x:.2f}' if amount else '%{x:.1%}')
                                            + f'<br>{t("Scenario profiles")}: %{{customdata[0]:,}}<br>{t("Cash purchasers")}: %{{customdata[1]:,}}'
                                            + f'<br>{t("Synthetic cash (USD)")}: %{{customdata[2]:,.2f}}<extra></extra>')))
        if metric != 'composition':
            for label, value, row in zip(labels, values, summary.itertuples(), strict=True):
                if not np.isfinite(value):
                    status = 'No observations' if pd.isna(row.profiles) or row.profiles == 0 else 'No cash purchasers' if amount and row.cash_purchasers == 0 else 'Limited support'
                    fig.add_annotation(x=0, y=label, text=t(status), showarrow=False, xanchor='left', font_size=10)
    style_figure(fig, height=max(420, len(labels) * (49 if metric == 'composition' else 42) + 75))
    fig.update_layout(barmode='group', showlegend=metric == 'composition', margin={'l': 132, 'r': 45, 't': 45 if metric == 'composition' else 12, 'b': 55 if metric == 'composition' else 75})
    title = ('Share of selected totals' if metric == 'composition' else
             'Synthetic cash<br>per purchaser (USD)' if metric == 'cash_per_purchaser_estimate' else
             'Synthetic purchaser<br>share')
    fig.update_xaxes(title=t(title), tickformat='$,.0f' if metric == 'cash_per_purchaser_estimate' else '.0%', tickfont_size=10)
    if metric != 'cash_per_purchaser_estimate':
        fig.update_xaxes(range=[0, 1.1])
    else:
        finite = summary.cash_per_purchaser_estimate.dropna()
        fig.update_xaxes(range=[0, max(1, finite.max() * 1.45) if len(finite) else 1])
    fig.update_yaxes(autorange='reversed', tickfont_size=10, automargin=True)
    return fig
