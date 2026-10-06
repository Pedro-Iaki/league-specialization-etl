from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app_core.analysis import smoothed_relationship
from app_core.config import (
    BACKGROUND,
    BLUE,
    GOLD,
    GRID,
    MIN_SUPPORT_PLAYERS,
    MUTED,
    PANEL,
    PLAYSTYLE_COLORS,
    PLAYSTYLE_LABELS,
    PLAYSTYLE_ORDER,
    ROLE_COLORS,
    ROLE_ORDER,
    TEXT,
    TIER_ORDER,
)


def style_figure(fig: go.Figure, *, height: int = 440, legend_title: str = "") -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "color": TEXT, "size": 13},
        margin={"l": 24, "r": 18, "t": 42, "b": 30},
        legend={
            "title": {"text": legend_title},
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
        },
        hoverlabel={"bgcolor": PANEL, "font_color": TEXT, "bordercolor": "#24364A"},
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, title_font_color=MUTED)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, title_font_color=MUTED)
    return fig


def annotate_sparse_cells(
    fig: go.Figure, x_values: list[str], y_values: list[str], values: np.ndarray, labels: np.ndarray
) -> None:
    """Show support labels even where Plotly omits text for a missing heatmap value."""
    for row, y_label in enumerate(y_values):
        for column, x_label in enumerate(x_values):
            if not np.isfinite(values[row, column]) and labels[row, column]:
                fig.add_annotation(
                    x=x_label, y=y_label, text=labels[row, column],
                    showarrow=False, font={"color": MUTED, "size": 11},
                )


def playstyle_composition_chart(composition: pd.DataFrame) -> go.Figure:
    frame = composition.copy()
    frame["Playstyle"] = frame["active_playstyle"].map(PLAYSTYLE_LABELS)
    color_map = {PLAYSTYLE_LABELS[key]: value for key, value in PLAYSTYLE_COLORS.items()}
    fig = px.bar(
        frame,
        x="tier",
        y="share",
        color="Playstyle",
        color_discrete_map=color_map,
        category_orders={
            "tier": TIER_ORDER,
            "Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER],
        },
        custom_data=["players"],
    )
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>%{fullData.name}: %{y:.1%}<br>Players: %{customdata[0]:,}<extra></extra>"
    )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(tickformat=".0%", title="Share of classified players")
    fig.update_xaxes(title="Current tier")
    return style_figure(fig, legend_title="")


def rank_distribution_chart(players: pd.DataFrame) -> go.Figure:
    frame = players.loc[players["active_playstyle"].isin(PLAYSTYLE_ORDER)].copy()
    frame["Playstyle"] = frame["active_playstyle"].map(PLAYSTYLE_LABELS)
    color_map = {PLAYSTYLE_LABELS[key]: value for key, value in PLAYSTYLE_COLORS.items()}
    fig = px.box(
        frame,
        x="Playstyle",
        y="rank_score",
        color="Playstyle",
        color_discrete_map=color_map,
        category_orders={"Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]},
        points=False,
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="")
    fig.update_yaxes(title="Analytical rank score")
    return style_figure(fig)


def champion_landscape_chart(champions: pd.DataFrame, minimum_games: int = 100) -> go.Figure:
    frame = champions.loc[champions["observed_games"].fillna(0) >= minimum_games].copy()
    dominant_role_columns = {
        "role_top_pct": "Top",
        "role_jungle_pct": "Jungle",
        "role_middle_pct": "Middle",
        "role_bottom_pct": "Bottom",
        "role_support_pct": "Support",
    }
    available = [column for column in dominant_role_columns if column in frame]
    frame["Dominant role"] = frame[available].idxmax(axis=1).map(dominant_role_columns) if available else "Unknown"
    frame["Observed games"] = frame["observed_games"].fillna(0)
    fig = px.scatter(
        frame,
        x="active_play_rate",
        y="lp_per_game_lift_vs_tier",
        size="Observed games",
        color="Dominant role",
        color_discrete_map=ROLE_COLORS,
        hover_name="champion_name",
        custom_data=["primary_player_count", "observed_games", "observed_win_rate"],
        size_max=34,
    )
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED, opacity=0.7)
    fig.update_traces(
        hovertemplate=(
            "<b>%{hovertext}</b><br>Active play rate: %{x:.2%}<br>"
            "LP/game lift: %{y:+.2f}<br>Primary players: %{customdata[0]:,}<br>"
            "Observed games: %{customdata[1]:,}<br>Observed win rate: %{customdata[2]:.1%}<extra></extra>"
        )
    )
    fig.update_xaxes(title="Active-pool play rate", tickformat=".1%")
    fig.update_yaxes(title="LP/game lift vs starting-tier baseline")
    return style_figure(fig, height=520, legend_title="Dominant role")


