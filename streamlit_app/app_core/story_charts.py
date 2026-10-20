"""Quiet, directly labeled charts for the six-page narrative."""
from __future__ import annotations

from textwrap import wrap

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.charts import style_figure
from app_core.config import BLUE, GOLD, MIN_SUPPORT_PLAYERS, MUTED, PLAYSTYLE_COLORS, PLAYSTYLE_LABELS, PLAYSTYLE_ORDER, TEXT
from app_core.experience import TIER_GROUPS
from app_core.i18n import focus_label, story_text, t
from app_core.story_analysis import CASE_TIER_ORDER

BAND_COLORS = ["#56B4E9", "#2EC4B6", "#E6B84B", "#D98A56", "#CC79A7"]
BAND_DASHES = ["solid", "dash", "dot", "dashdot", "longdash"]


def audience_composition_chart(frame: pd.DataFrame) -> go.Figure:
    """Complete focus composition within ranks; each bar has one profile denominator."""
    fig = go.Figure()
    for playstyle in PLAYSTYLE_ORDER:
        rows = frame.loc[frame["playstyle"].eq(playstyle)]
        share = rows["share"].where(rows["n"].ge(MIN_SUPPORT_PLAYERS))
        fig.add_trace(go.Bar(
            x=share.tolist(), y=rows["tier_group"].tolist(), orientation="h", name=focus_label(playstyle),
            marker_color=PLAYSTYLE_COLORS[playstyle],
            showlegend=False,
            text=[f"{value:.0%}" if pd.notna(value) and value >= .06 else "" for value in share],
            textposition="inside", insidetextanchor="middle", textfont={"color": "#080f19", "size": 13},
            customdata=rows[["members", "n"]].to_numpy().tolist(),
            hovertemplate="%{y}<br>%{fullData.name}: %{x:.1%}<br>Profiles: %{customdata[0]:,} / %{customdata[1]:,}<extra></extra>",
        ))
    for row in frame.loc[frame["playstyle"].eq(PLAYSTYLE_ORDER[0])].itertuples():
        if row.n < MIN_SUPPORT_PLAYERS:
            fig.add_annotation(x=.5, y=row.tier_group, text="No profiles" if not row.n else "Low support", showarrow=False)
    labels = [f"{t(row.tier_group)}<br>{t('n = {p0}', p0=f'{row.n:,}')}"
              for row in frame.loc[frame["playstyle"].eq(PLAYSTYLE_ORDER[0])].itertuples()]
    style_figure(fig, height=280)
    fig.update_layout(barmode="stack", margin={"l": 110, "r": 16, "t": 12, "b": 55})
    fig.update_yaxes(categoryorder="array", categoryarray=TIER_GROUPS, autorange="reversed", showgrid=False,
                     tickvals=TIER_GROUPS, ticktext=labels, tickfont={"size": 11}, fixedrange=True)
    fig.update_xaxes(range=[0, 1], tickformat=".0%", title="Share of profiles", fixedrange=True)
    return fig


def audience_band_chart(frame: pd.DataFrame, *, intervals: bool = False) -> go.Figure:
    """One focus group: five band profiles on an ordered rank axis."""
    fig = go.Figure()
    for band, (color, dash) in enumerate(zip(BAND_COLORS, BAND_DASHES, strict=True), 1):
        rows = frame.loc[frame["mastery_band"].eq(band)].set_index("tier_group").reindex(TIER_GROUPS)
        share = rows["share"].where(rows["n"].ge(MIN_SUPPORT_PLAYERS))
        fig.add_trace(go.Scatter(
            x=list(range(4)), y=share.tolist(), mode="lines+markers", connectgaps=False,
            name=story_text("Activity band {p0}", "Mastery band {p0}", p0=band),
            line={"color": color, "dash": dash, "width": 2.5}, marker={"size": 7}, showlegend=False,
            error_y={"type": "data", "symmetric": False, "array": (rows["upper"] - share).tolist(),
                     "arrayminus": (share - rows["lower"]).tolist(), "visible": intervals, "thickness": 1, "width": 3},
            customdata=rows[["members", "n", "lower", "upper"]].assign(rank=TIER_GROUPS).to_numpy().tolist(),
            hovertemplate="%{fullData.name}<br>%{customdata[4]}: %{y:.1%}<br>Profiles: %{customdata[0]:,} / %{customdata[1]:,}<br>95% Wilson: %{customdata[2]:.1%}–%{customdata[3]:.1%}<extra></extra>",
        ))
    upper = frame.loc[frame["n"].ge(MIN_SUPPORT_PLAYERS), "upper"].max()
    maximum = min(1, max(.1, np.ceil(upper * 10) / 10)) if pd.notna(upper) else .1
    style_figure(fig, height=310)
    fig.update_layout(margin={"l": 48, "r": 12, "t": 16, "b": 75}, hovermode="closest")
    fig.update_xaxes(tickmode="array", tickvals=list(range(4)), ticktext=[t(group) for group in TIER_GROUPS],
                     tickangle=-15, tickfont={"size": 10}, title=story_text("Rank", "Tier"), fixedrange=True)
    fig.update_yaxes(range=[0, maximum], title="Share of profiles", tickformat=".0%", nticks=5, fixedrange=True)
    return fig


def audience_role_chart(frame: pd.DataFrame) -> go.Figure:
    roles = frame["main_role"].drop_duplicates().tolist()
    shares = frame.assign(share=frame["share"].where(frame["n"].ge(MIN_SUPPORT_PLAYERS))).pivot(
        index="main_role", columns="playstyle", values="share",
    ).reindex(index=roles, columns=PLAYSTYLE_ORDER)
    counts = frame.set_index(["main_role", "playstyle"])
    customdata = [[[int(counts.loc[(role, style), "members"]), int(counts.loc[(role, style), "n"]), focus_label(style)]
                   for style in PLAYSTYLE_ORDER] for role in roles]
    fig = go.Figure(go.Heatmap(
        x=list(range(4)), y=roles, z=shares.to_numpy().tolist(), zmin=0, zmax=1,
        colorscale=[[0, "#0e1b2b"], [1, "#257ba6"]], xgap=3, ygap=3, showscale=False,
        text=[[f"{value:.1%}" if pd.notna(value) else "Not shown" for value in row] for row in shares.to_numpy()],
        texttemplate="%{text}", textfont={"size": 11, "color": "#e8eef6"}, customdata=customdata,
        hovertemplate="%{y}<br>%{customdata[2]}: %{z:.1%}<br>Profiles: %{customdata[0]:,} / %{customdata[1]:,}<extra></extra>",
    ))
    style_figure(fig, height=390)
    fig.update_layout(margin={"l": 85, "r": 20, "t": 8, "b": 120})
    fig.update_xaxes(tickvals=list(range(4)), ticktext=["<br>".join(wrap(focus_label(style), 12)) for style in PLAYSTYLE_ORDER], tickangle=0,
                     tickfont={"size": 9}, fixedrange=True)
    fig.update_yaxes(autorange="reversed", tickvals=roles, ticktext=["<br>".join(wrap(t(role), 13)) for role in roles],
                     tickfont={"size": 10}, fixedrange=True)
    return fig


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
