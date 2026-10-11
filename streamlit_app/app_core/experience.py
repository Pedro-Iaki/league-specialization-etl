"""Raw all-time specialization comparisons within pooled mastery quintiles."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app_core.charts import style_figure
from app_core.config import PLAYSTYLE_COLORS, PLAYSTYLE_ORDER

TIER_GROUPS = ["Iron-Silver", "Gold-Platinum", "Emerald", "Diamond+"]
TIER_GROUP_MAP = dict(zip(
    ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER"],
    [TIER_GROUPS[0]] * 3 + [TIER_GROUPS[1]] * 2 + [TIER_GROUPS[2]] + [TIER_GROUPS[3]] * 2,
    strict=True,
))


def experience_bands(players: pd.DataFrame) -> pd.DataFrame:
    """Assign five pooled count bands before tier exclusions or profile filters.

    Stable source order breaks mastery ties, keeping counts within one player.
    Missing, infinite and negative mastery cannot define an experience band.
    """
    frame = players.loc[players["alltime_playstyle"].isin(PLAYSTYLE_ORDER)].copy()
    mastery = pd.to_numeric(frame["total_mastery_points"], errors="coerce")
    frame = frame.loc[np.isfinite(mastery) & mastery.ge(0)].copy()
    frame["total_mastery_points"] = mastery.loc[frame.index]
    frame = frame.sort_values("total_mastery_points", kind="stable")
    # array_split yields exactly five bands, including empty bands in tiny samples.
    frame["mastery_band"] = np.repeat(np.arange(1, 6), [len(part) for part in np.array_split(np.arange(len(frame)), 5)])
    return frame


def experience_cells(banded: pd.DataFrame, include_master: bool = True) -> pd.DataFrame:
    frame = banded.copy()
    if not include_master:
        frame = frame.loc[frame["tier"].ne("MASTER")]
    frame["tier_group"] = frame["tier"].map(TIER_GROUP_MAP)
    frame["is_specialist"] = frame["alltime_playstyle"].eq("specialist")
    counts = frame.groupby(["mastery_band", "tier_group"], observed=True).agg(
        n=("is_specialist", "size"), specialists=("is_specialist", "sum"),
    )
    index = pd.MultiIndex.from_product([range(1, 6), TIER_GROUPS], names=["mastery_band", "tier_group"])
    cells = counts.reindex(index, fill_value=0).reset_index()
    n = cells["n"].replace(0, np.nan)
    share = cells["specialists"] / n
    z = 1.959963984540054
    center = (share + z**2 / (2 * n)) / (1 + z**2 / n)
    half = z * np.sqrt(share * (1 - share) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
    cells["share"] = share
    cells["lower"] = (center - half).clip(0, 1)
    cells["upper"] = (center + half).clip(0, 1)
    return cells


def experience_display(cells: pd.DataFrame, minimum: int, show_omitted: bool = False) -> pd.DataFrame:
    """Retain empty positions to break lines; support uses the cell denominator."""
    result = cells.copy()
    result["omitted"] = result["n"].lt(minimum)
    hidden = result["n"].eq(0) | (result["omitted"] & (not show_omitted))
    result.loc[hidden, ["share", "lower", "upper"]] = np.nan
    result["count_label"] = [
        "" if hide else f"n={int(n):,}" + (" ⚠" if thin else "")
        for n, thin, hide in zip(result["n"], result["omitted"], hidden, strict=True)
    ]
    return result


def experience_chart(display: pd.DataFrame, lines: bool = False) -> go.Figure:
    fig = go.Figure() if lines else make_subplots(
        rows=2, cols=3, shared_yaxes=True,
        subplot_titles=[f"Mastery band {band}" for band in range(1, 6)],
        vertical_spacing=0.22,
    )
    colors = [PLAYSTYLE_COLORS[style] for style in PLAYSTYLE_ORDER]
    for group, color, position in zip(
        TIER_GROUPS, colors, ["top left", "bottom left", "top right", "bottom right"], strict=True,
    ):
        for band in ([None] if lines else range(1, 6)):
            data = display.loc[display["tier_group"].eq(group)]
            if band is not None:
                data = data.loc[data["mastery_band"].eq(band)]
            common = {
                "x": data["mastery_band"] if lines else data["tier_group"], "y": data["share"],
                "name": group, "marker_color": color, "text": data["count_label"],
                "customdata": data[["n", "specialists", "lower", "upper"]].to_numpy(),
                "error_y": {"type": "data", "symmetric": False, "array": data["upper"] - data["share"],
                            "arrayminus": data["share"] - data["lower"]},
                "hovertemplate": "%{x}<br>%{fullData.name}: %{y:.1%}<br>n=%{customdata[0]:,}"
                                 "<br>Specialists: %{customdata[1]:,}<br>95% Wilson: %{customdata[2]:.1%}–%{customdata[3]:.1%}<extra></extra>",
                "showlegend": lines,
            }
            if lines:
                fig.add_trace(go.Scatter(**common, mode="lines+markers+text", textposition=position, connectgaps=False))
            else:
                fig.add_trace(go.Bar(**common, textposition="outside", cliponaxis=False),
                              row=(band - 1) // 3 + 1, col=(band - 1) % 3 + 1)
    style_figure(fig, height=460 if lines else 720)
    upper = display["upper"].max()
    ymax = min(1.15, max(0.1, upper * 1.3)) if pd.notna(upper) else 0.1
    fig.update_yaxes(range=[0, ymax], tickformat=".0%", title="Raw specialist share")
    if lines:
        fig.update_xaxes(title="Mastery band (low to high)", tickmode="linear", dtick=1)
    else:
        fig.update_layout(barmode="overlay")
        fig.update_xaxes(categoryorder="array", categoryarray=TIER_GROUPS, tickangle=-25)
    return fig