def concentration_distribution_chart(players: pd.DataFrame) -> go.Figure:
    frame = players.loc[players["active_playstyle"].isin(PLAYSTYLE_ORDER)].copy()
    metrics = [
        ("active_top1_share", "Top champion share"),
        ("active_hhi", "HHI concentration"),
        ("active_normalized_entropy", "Normalized entropy"),
        ("active_favoured_champion_count", "Favoured champions"),
    ]
    fig = make_subplots(rows=2, cols=2, subplot_titles=[label for _, label in metrics])
    for index, (column, _label) in enumerate(metrics):
        row, col = divmod(index, 2)
        for playstyle in PLAYSTYLE_ORDER:
            values = frame.loc[frame["active_playstyle"] == playstyle, column].dropna()
            fig.add_trace(
                go.Box(
                    y=values,
                    name=PLAYSTYLE_LABELS[playstyle],
                    marker_color=PLAYSTYLE_COLORS[playstyle],
                    boxpoints=False,
                    legendgroup=playstyle,
                    showlegend=index == 0,
                    hovertemplate=f"{PLAYSTYLE_LABELS[playstyle]}<br>%{{y:.3f}}<extra></extra>",
                ),
                row=row + 1,
                col=col + 1,
            )
    fig.update_layout(boxmode="group")
    return style_figure(fig, height=680)


def transition_heatmap(matrix: pd.DataFrame, counts: pd.DataFrame | None = None) -> go.Figure:
    labels = [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]
    show_sparse = matrix.attrs.get("show_sparse", False)
    if counts is None:
        counts = matrix.attrs.get("support_counts")
    if counts is None:
        counts = pd.DataFrame(np.nan, index=matrix.index, columns=matrix.columns)
        display = matrix.map(lambda value: "—" if pd.isna(value) else f"{value:.1%}")
    else:
        row_support = counts.sum(axis=1)
        supported_cells = (counts >= MIN_SUPPORT_PLAYERS) | (
            counts.eq(0) & row_support.ge(MIN_SUPPORT_PLAYERS).to_numpy()[:, None]
        )
        if not show_sparse:
            matrix = matrix.where(supported_cells)
        display = matrix.map(lambda value: "" if pd.isna(value) else f"{value:.1%}")
        display = display.mask(
            matrix.notna(),
            display + "<br>n=" + counts.fillna(0).astype(int).astype(str),
        )
        if show_sparse:
            display = display.mask(
                matrix.notna() & (counts > 0) & (counts < MIN_SUPPORT_PLAYERS),
                display + " ⚠",
            )
        else:
            display = display.mask((counts > 0) & (counts < MIN_SUPPORT_PLAYERS), f"n<{MIN_SUPPORT_PLAYERS}")
        display = display.mask(matrix.isna() & counts.eq(0), "—")
    data = matrix.to_numpy(dtype=float)
    labels_array = display.to_numpy()
    fig = go.Figure(
        go.Heatmap(
            z=data,
            x=labels,
            y=labels,
            colorscale=[[0, BACKGROUND], [0.35, BLUE], [1, GOLD]],
            customdata=counts.to_numpy(),
            text=np.where(np.isfinite(data), labels_array, ""),
            texttemplate="%{text}",
            hovertemplate="Active: %{y}<br>All-time: %{x}<br>Share: %{z:.1%}<br>Players: %{customdata:,.0f}<extra></extra>",
            colorbar={"title": "Row share", "tickformat": ".0%"},
        )
    )
    annotate_sparse_cells(fig, labels, labels, data, labels_array)
    fig.update_xaxes(title="All-time mastery playstyle")
    fig.update_yaxes(title="Active-pool playstyle", autorange="reversed")
    return style_figure(fig, height=500)


