"""Four descriptive views of synthetic spending joined to real player context."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app_core.business import EXPERIENCE_METRICS, PLAYTIME_ORDER, TENURE_ORDER
from app_core.charts import style_figure
from app_core.config import (
    BLUE,
    GOLD,
    PLAYSTYLE_COLORS,
    PLAYSTYLE_LABELS,
    PLAYSTYLE_ORDER,
    ROLE_COLORS,
    ROLE_ORDER,
    TIER_ORDER,
)

DIMENSION_LABELS = {
    "main_role": "Inferred role", "recent_playstyle": "Real recent playstyle",
    "tier": "Current real tier", "tenure_band": "Account age (simulated)",
    "playtime_band": "Total playtime (estimated)",
}


def audience_chart(frame: pd.DataFrame, dimension: str) -> go.Figure:
    colors = ROLE_COLORS if dimension == "main_role" else PLAYSTYLE_COLORS if dimension == "recent_playstyle" else None
    fig = px.scatter(
        frame, x="cash_purchaser_share", y="usd_per_purchaser", size="players", size_max=48,
        color=dimension, color_discrete_map=colors, custom_data=["audience", "players", "cash_purchasers", "usd_per_player"],
        category_orders={"tier": [*TIER_ORDER, "GRANDMASTER", "CHALLENGER"], "main_role": ROLE_ORDER,
                         "recent_playstyle": PLAYSTYLE_ORDER, "tenure_band": TENURE_ORDER,
                         "playtime_band": [*PLAYTIME_ORDER, "Similar playtime"]},
        labels={"cash_purchaser_share": "Synthetic cash purchaser share · 60 days",
                "usd_per_purchaser": "Synthetic mean USD per cash purchaser · 60 days", dimension: DIMENSION_LABELS[dimension]},
    )
    fig.update_traces(hovertemplate=(
        "%{customdata[0]}<br>Purchaser share: %{x:.1%}<br>USD / cash purchaser: $%{y:.2f}"
        "<br>Players: %{customdata[1]:,.0f}<br>Cash purchasers: %{customdata[2]:,.0f}"
        "<br>USD / player: $%{customdata[3]:.2f}<extra></extra>"
    ))
    fig.update_xaxes(tickformat=".0%", range=[0, 1])
    fig.update_yaxes(tickprefix="$", rangemode="tozero")
    return style_figure(fig, legend_title=DIMENSION_LABELS[dimension])


def experience_chart(frame: pd.DataFrame, metric: str) -> go.Figure:
    fig = px.line(
        frame, x="mastery_points", y=metric, color="tenure_band", markers=True, log_x=True,
        category_orders={"tenure_band": TENURE_ORDER},
        color_discrete_map=dict(zip(TENURE_ORDER, [GOLD, BLUE, "#2EC4B6"], strict=True)),
        custom_data=["players", "cash_purchasers", "min_mastery", "max_mastery"],
        labels={"mastery_points": "Real cumulative mastery · experience proxy (log scale)",
                metric: EXPERIENCE_METRICS[metric], "tenure_band": "Simulated tenure"},
    )
    value = "%{y:.1%}" if metric == "cash_purchaser_share" else "$%{y:.2f}"
    fig.update_traces(hovertemplate=(
        f"Displayed: {value}<br>Mastery: %{{x:,.0f}}<br>Players: %{{customdata[0]:,.0f}}"
        "<br>Cash purchasers: %{customdata[1]:,.0f}<br>Mastery band: %{customdata[2]:,.0f}–%{customdata[3]:,.0f}<extra>%{fullData.name}</extra>"
    ), connectgaps=False)
    fig.update_yaxes(rangemode="tozero", tickformat=".0%" if metric == "cash_purchaser_share" else None,
                     tickprefix="" if metric == "cash_purchaser_share" else "$")
    return style_figure(fig, legend_title="Simulated tenure since first purchase")


def cosmetic_chart(frame: pd.DataFrame, dimension: str, axis_label: str) -> go.Figure:
    fig = go.Figure()
    palette = [GOLD, BLUE, "#2EC4B6", "#9B7EDE", "#D98E32", "#D85F76", "#47B36B", "#65758B"]
    for index, (name, group) in enumerate(frame.groupby(dimension, observed=True)):
        color = PLAYSTYLE_COLORS.get(name, palette[index % len(palette)])
        shade = f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.10)"
        label = PLAYSTYLE_LABELS.get(name, name) if dimension == "recent_playstyle" else name
        fig.add_trace(go.Scatter(x=group["pool_value"], y=group["q1"], mode="lines", line={"width": 0},
                                showlegend=False, hoverinfo="skip", legendgroup=str(name), connectgaps=False))
        fig.add_trace(go.Scatter(x=group["pool_value"], y=group["q3"], mode="lines", line={"width": 0},
                                fill="tonexty", fillcolor=shade, showlegend=False, hoverinfo="skip",
                                legendgroup=str(name), connectgaps=False))
        fig.add_trace(go.Scatter(
            x=group["pool_value"], y=group["mean_cosmetic_share"], mode="lines+markers", name=label,
            line={"color": color}, legendgroup=str(name), connectgaps=False,
            customdata=group[["players", "q1", "q3", "content_events"]].to_numpy(),
            hovertemplate=(
                "Pool value: %{x:.1%}<br>Mean player cosmetic share: %{y:.1%}<br>Players: %{customdata[0]:,.0f}"
                "<br>Middle 50%: %{customdata[1]:.1%}–%{customdata[2]:.1%}<br>Content events: %{customdata[3]:,.0f}<extra>%{fullData.name}</extra>"
            ),
        ))
    fig.update_xaxes(title=axis_label, range=[0, 1], tickformat=".0%")
    fig.update_yaxes(title="Synthetic mean player cosmetic share · full generated history", range=[0, 1], tickformat=".0%")
    return style_figure(fig, legend_title=DIMENSION_LABELS[dimension])


def discount_chart(frame: pd.DataFrame, dimension: str) -> go.Figure:
    colors = ROLE_COLORS if dimension == "main_role" else PLAYSTYLE_COLORS if dimension == "recent_playstyle" else None
    fig = px.scatter(
        frame, x="cash_discount_share", y="cash_discount_mean", size="cash_purchasers", size_max=48,
        color=dimension, color_discrete_map=colors,
        custom_data=["cash_purchasers", "cash_events", "discounted_events", "discounted_cash_purchasers"],
        labels={"cash_discount_share": "Synthetic discounted fiat-event share · 60 days",
                "cash_discount_mean": "Synthetic mean discount among discounted fiat events", dimension: DIMENSION_LABELS[dimension]},
    )
    fig.update_traces(marker={"opacity": 0.8}, hovertemplate=(
        "Discounted share: %{x:.1%}<br>Conditional discount: %{y:.1%}<br>Cash purchasers: %{customdata[0]:,.0f}"
        "<br>Fiat events: %{customdata[1]:,.0f}<br>Discounted fiat events: %{customdata[2]:,.0f}"
        "<br>Discount purchasers: %{customdata[3]:,.0f}<extra>%{fullData.name}</extra>"
    ))
    for column, update in (("cash_discount_share", fig.update_xaxes), ("cash_discount_mean", fig.update_yaxes)):
        lower, upper = frame[column].min(), frame[column].max()
        padding = max(0.04, (upper - lower) * 0.2)
        update(tickformat=".0%", range=[max(0, lower - padding), min(1, upper + padding)])
    return style_figure(fig, legend_title=DIMENSION_LABELS[dimension])
