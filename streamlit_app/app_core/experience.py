"""Raw lifetime specialization comparisons within pooled mastery quintiles."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app_core.charts import style_figure
from app_core.config import PLAYSTYLE_COLORS, PLAYSTYLE_ORDER, ROLE_ORDER

TIER_GROUPS = ["Iron-Silver", "Gold-Platinum", "Emerald", "Diamond+"]
TIER_GROUP_MAP = dict(zip(
    ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND", "MASTER"],
    [TIER_GROUPS[0]] * 3 + [TIER_GROUPS[1]] * 2 + [TIER_GROUPS[2]] + [TIER_GROUPS[3]] * 2,
    strict=True,
))
ASSUMED_POINTS_PER_MATCH = 600
ASSUMED_MATCH_MINUTES = 30


def experience_bands(players: pd.DataFrame) -> pd.DataFrame:
    """Assign five pooled count bands before tier exclusions or profile filters.

    Stable source order breaks mastery ties, keeping counts within one player.
    Missing, infinite and negative mastery cannot define an experience band.
    """
    frame = players.loc[players["lifetime_playstyle"].isin(PLAYSTYLE_ORDER)].copy()
    mastery = pd.to_numeric(frame["lifetime_mastery_points"], errors="coerce")
    frame = frame.loc[np.isfinite(mastery) & mastery.ge(0)].copy()
    frame["lifetime_mastery_points"] = mastery.loc[frame.index]
    frame = frame.sort_values("lifetime_mastery_points", kind="stable")
    # array_split yields exactly five bands, including empty bands in tiny samples.
    frame["mastery_band"] = np.repeat(np.arange(1, 6), [len(part) for part in np.array_split(np.arange(len(frame)), 5)])
    return frame


def experience_cells(banded: pd.DataFrame, include_master: bool = True) -> pd.DataFrame:
    """Keep the explorer's specialist view of the shared focus counts."""
    cells = experience_focus_cells(banded, include_master)
    return cells.loc[cells["playstyle"].eq("specialist")].drop(columns="playstyle").rename(
        columns={"members": "specialists"},
    ).reset_index(drop=True)


def experience_focus_cells(banded: pd.DataFrame, include_master: bool = True) -> pd.DataFrame:
    """All four Lifetime classifications, with the same band/rank denominators."""
    frame = banded.copy()
    if not include_master:
        frame = frame.loc[frame["tier"].ne("MASTER")]
    frame["tier_group"] = frame["tier"].map(TIER_GROUP_MAP)
    index = pd.MultiIndex.from_product(
        [range(1, 6), TIER_GROUPS, PLAYSTYLE_ORDER], names=["mastery_band", "tier_group", "playstyle"],
    )
    return _focus_counts(frame, ["mastery_band", "tier_group"], index)


def role_focus_cells(banded: pd.DataFrame) -> pd.DataFrame:
    """Marginal role composition of the same eligible cohort, including unknown roles."""
    frame = banded.loc[banded["tier"].isin(TIER_GROUP_MAP)].copy()
    frame["main_role"] = frame["main_role"].where(frame["main_role"].isin(ROLE_ORDER), "Unknown role")
    index = pd.MultiIndex.from_product([[*ROLE_ORDER, "Unknown role"], PLAYSTYLE_ORDER],
                                       names=["main_role", "playstyle"])
    return _focus_counts(frame, ["main_role"], index)


def _focus_counts(frame: pd.DataFrame, groups: list[str], index: pd.MultiIndex) -> pd.DataFrame:
    frame = frame.loc[frame["lifetime_playstyle"].isin(PLAYSTYLE_ORDER)].rename(columns={"lifetime_playstyle": "playstyle"})
    counts = frame.groupby([*groups, "playstyle"], observed=True).size().reindex(index, fill_value=0)
    cells = counts.rename("members").reset_index()
    cells.insert(len(groups) + 1, "n", cells.groupby(groups, observed=True)["members"].transform("sum"))
    return _focus_proportions(cells)


def _focus_proportions(cells: pd.DataFrame) -> pd.DataFrame:
    n = cells["n"].replace(0, np.nan)
    share = cells["members"] / n
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


def experience_overall(cells: pd.DataFrame) -> pd.DataFrame:
    """Pool counts across bands, preserving each classification's full denominator."""
    index = pd.MultiIndex.from_product([TIER_GROUPS, PLAYSTYLE_ORDER], names=["tier_group", "playstyle"])
    overall = cells.groupby(["tier_group", "playstyle"], observed=True)[["n", "members"]].sum().reindex(index, fill_value=0)
    return _focus_proportions(overall.reset_index())


def experience_ranges(banded: pd.DataFrame) -> pd.DataFrame:
    """Score boundaries and assumption-based hour equivalents; band membership is untouched."""
    ranges = banded.groupby("mastery_band")["lifetime_mastery_points"].agg(low="min", high="max", n="size")
    ranges = ranges.reindex(range(1, 6))
    hours_per_point = ASSUMED_MATCH_MINUTES / 60 / ASSUMED_POINTS_PER_MATCH
    ranges["hours_low"] = ranges["low"] * hours_per_point
    ranges["hours_high"] = ranges["high"] * hours_per_point
    return ranges


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