def role_difference_heatmap(matrix: pd.DataFrame, counts: pd.DataFrame | None = None) -> go.Figure:
    labels = [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]
    show_sparse = matrix.attrs.get("show_sparse", False)
    if counts is None:
        counts = matrix.attrs.get("support_counts")
    if show_sparse and matrix.attrs.get("raw_differences") is not None:
        matrix = matrix.attrs["raw_differences"]
    finite = np.abs(matrix.to_numpy(dtype=float))
    finite = finite[np.isfinite(finite)]
    max_abs = max(float(finite.max()) if finite.size else 1.0, 1.0)
    if counts is None:
        counts = pd.DataFrame(np.nan, index=matrix.index, columns=matrix.columns)
    display = matrix.map(lambda value: "" if pd.isna(value) else f"{value:+.1f} pp")
    display = display.mask(
        matrix.notna(),
        display + "<br>n=" + counts.fillna(0).astype(int).astype(str),
    )
    if show_sparse:
        display = display.mask(
            matrix.notna() & (counts > 0) & (counts < MIN_SUPPORT_PLAYERS),
            display + " ⚠",
        )
    else:
        display = display.mask((counts > 0) & (counts < MIN_SUPPORT_PLAYERS), f"n<{MIN_SUPPORT_PLAYERS}")
    display = display.mask(matrix.isna() & counts.eq(0), "—")
    data = matrix.to_numpy(dtype=float)
    labels_array = display.to_numpy()
    y_values = matrix.index.tolist()
    fig = go.Figure(
        go.Heatmap(
            z=data,
            x=labels,
            y=y_values,
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            colorscale=[[0, "#C95364"], [0.5, PANEL], [1, "#2EC4B6"]],
            customdata=counts.to_numpy(),
            text=np.where(np.isfinite(data), labels_array, ""),
            texttemplate="%{text}",
            hovertemplate="Role: %{y}<br>Playstyle: %{x}<br>Difference: %{z:+.1f} pp<br>Players: %{customdata:,.0f}<extra></extra>",
            colorbar={"title": "Percentage points"},
        )
    )
    annotate_sparse_cells(fig, labels, y_values, data, labels_array)
    fig.update_xaxes(title="")
    fig.update_yaxes(title="", autorange="reversed")
    return style_figure(fig, height=440)


