"""Quiet, directly labeled charts for the six-page narrative."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.charts import style_figure
from app_core.config import BLUE, GOLD, MIN_SUPPORT_PLAYERS, MUTED, PLAYSTYLE_COLORS, PLAYSTYLE_LABELS, TEXT
from app_core.i18n import t
from app_core.story_analysis import CASE_TIER_ORDER

STORY_COLORS = [GOLD, "#2EC4B6", BLUE, "#9B7EDE"]


def story_lines(
    frame: pd.DataFrame, x: str, y: str, series: str, order: list[str], *, ratio: bool = False,
) -> go.Figure:
    fig = go.Figure()
    for index, (label, group) in enumerate(frame.groupby(series, observed=True, sort=False)):
        group = group.set_index(x).reindex(order)
        values = group[y].copy()
        if "players" in group and ratio:
            values = values.where(group["players"].ge(MIN_SUPPORT_PLAYERS))
        counts = group["players"] if "players" in group else np.full(len(group), np.nan)
        fig.add_trace(go.Scatter(
            x=order, y=values, name=PLAYSTYLE_LABELS.get(label, label), mode="lines+markers",
            line={"color": PLAYSTYLE_COLORS.get(label, STORY_COLORS[index % len(STORY_COLORS)]), "width": 2.5},
            connectgaps=False, customdata=counts,
            hovertemplate=("%{x}<br>%{fullData.name}: %{y:.2f}×<br>Players: %{customdata:,}<extra></extra>"
                           if ratio else "%{x}<br>%{fullData.name}: %{y:.1%}<br>Players: %{customdata:,}<extra></extra>"),
        ))
    if ratio:
        fig.add_hline(y=1, line_dash="dot", line_color=MUTED)
    fig.update_yaxes(title="Observed / mastery-expected share" if ratio else "Specialist share", tickformat=".1f" if ratio else ".0%", rangemode="tozero")
    fig.update_xaxes(categoryorder="array", categoryarray=order, title="Current tier" if x == "tier" else "Lifetime mastery quintile")
    return style_figure(fig, height=330)


def coverage_chart(coverage: pd.DataFrame) -> go.Figure:
    positions = list(range(len(coverage)))
    fig = go.Figure(go.Bar(
        x=coverage["players"], y=positions, orientation="h", marker_color=BLUE, width=.35,
        customdata=coverage["stage"], hovertemplate="%{customdata}<br>Players: %{x:,}<extra></extra>",
    ))
    for position, row in zip(positions, coverage.itertuples(), strict=True):
        count = t(f"{row.players:,}")
        fig.add_annotation(x=0, y=position - .2, text=f"{t(row.stage)} · {count}", showarrow=False,
                           xanchor="left", yanchor="bottom", font={"color": TEXT, "size": 11})
    fig.update_xaxes(range=[0, max(1, coverage["players"].max()) * 1.05], title="Players", showgrid=False)
    fig.update_yaxes(range=[len(coverage) - .5, -.8], showgrid=False, showticklabels=False, zeroline=False)
    return style_figure(fig, height=290)


def growth_interval_chart(summary: pd.DataFrame) -> go.Figure:
    visible = summary.loc[summary["observations"].ge(MIN_SUPPORT_PLAYERS)]
    fig = go.Figure(go.Scatter(
        x=visible["mean"], y=visible["playstyle"].map(PLAYSTYLE_LABELS), mode="markers",
        marker={"color": GOLD, "size": 10},
        error_x={"type": "data", "symmetric": False, "array": visible["high"] - visible["mean"],
                 "arrayminus": visible["mean"] - visible["low"], "color": BLUE, "thickness": 3},
        customdata=visible[["observations", "low", "high"]],
        hovertemplate="%{y}<br>Mean: %{x:+.2f}<br>95% interval: %{customdata[1]:+.2f} to %{customdata[2]:+.2f}<br>Player–tier observations: %{customdata[0]:,}<extra></extra>",
    ))
    fig.add_vline(x=0, line_dash="dot", line_color=MUTED)
    fig.update_xaxes(title="LP per game above starting-tier baseline")
    fig.update_yaxes(autorange="reversed")
    return style_figure(fig, height=290)


def case_chart(frame: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for label, color, dash in [("One-tricks", GOLD, "solid"), ("Champion holders", "#2EC4B6", "dot"),
                               ("All-champion one-tricks", MUTED, "dash")]:
        group = frame.loc[frame["series"].eq(label)].set_index("tier").reindex(CASE_TIER_ORDER)
        fig.add_trace(go.Scatter(
            x=CASE_TIER_ORDER, y=group["share"], name=label, mode="lines+markers",
            line={"color": color, "dash": dash, "width": 2.5}, customdata=group[["players", "total"]],
            hovertemplate="%{x}<br>%{fullData.name}: %{y:.1%}<br>Count: %{customdata[0]:,} / %{customdata[1]:,}<extra></extra>",
        ))
    fig.update_xaxes(title="Current tier")
    fig.update_yaxes(title="Share within cohort", tickformat=".0%", rangemode="tozero")
    return style_figure(fig, height=330)
