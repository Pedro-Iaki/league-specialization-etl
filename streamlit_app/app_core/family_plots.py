"""Shared visualizations for original-family bootstrap evidence."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def family_consistency_figure(families: pd.DataFrame, characters: pd.DataFrame, target: float) -> go.Figure:
    figure = go.Figure()
    for index, row in enumerate(families.itertuples()):
        group = characters.loc[characters.family.eq(row.family)]
        jitter = (group.character_key.to_numpy() % 7 - 3) * .025
        figure.add_trace(go.Scatter(x=group.own_consistency, y=index + jitter, mode='markers',
                                    marker=dict(size=5, color=np.where(group.own_consistency.lt(target), '#dd8b78', '#a3b7ca')),
                                    text=group.character, showlegend=False,
                                    hovertemplate='%{text}<br>Own-family consistency %{x:.1%}<extra></extra>'))
        figure.add_trace(go.Scatter(x=[row.mean_consistency, row.retained_consistency], y=[index, index],
                                    mode='lines', line=dict(color='#6b7e91', width=2), showlegend=False, hoverinfo='skip'))
    for field, name, color, symbol in [('mean_consistency', 'Full family', '#d8a52d', 'circle'),
                                      ('retained_consistency', 'Without weakest members', '#4ea5d9', 'diamond')]:
        figure.add_trace(go.Scatter(x=families[field], y=list(range(len(families))), name=name, mode='markers',
                                    marker=dict(size=10, color=color, symbol=symbol),
                                    customdata=families[['family', 'characters', 'removed_count', 'pattern']],
                                    hovertemplate='%{customdata[0]} · %{customdata[1]} members<br>%{x:.1%}'
                                                  '<br>%{customdata[2]} removed for comparison<br>%{customdata[3]}<extra>%{fullData.name}</extra>'))
    figure.add_vline(x=target, line_dash='dot', line_color='#d8a52d')
    figure.update_layout(height=min(600, max(210, len(families) * 24 + 80)),
                         margin=dict(l=5, r=10, t=5, b=5), legend=dict(orientation='h', y=1.15))
    figure.update_xaxes(range=[-.03, 1.03], tickformat='.0%', title=None)
    figure.update_yaxes(tickvals=list(range(len(families))), ticktext=families.family, autorange='reversed')
    return figure


def co_membership_figure(rows: pd.DataFrame, rates: np.ndarray, selected: str = 'All families') -> go.Figure:
    selected_rows = rows if selected == 'All families' else rows.loc[rows.family.eq(selected)]
    order = []
    for _, group in selected_rows.groupby('family', sort=True):
        remaining = list(group.index)
        current = max(remaining, key=lambda i: (rates[i, remaining].sum() - rates[i, i], -i))
        while remaining:
            order.append(current)
            remaining.remove(current)
            if remaining:
                current = max(remaining, key=lambda i: (rates[current, i], -i))
    matrix = rates[np.ix_(order, order)].copy()
    np.fill_diagonal(matrix, np.nan)
    names = [f'{rows.loc[i, "character"]} · {rows.loc[i, "family"]}' for i in order]
    figure = go.Figure(go.Heatmap(z=matrix, x=names, y=names, zmin=0, zmax=1, colorscale='Blues',
                                 colorbar=dict(title='Together', tickformat='.0%'),
                                 hovertemplate='%{y}<br>%{x}<br>Together %{z:.0%} of repeats<extra></extra>'))
    figure.update_layout(height=min(850, max(380, len(order) * 20)), margin=dict(l=10, r=10, t=10, b=10))
    figure.update_yaxes(autorange='reversed')
    if selected == 'All families':
        ends = np.flatnonzero(rows.loc[order, 'family'].to_numpy()[:-1] != rows.loc[order, 'family'].to_numpy()[1:])
        for end in ends:
            figure.add_hline(y=float(end) + .5, line_width=1, line_color='#888')
            figure.add_vline(x=float(end) + .5, line_width=1, line_color='#888')
    return figure