def champion_role_chart(champion: pd.Series, over_under: bool = False) -> go.Figure:
    role_columns = {
        "Top": "role_top_pct",
        "Jungle": "role_jungle_pct",
        "Middle": "role_middle_pct",
        "Bottom": "role_bottom_pct",
        "Support": "role_support_pct",
    }
    if over_under:
        roles = list(role_columns)
        differences = [
            100 * ((0 if pd.isna(champion.get(role_columns[role])) else float(champion[role_columns[role]])) - 0.2)
            for role in roles
        ]
        fig = go.Figure(
            go.Bar(
                x=differences,
                y=roles,
                orientation="h",
                marker_color=[ROLE_COLORS[role] for role in roles],
                text=[f"{value:+.1f} pp" for value in differences],
                textposition="outside",
                hovertemplate="%{y}<br>Difference from 20%: %{x:+.1f} pp<extra></extra>",
            )
        )
        fig.add_vline(x=0, line_color=MUTED)
        fig.update_xaxes(title="Difference from equal 20% role share (percentage points)")
        fig.update_yaxes(title="", autorange="reversed")
        return style_figure(fig, height=330)
    fig = go.Figure()
    for role, column in role_columns.items():
        value = champion.get(column)
        value = 0 if pd.isna(value) else float(value)
        fig.add_trace(
            go.Bar(
                x=[value],
                y=["Estimated player-role mix"],
                name=role,
                orientation="h",
                marker_color=ROLE_COLORS[role],
                hovertemplate=f"{role}: %{{x:.1%}}<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title="Share", tickformat=".0%", range=[0, 1])
    fig.update_yaxes(title="")
    return style_figure(fig, height=270)


def champion_playstyle_chart(profile: pd.DataFrame) -> go.Figure:
    frame = profile.loc[profile["playstyle"].isin(PLAYSTYLE_ORDER)].copy()
    frame["Playstyle"] = frame["playstyle"].map(PLAYSTYLE_LABELS)
    color_map = {PLAYSTYLE_LABELS[key]: value for key, value in PLAYSTYLE_COLORS.items()}
    fig = px.bar(
        frame,
        x="Playstyle",
        y="lp_per_game_lift_vs_tier",
        color="Playstyle",
        color_discrete_map=color_map,
        category_orders={"Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]},
        custom_data=["observed_games", "observed_player_count", "current_player_count"],
    )
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    fig.update_traces(
        hovertemplate=(
            "%{x}<br>LP/game lift: %{y:+.2f}<br>Observed games: %{customdata[0]:,}<br>"
            "Observed players: %{customdata[1]:,}<br>Current players: %{customdata[2]:,}<extra></extra>"
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="")
    fig.update_yaxes(title="LP/game lift vs tier")
    return style_figure(fig, height=420)


def cooccurrence_chart(neighbors: pd.DataFrame, top_n: int = 12) -> go.Figure:
    frame = neighbors.head(top_n).sort_values("npmi")
    fig = px.scatter(
        frame,
        x="npmi",
        y="related_champion",
        size="pair_player_count",
        color="lift",
        color_continuous_scale=[[0, BLUE], [1, GOLD]],
        custom_data=["pair_player_count", "lift", "conditional_probability", "jaccard"],
        size_max=28,
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>NPMI: %{x:.3f}<br>Shared players: %{customdata[0]:,}<br>"
            "Lift: %{customdata[1]:.2f}×<br>Conditional overlap: %{customdata[2]:.1%}<br>"
            "Jaccard: %{customdata[3]:.1%}<extra></extra>"
        )
    )
    fig.update_xaxes(title="Normalized pointwise mutual information")
    fig.update_yaxes(title="")
    fig.update_coloraxes(colorbar_title="Lift")
    return style_figure(fig, height=max(390, 34 * len(frame) + 120))


def growth_by_tier_chart(summary: pd.DataFrame) -> go.Figure:
    frame = summary.copy()
    frame["Playstyle"] = frame["playstyle"].map(PLAYSTYLE_LABELS)
    color_map = {PLAYSTYLE_LABELS[key]: value for key, value in PLAYSTYLE_COLORS.items()}
    fig = px.bar(
        frame,
        x="previous_tier",
        y="lp_per_game_lift_vs_tier",
        color="Playstyle",
        barmode="group",
        color_discrete_map=color_map,
        category_orders={
            "previous_tier": TIER_ORDER,
            "Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER],
        },
        custom_data=["observed_games", "intervals", "observed_win_rate"],
    )
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    fig.update_traces(
        hovertemplate=(
            "<b>%{x} · %{fullData.name}</b><br>LP/game lift: %{y:+.2f}<br>"
            "Observed games: %{customdata[0]:,}<br>Intervals: %{customdata[1]:,}<br>"
            "Observed win rate: %{customdata[2]:.1%}<extra></extra>"
        )
    )
    fig.update_xaxes(title="Starting tier")
    fig.update_yaxes(title="LP/game lift vs tier baseline")
    return style_figure(fig, height=520)


def champion_playstyle_heatmap(summary: pd.DataFrame) -> go.Figure:
    pivot = summary.pivot(
        index="primary_champion_name", columns="playstyle", values="lp_per_game_lift_vs_tier"
    ).reindex(columns=PLAYSTYLE_ORDER)
    game_pivot = summary.pivot(index="primary_champion_name", columns="playstyle", values="observed_games").reindex(
        index=pivot.index, columns=PLAYSTYLE_ORDER
    )
    labels = [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]
    values = pivot.to_numpy()
    finite_values = np.abs(values[np.isfinite(values)])
    max_abs = max(float(np.percentile(finite_values, 95)) if finite_values.size else 1.0, 1.0)
    text = np.empty(values.shape, dtype=object)
    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            value = values[row, col]
            games = game_pivot.iloc[row, col]
            text[row, col] = "" if pd.isna(value) else f"{value:+.1f}<br>n={games:,.0f}"
    fig = go.Figure(
        go.Heatmap(
            z=values,
            x=labels,
            y=pivot.index,
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            colorscale=[[0, "#C95364"], [0.5, PANEL], [1, "#2EC4B6"]],
            text=text,
            texttemplate="%{text}",
            customdata=game_pivot.to_numpy(),
            hovertemplate=(
                "Champion: %{y}<br>Playstyle: %{x}<br>LP/game lift: %{z:+.2f}<br>"
                "Observed games: %{customdata:,.0f}<extra></extra>"
            ),
            colorbar={"title": "LP/game lift"},
        )
    )
    fig.update_xaxes(title="")
    fig.update_yaxes(title="", autorange="reversed")
    return style_figure(fig, height=max(520, 32 * len(pivot) + 130))


def specialization_relationship_chart(
    frame: pd.DataFrame,
    x: str,
    x_label: str,
    y_label: str,
    trend: pd.DataFrame | None = None,
    color: str = "tier",
) -> go.Figure:
    tier_label = "Current tier" if y_label.startswith("Recent rank LP/game") else "Starting tier"
    plot = frame.loc[frame[x].notna() & frame["outcome"].notna()].copy()
    custom_columns = [column for column in ("support_games", "period_count") if column in plot]
    fig = px.scatter(
        plot,
        x=x,
        y="outcome",
        color=color if color in plot else None,
        category_orders={"tier": TIER_ORDER, "starting_tier": TIER_ORDER},
        opacity=0.38,
        render_mode="webgl",
        custom_data=custom_columns,
        color_discrete_sequence=[BLUE, GOLD, "#2EC4B6", "#9B7EDE", "#D85F76"],
        labels={"tier": tier_label, "starting_tier": tier_label, x: x_label, "outcome": y_label},
    )
    fig.update_traces(marker={"size": 6})
    x_format = ".1%" if x in {"champion_commitment", "top_champion_share"} else ".3f"
    support_label = "Mastery-weighted games" if x == "champion_commitment" else "Ranked games"
    support_hover = "".join(
        f"<br>{support_label if column == 'support_games' else 'Observed periods'}: %{{customdata[{index}]:,.1f}}"
        for index, column in enumerate(custom_columns)
    )
    fig.update_traces(
        hovertemplate=(
            f"{x_label}: %{{x:{x_format}}}<br>{y_label}: %{{y:+.2f}}"
            f"{support_hover}<extra>%{{fullData.name}}</extra>"
        )
    )
    if trend is not None and not trend.empty and trend["outcome"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=trend[x],
                y=trend["outcome"],
                mode="lines+markers",
                name="Mean within quantile bands",
                line={"color": GOLD, "width": 4},
                marker={"size": 9},
                customdata=trend["players"],
                hovertemplate=(
                    f"{x_label}: %{{x:{x_format}}}<br>Mean {y_label}: %{{y:+.2f}}"
                    "<br>Observations: %{customdata:,}<extra></extra>"
                ),
            )
        )
    smooth = smoothed_relationship(plot, x)
    if not smooth.empty:
        fig.add_trace(go.Scatter(
            x=smooth[x],
            y=smooth["outcome"],
            mode="lines",
            name="Smoothed local median (optional)",
            visible="legendonly",
            line={"color": "#2EC4B6", "width": 3},
            customdata=smooth["players"],
            hovertemplate=(
                f"{x_label}: %{{x:{x_format}}}<br>Local median {y_label}: %{{y:+.2f}}"
                "<br>Nearby observations: %{customdata:,}<extra></extra>"
            ),
        ))
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED, opacity=0.65)
    fig.update_xaxes(title=x_label)
    if x in {"champion_commitment", "top_champion_share"}:
        fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(title=y_label)
    return style_figure(fig, height=580, legend_title=tier_label)


def composition_view_chart(frame: pd.DataFrame, group: str) -> go.Figure:
    plot = frame.copy()
    plot["Playstyle"] = plot["playstyle"].map(PLAYSTYLE_LABELS)
    fig = px.bar(
        plot,
        x=group,
        y="share",
        color="Playstyle",
        color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()},
        category_orders={
            group: TIER_ORDER if group == "tier" else ROLE_ORDER if group == "main_role" else sorted(plot[group].dropna().unique()),
            "Playstyle": [PLAYSTYLE_LABELS[key] for key in PLAYSTYLE_ORDER],
        },
        custom_data=["players"],
    )
    fig.update_layout(barmode="stack")
    fig.update_traces(
        hovertemplate="%{x}<br>%{fullData.name}: %{y:.1%}<br>Players: %{customdata[0]:,}<extra></extra>"
    )
    fig.update_yaxes(title="Share within group", tickformat=".0%")
    fig.update_xaxes(title="Current tier" if group == "tier" else "Current inferred role" if group == "main_role" else "Rank-score band")
    return style_figure(fig, height=460)


