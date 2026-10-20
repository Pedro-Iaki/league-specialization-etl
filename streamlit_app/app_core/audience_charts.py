"""Rank context, concentration distributions and the progressive audience grid."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app_core.audience import RANK_GROUPS
from app_core.charts import style_figure
from app_core.config import MIN_SUPPORT_PLAYERS, TEXT
from app_core.i18n import story_text, t
from app_core.story_charts import BAND_COLORS, PROFILE_DASHES, RANK_COLORS


def rank_count_chart(banded: pd.DataFrame) -> go.Figure:
    counts = banded.rank_group.value_counts().reindex(RANK_GROUPS, fill_value=0)
    shares = counts / max(1, len(banded))
    fig = go.Figure(
        go.Bar(
            x=counts.tolist(),
            y=RANK_GROUPS,
            orientation="h",
            marker_color=RANK_COLORS,
            text=[f"{n:,} · {share:.1%}" for n, share in zip(counts, shares, strict=True)],
            textposition="outside",
            cliponaxis=False,
            customdata=shares.tolist(),
            hovertemplate="%{y}<br>Profiles: %{x:,}<br>Share: %{customdata:.1%}<extra></extra>",
        )
    )
    style_figure(fig, height=285)
    fig.update_layout(margin={"l": 110, "r": 75, "t": 15, "b": 50})
    fig.update_xaxes(range=[0, max(1, counts.max()) * 1.25], title="Profiles", fixedrange=True)
    fig.update_yaxes(categoryorder="array", categoryarray=RANK_GROUPS, autorange="reversed", fixedrange=True)
    return fig


def rank_band_sizes_chart(cells: pd.DataFrame) -> go.Figure:
    table = (
        cells.loc[cells.window.eq("active_pool_lifetime")]
        .pivot(index="activity_band", columns="rank_group", values="n")
        .reindex(columns=RANK_GROUPS)
    )
    fig = go.Figure(
        go.Heatmap(
            x=list(range(4)),
            y=list(range(1, 6)),
            z=table.to_numpy().tolist(),
            text=[[f"{n:,}" for n in row] for row in table.to_numpy()],
            texttemplate="%{text}",
            colorscale=[[0, "#0e1b2b"], [1, "#257ba6"]],
            zmin=0,
            showscale=False,
            xgap=3,
            ygap=3,
            customdata=[[rank for rank in RANK_GROUPS] for _ in range(5)],
            hovertemplate="%{customdata}<br>Band %{y}<br>Profiles: %{z:,}<extra></extra>",
        )
    )
    style_figure(fig, height=285)
    fig.update_layout(margin={"l": 55, "r": 10, "t": 15, "b": 65})
    fig.update_xaxes(
        tickvals=list(range(4)),
        ticktext=[t(r).replace("-", "–<br>") for r in RANK_GROUPS],
        tickfont={"size": 10},
        fixedrange=True,
    )
    fig.update_yaxes(
        autorange="reversed",
        tickvals=list(range(1, 6)),
        title=story_text("Activity band", "Mastery band"),
        fixedrange=True,
    )
    return fig


def concentration_chart(cells: pd.DataFrame, *, bands_on_x: bool, quartiles: bool) -> go.Figure:
    series = RANK_GROUPS if bands_on_x else range(1, 6)
    positions = list(range(1, 6)) if bands_on_x else RANK_GROUPS
    series_field, axis_field = ("rank_group", "activity_band") if bands_on_x else ("activity_band", "rank_group")
    colors = RANK_COLORS if bands_on_x else BAND_COLORS
    fig = go.Figure()
    for i, group in enumerate(series):
        rows = cells.loc[cells[series_field].eq(group)].set_index(axis_field).reindex(positions)
        median = rows["median"].where(rows.n.ge(MIN_SUPPORT_PLAYERS))
        position_labels = (
            [story_text("Activity band {p0}", "Mastery band {p0}", p0=p) for p in positions]
            if bands_on_x
            else list(positions)
        )
        fig.add_trace(
            go.Scatter(
                x=list(range(1, 6)) if bands_on_x else list(range(4)),
                y=median.tolist(),
                mode="lines+markers",
                connectgaps=False,
                name=t(group) if bands_on_x else story_text("Activity band {p0}", "Mastery band {p0}", p0=group),
                line={"color": colors[i], "dash": PROFILE_DASHES[i], "width": 2.5},
                marker={"size": 7},
                showlegend=False,
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": (rows.q3 - median).tolist(),
                    "arrayminus": (median - rows.q1).tolist(),
                    "visible": quartiles,
                    "thickness": 1,
                    "width": 3,
                },
                customdata=rows[["n", "q1", "q3", "median_hhi"]].assign(position=position_labels).to_numpy().tolist(),
                hovertemplate="%{fullData.name}<br>%{customdata[4]}<br>Median: %{y:.1%}<br>Middle 50%: %{customdata[1]:.1%}–%{customdata[2]:.1%}<br>Profiles: %{customdata[0]:,}<extra></extra>",
            )
        )
    style_figure(fig, height=340)
    fig.update_layout(margin={"l": 55, "r": 10, "t": 15, "b": 75})
    fig.update_xaxes(
        tickvals=list(range(1, 6)) if bands_on_x else list(range(4)),
        ticktext=[str(p) for p in positions] if bands_on_x else [t(r).replace("-", "–<br>") for r in positions],
        title=story_text("Activity band (low to high)", "Mastery band (low to high)")
        if bands_on_x
        else story_text("Rank", "Tier"),
        tickfont={"size": 11},
        fixedrange=True,
    )
    fig.update_yaxes(
        range=[0, 1],
        title=story_text("Leading-character share", "Leading-champion share"),
        tickformat=".0%",
        fixedrange=True,
    )
    return fig


def recap_chart(grid: pd.DataFrame, *, maximum: int | None = None) -> go.Figure:
    counts = grid.groupby("rank_group").profiles.sum().reindex(RANK_GROUPS)
    titles = [f"{t(rank)}<br>{t('n = {p0}', p0=f'{n:,}')}" for rank, n in counts.items()]
    fig = make_subplots(rows=2, cols=2, subplot_titles=titles, vertical_spacing=0.23, horizontal_spacing=0.12)
    for i, rank in enumerate(RANK_GROUPS):
        table = grid.loc[grid.rank_group.eq(rank)].pivot(index="activity_band", columns="focus_bin", values="profiles")
        custom = [[[t(rank), f"{j * 10}–{(j + 1) * 10}%"] for j in range(10)] for _ in range(5)]
        fig.add_trace(
            go.Heatmap(
                x=[0.05 + 0.1 * j for j in range(10)],
                y=list(range(1, 6)),
                z=table.to_numpy().tolist(),
                coloraxis="coloraxis",
                xgap=1,
                ygap=1,
                customdata=custom,
                hovertemplate="%{customdata[0]}<br>Band %{y}<br>Leading share: %{customdata[1]}<br>Profiles: %{z:,}<extra></extra>",
            ),
            row=i // 2 + 1,
            col=i % 2 + 1,
        )
    style_figure(fig, height=570)
    fig.update_layout(
        margin={"l": 48, "r": 15, "t": 65, "b": 100},
        coloraxis={
            "cmin": 0,
            "cmax": max(1, int(grid.profiles.max()) if maximum is None else maximum),
            "colorscale": [[0, "#0e1b2b"], [1, "#56B4E9"]],
            "colorbar": {
                "orientation": "h",
                "y": -0.2,
                "len": 0.65,
                "thickness": 10,
                "nticks": 3,
                "tickangle": 0,
                "tickfont": {"size": 11},
            },
        },
    )
    fig.update_annotations(font={"size": 12, "color": TEXT})
    fig.update_xaxes(range=[0, 1], tickvals=[0, 0.5, 1], tickformat=".0%", fixedrange=True)
    fig.update_yaxes(
        tickvals=list(range(1, 6)), autorange="reversed", title=story_text("Band", "Band"), fixedrange=True
    )
    return fig
