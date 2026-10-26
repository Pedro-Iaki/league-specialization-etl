"""Shared display labels and readable maps for the frozen audience dimensions."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.audience_segments import RANK_GROUPS, band_order
from app_core.charts import style_figure
from app_core.i18n import story_text, t

MAP_COLORS = [[0, '#14293e'], [.35, '#33536a'], [.7, '#b18d39'], [1, '#f2cb68']]


def dimension_label(dimension: str, units: str = 'Score') -> str:
    if dimension == 'activity_band':
        return t('Total playtime (estimated)') if units == 'Estimated hours' else story_text('Accumulated activity score', 'Lifetime mastery')
    if dimension == 'rank_group':
        return story_text('Rank group', 'Tier group')
    return t({'engagement_band': 'Ranked games recorded', 'history_band': 'Retained history marker',
              'rank_group': 'Rank group'}[dimension])


def band_label(reference: dict, dimension: str, code: str, units: str = 'Score') -> str:
    if code == 'Missing':
        return t('Not recorded')
    spec = reference['bands'][dimension]
    number = int(code.removeprefix(spec['prefix']))
    if number == 0:
        return t('Zero recorded')
    if dimension == 'activity_band':
        labels = ['≤500 h', '500–1,250 h', '1,250–2,083 h', '2,083–3,333 h', '>3,333 h'] if units == 'Estimated hours' else [
            '≤600k', '600k–1.5m', '1.5m–2.5m', '2.5m–4m', '>4m']
        return t(labels[number - 1])
    return t(spec['labels'][number - 1])


def map_orders(base: pd.DataFrame, reference: dict, dimension: str) -> list[str]:
    if dimension == 'rank_group':
        return RANK_GROUPS.copy()
    # Keep the five positive ranges fixed even when a selected slice has empty rows.
    order = band_order(reference, dimension)
    return [code for code in order if code[-1:] in '12345' or base[dimension].eq(code).any()]


def audience_map_figure(cells: pd.DataFrame, reference: dict, *, x_dimension: str = 'activity_band',
                        y_dimension: str = 'engagement_band', units: str = 'Score',
                        orders: dict[str, list[str]], value: str = 'estimate', maximum: float | None = None,
                        metric_label: str = 'Audience share', compact: bool = False,
                        labels: dict[str, str] | None = None) -> go.Figure:
    """Layout only: cells already own the statistic, denominator and support mask.

    Nulls stay unavailable, and every cell gets a readable annotation. Reversing
    axes transposes these same numerical cells without calculating a new share.
    """
    x_order, y_order = orders[x_dimension], orders[y_dimension]
    index = pd.MultiIndex.from_product([y_order, x_order], names=[y_dimension, x_dimension])
    grid = cells.set_index([y_dimension, x_dimension]).reindex(index)
    values = grid[value].to_numpy(dtype=float).reshape(len(y_order), len(x_order))
    finite = values[np.isfinite(values)]
    if maximum is None:
        maximum = max(.01, math.ceil(finite.max() * 100) / 100) if len(finite) else 1
    labels = labels or {}

    def display(dimension, code):
        return labels.get(code, t(code) if dimension == 'rank_group' else band_label(reference, dimension, code, units))

    x_labels = [display(x_dimension, code) for code in x_order]
    y_labels = [display(y_dimension, code) for code in y_order]
    hover = []
    family = 'scored_coverage' in grid
    for _, row in grid.iterrows():
        available = np.isfinite(row[value])
        status = t('No observations') if pd.isna(row.profiles) or row.profiles == 0 else t('Limited support')
        if family and pd.notna(row.profiles) and row.profiles > 0:
            if value == 'affinity_estimate' and row.scored_profiles == 0:
                status = t('No scored evidence')
            elif value == 'primary_estimate' and row.primary_profiles == 0:
                status = t('No primary observations')
        hover.append([f'{row[value]:.1%}' if available else status,
                      int(row.profiles) if pd.notna(row.profiles) else 0,
                      round(row.effective_players, 1) if pd.notna(row.effective_players) else 0])
        if family:
            hover[-1].extend([row.scored_coverage, row.scored_profiles, row.scored_effective_players,
                              row.primary_profiles, row.primary_effective_players])
    custom = np.asarray(hover, dtype=object).reshape(len(y_order), len(x_order), 8 if family else 3).tolist()
    family_hover = '' if not family else (
        f'<br>{t("Scored coverage")}: %{{customdata[3]:.1%}}'
        f'<br>{t("Scored profiles")}: %{{customdata[4]:,}}'
        f'<br>{t("Scored effective support")}: %{{customdata[5]:.1f}}'
        f'<br>{t("Primary profiles")}: %{{customdata[6]:,}}'
        f'<br>{t("Primary effective support")}: %{{customdata[7]:.1f}}')
    fig = go.Figure(go.Heatmap(
        x=x_labels, y=y_labels, z=values.tolist(), customdata=custom,
        colorscale=MAP_COLORS, zmin=0, zmax=maximum, xgap=3, ygap=3,
        showscale=not compact, hoverongaps=True,
        colorbar={'orientation': 'h', 'x': .5, 'xanchor': 'center', 'y': -.43,
                  'len': .8, 'thickness': 9, 'tickformat': '.0%', 'nticks': 4, 'tickangle': 0,
                  'title': {'text': t(metric_label), 'side': 'top'}},
        hovertemplate=(f'{dimension_label(x_dimension, units)}: %{{x}}<br>'
                       f'{dimension_label(y_dimension, units)}: %{{y}}<br>'
                       f'{t(metric_label)}: %{{customdata[0]}}<br>'
                       f'{t("Observed profiles")}: %{{customdata[1]:,}}<br>'
                       f'{t("Effective support")}: %{{customdata[2]:.1f}}{family_hover}<extra></extra>'),
    ))
    for y, row in enumerate(values):
        for x, number in enumerate(row):
            fig.add_annotation(x=x_labels[x], y=y_labels[y],
                               text=f'{number:.1%}' if np.isfinite(number) else '—', showarrow=False,
                               font={'size': 11 if compact else 13,
                                     'color': '#081321' if np.isfinite(number) and number / maximum > .55 else '#e8eef6'})
    style_figure(fig, height=330 if compact else 520)
    fig.update_layout(margin={'l': 65, 'r': 12, 't': 10, 'b': 60 if compact else 140})
    fig.update_xaxes(title=dimension_label(x_dimension, units), categoryorder='array',
                     categoryarray=x_labels, tickmode='array', tickvals=x_labels,
                     ticktext=[label.replace('–', '–<br>') for label in x_labels], tickangle=0,
                     showgrid=False, automargin=True, tickfont_size=11)
    fig.update_yaxes(title=dimension_label(y_dimension, units), categoryorder='array',
                     categoryarray=y_labels, showgrid=False, automargin=True, tickfont_size=11)
    return fig


def map_display_table(cells: pd.DataFrame, reference: dict) -> pd.DataFrame:
    result = cells.copy()
    for dimension in reference['bands']:
        if dimension in result:
            result[dimension] = result[dimension].map(lambda code, d=dimension: band_label(reference, d, code))
    result['Estimated share (%)'] = (result['estimate'] * 100).round(2)
    result['Effective support'] = result.effective_players.round(1)
    result = result.rename(columns={'activity_band': 'Accumulated activity score', 'engagement_band': 'Ranked games recorded',
                                    'rank_group': 'Rank group', 'profiles': 'Observed profiles', 'status': 'Availability'})
    columns = ['Accumulated activity score', 'Ranked games recorded', 'Rank group',
               'Estimated share (%)', 'Observed profiles', 'Effective support', 'Availability']
    return result[[column for column in columns if column in result]]