def champion_efficiency_landscape(frame: pd.DataFrame, x_label: str, y_label: str) -> go.Figure:
    plot = frame.loc[frame["specialization_axis"].notna() & frame["outcome"].notna()].copy()
    fig = px.scatter(
        plot,
        x="specialization_axis",
        y="outcome",
        size="observed_player_count",
        hover_name="champion_name",
        color="observed_win_rate",
        color_continuous_scale="Tealgrn",
        custom_data=["observed_player_count", "observed_period_count"],
        size_max=36,
    )
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED, opacity=0.65)
    fig.update_traces(
        hovertemplate=(
            f"<b>%{{hovertext}}</b><br>{x_label}: %{{x:.2f}}<br>"
            f"{y_label}: %{{y:+.2f}}<br>Players: %{{customdata[0]:,}}<br>"
            "Periods: %{customdata[1]:,}<extra></extra>"
        )
    )
    fig.update_xaxes(title=x_label)
    fig.update_yaxes(title=y_label)
    fig.update_coloraxes(colorbar_title="Mean player win rate", colorbar_tickformat=".0%")
    return style_figure(fig, height=590)


def playstyle_outcome_chart(frame: pd.DataFrame, value: str, title: str) -> go.Figure:
    plot = frame.copy()
    plot["Playstyle"] = plot["playstyle"].map(PLAYSTYLE_LABELS)
    fig = px.bar(
        plot,
        x="Playstyle",
        y=value,
        color="Playstyle",
        color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()},
        category_orders={"Playstyle": [PLAYSTYLE_LABELS[key] for key in PLAYSTYLE_ORDER]},
        custom_data=["observed_player_count", "observed_period_count"],
    )
    fig.update_layout(showlegend=False)
    value_format = "%{y:.1%}" if value == "observed_win_rate" else "%{y:+.2f} LP/game"
    fig.update_traces(hovertemplate=(
        f"%{{x}}<br>{title}: {value_format}<br>Player–tier observations: %{{customdata[0]:,}}"
        "<br>Observed periods: %{customdata[1]:,}<extra></extra>"
    ))
    fig.update_traces(texttemplate="n=%{customdata[0]}", textposition="outside", selector={"type": "bar"})
    if value != "observed_win_rate":
        fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    else:
        fig.update_yaxes(tickformat=".0%", range=[0, 1])
    fig.update_xaxes(title="")
    fig.update_yaxes(title=title)
    return style_figure(fig, height=430)


def composition_delta_chart(frame: pd.DataFrame, group: str) -> go.Figure:
    plot = frame.copy()
    plot["Playstyle"] = plot["playstyle"].map(PLAYSTYLE_LABELS)
    fig = px.bar(
        plot,
        x=group,
        y="difference_pp",
        color="Playstyle",
        barmode="group",
        color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()},
        category_orders={
            group: TIER_ORDER if group == "tier" else ROLE_ORDER if group == "main_role" else sorted(plot[group].dropna().unique()),
            "Playstyle": [PLAYSTYLE_LABELS[key] for key in PLAYSTYLE_ORDER],
        },
        custom_data=["share", "population_share", "players"],
    )
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    fig.update_traces(
        hovertemplate=(
            "%{x} · %{fullData.name}<br>Difference: %{y:+.1f} pp<br>"
            "Champion players: %{customdata[0]:.1%}<br>All players: %{customdata[1]:.1%}<br>"
            "Champion player count: %{customdata[2]:,}<extra></extra>"
        )
    )
    fig.update_xaxes(title="Current tier" if group == "tier" else "Current inferred role" if group == "main_role" else "Rank-score band")
    fig.update_yaxes(title="Difference from all players in same group (pp)")
    return style_figure(fig, height=460)


def champion_tier_outcome_heatmap(
    style_tiers: pd.DataFrame,
    tier_baselines: pd.DataFrame,
    metric: str,
    over_under: bool,
    minimum_players: int = MIN_SUPPORT_PLAYERS,
) -> go.Figure:
    minimum_players = style_tiers.attrs.get("minimum_players", minimum_players)
    show_sparse = style_tiers.attrs.get("show_sparse", False)
    baseline = tier_baselines.loc[:, ["starting_tier", metric]].rename(columns={metric: "baseline"})
    plot = style_tiers.merge(baseline, on="starting_tier", how="left")
    if over_under:
        multiplier = 100 if metric == "observed_win_rate" else 1
        plot["value"] = multiplier * (plot[metric] - plot["baseline"])
    else:
        plot["value"] = plot[metric]
    tiers = [tier for tier in TIER_ORDER if tier in set(plot["starting_tier"])]
    styles = [style for style in PLAYSTYLE_ORDER if style in set(plot["playstyle"])]
    values = plot.pivot(index="playstyle", columns="starting_tier", values="value").reindex(
        index=styles, columns=tiers
    )
    counts = plot.pivot(index="playstyle", columns="starting_tier", values="observed_player_count").reindex(
        index=styles, columns=tiers
    )
    raw_values = plot.pivot(index="playstyle", columns="starting_tier", values=metric).reindex(
        index=styles, columns=tiers
    )
    baseline_values = plot.pivot(index="playstyle", columns="starting_tier", values="baseline").reindex(
        index=styles, columns=tiers
    )
    if not show_sparse:
        values = values.where(counts >= minimum_players)
    display = values.map(
        lambda value: "" if pd.isna(value)
        else f"{value:+.1f}" if over_under or metric != "observed_win_rate"
        else f"{value:.0%}"
    )
    if not show_sparse:
        display = display.mask((counts > 0) & (counts < minimum_players), f"n<{minimum_players}")
    display = display.mask(
        counts.notna() & (counts >= minimum_players),
        display + "<br>n=" + counts.fillna(0).astype(int).astype(str),
    )
    if show_sparse:
        display = display.mask(
            counts.notna() & (counts < minimum_players),
            display + "<br>n=" + counts.fillna(0).astype(int).astype(str) + " ⚠",
        )
    data = values.to_numpy(dtype=float)
    if over_under or metric != "observed_win_rate":
        finite = np.abs(data[np.isfinite(data)])
        bound = max(float(np.nanmax(finite)) if finite.size else 1.0, 1.0 if over_under else 5.0)
        colorscale = [[0, "#C95364"], [0.5, PANEL], [1, "#2EC4B6"]]
        zmin, zmax = -bound, bound
        color_title = "Difference (pp)" if metric == "observed_win_rate" else "LP/game difference"
    else:
        colorscale = [[0, "#C95364"], [0.5, PANEL], [1, "#2EC4B6"]]
        zmin, zmax = 0.45, 0.55
        color_title = "Win rate"
    hover_value = "%{z:+.1f} pp" if over_under and metric == "observed_win_rate" else (
        "%{z:+.2f} LP/game" if over_under or metric != "observed_win_rate" else "%{z:.1%}"
    )
    raw_format = "%{customdata[1]:.1%}" if metric == "observed_win_rate" else "%{customdata[1]:+.2f}"
    baseline_format = "%{customdata[2]:.1%}" if metric == "observed_win_rate" else "%{customdata[2]:+.2f}"
    custom = np.stack(
        [counts.to_numpy(), raw_values.to_numpy(), baseline_values.to_numpy()], axis=-1
    )
    fig = go.Figure(
        go.Heatmap(
            z=data,
            x=tiers,
            y=[PLAYSTYLE_LABELS[style] for style in styles],
            customdata=custom,
            text=np.where(np.isfinite(data), display.to_numpy(), ""),
            texttemplate="%{text}",
            colorscale=colorscale,
            zmid=0 if over_under or metric != "observed_win_rate" else 0.5,
            zmin=zmin,
            zmax=zmax,
            colorbar={"title": color_title, "tickformat": ".0%" if metric == "observed_win_rate" and not over_under else None},
            hovertemplate=(
                f"Tier: %{{x}}<br>Playstyle: %{{y}}<br>Displayed: {hover_value}<br>"
                f"Playstyle value: {raw_format}<br>Champion tier average: {baseline_format}<br>"
                "Players: %{customdata[0]:,.0f}<extra></extra>"
            ),
        )
    )
    annotate_sparse_cells(
        fig, tiers, [PLAYSTYLE_LABELS[style] for style in styles], data, display.to_numpy()
    )
    fig.update_xaxes(title="Starting tier")
    fig.update_yaxes(title="Observed playstyle", autorange="reversed")
    return style_figure(fig, height=max(390, 65 * len(styles) + 130))


def champion_ranked_share_chart(frame: pd.DataFrame, over_under: bool) -> go.Figure:
    plot = frame.copy()
    value = "difference_pp" if over_under else "share"
    fig = px.bar(
        plot,
        x="starting_tier",
        y=value,
        category_orders={"starting_tier": TIER_ORDER},
        custom_data=["players", "share", "baseline_share"],
        color_discrete_sequence=[BLUE],
    )
    display_format = "%{y:+.1f} pp" if over_under else "%{y:.1%}"
    fig.update_traces(
        hovertemplate=(
            f"%{{x}}<br>Displayed: {display_format}<br>Champion players: %{{customdata[0]:,}}<br>"
            "Champion mean: %{customdata[1]:.1%}<br>All players in tier: %{customdata[2]:.1%}<extra></extra>"
        )
    )
    fig.update_traces(texttemplate="n=%{customdata[0]}", textposition="outside", selector={"type": "bar"})
    if over_under:
        fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
        fig.update_yaxes(title="Difference from all players in tier (pp)")
    else:
        fig.update_yaxes(title="Mean estimated ranked-mastery share", tickformat=".0%", range=[0, 1])
    fig.update_xaxes(title="Most recent starting tier in window")
    return style_figure(fig, height=430)


def ranked_share_heatmap(
    summary: pd.DataFrame, x_dimension: str, y_dimension: str,
    minimum_players: int = MIN_SUPPORT_PLAYERS,
) -> go.Figure:
    """Show mean player median ranked-mastery share and player support."""
    minimum_players = summary.attrs.get("minimum_players", minimum_players)
    show_sparse = summary.attrs.get("show_sparse", False)
    x_values = (
        [value for value in (TIER_ORDER if x_dimension == "Tier" else ROLE_ORDER) if value in set(summary[x_dimension])]
        if x_dimension != "Champion"
        else summary.groupby("Champion")["player_count"].sum().sort_values(ascending=False).index.tolist()
    )
    y_values = (
        [value for value in (TIER_ORDER if y_dimension == "Tier" else ROLE_ORDER) if value in set(summary[y_dimension])]
        if y_dimension != "Champion"
        else summary.groupby("Champion")["player_count"].sum().sort_values(ascending=False).index.tolist()
    )
    values = summary.pivot(index=y_dimension, columns=x_dimension, values="mean_share").reindex(
        index=y_values, columns=x_values
    )
    counts = summary.pivot(index=y_dimension, columns=x_dimension, values="player_count").reindex(
        index=y_values, columns=x_values
    )
    if not show_sparse:
        values = values.where(counts >= minimum_players)
    text_values = values.map(lambda value: "" if pd.isna(value) else f"{value:.0%}")
    if not show_sparse:
        text_values = text_values.mask((counts > 0) & (counts < minimum_players), f"n<{minimum_players}")
    text_values = text_values.mask(
        counts.notna() & (counts >= minimum_players),
        text_values + "<br>n=" + counts.fillna(0).astype(int).astype(str),
    )
    if show_sparse:
        text_values = text_values.mask(
            counts.notna() & (counts < minimum_players),
            text_values + "<br>n=" + counts.fillna(0).astype(int).astype(str) + " ⚠",
        )
    data = values.to_numpy(dtype=float)
    labels_array = text_values.to_numpy()
    fig = go.Figure(
        go.Heatmap(
            z=data,
            x=x_values,
            y=y_values,
            customdata=counts.to_numpy(),
            text=np.where(np.isfinite(data), labels_array, ""),
            texttemplate="%{text}",
            zmin=0,
            zmax=1,
            colorscale=[[0, PANEL], [0.5, BLUE], [1, GOLD]],
            colorbar={"title": "Mean share", "tickformat": ".0%"},
            hovertemplate=(
                f"{x_dimension}: %{{x}}<br>{y_dimension}: %{{y}}<br>"
                "Mean player median: %{z:.1%}<br>Players: %{customdata:,.0f}<extra></extra>"
            ),
        )
    )
    annotate_sparse_cells(fig, x_values, y_values, data, labels_array)
    fig.update_xaxes(title=x_dimension, tickangle=-35 if x_dimension == "Champion" else 0)
    fig.update_yaxes(title=y_dimension, autorange="reversed")
    return style_figure(fig, height=max(440, 36 * len(y_values) + 135))
