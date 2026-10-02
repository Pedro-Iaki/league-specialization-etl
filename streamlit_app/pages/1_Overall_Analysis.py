from __future__ import annotations

import math

import plotly.express as px
import streamlit as st
from app_core import config as dashboard_config
from app_core.analysis import (
    playstyle_composition,
    playstyle_mastery_bands,
    profile_basis,
    ranked_share_by_dimensions,
    role_playstyle_skew,
)
from app_core.charts import (
    composition_view_chart,
    ranked_share_heatmap,
    role_difference_heatmap,
    transition_heatmap,
)
from app_core.config import PLAYSTYLE_COLORS, PLAYSTYLE_LABELS, PLAYSTYLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.metrics import active_alltime_transition
from app_core.ui import (
    data_source_caption,
    format_compact,
    hero,
    render_load_error,
    section,
    setup_page,
    support_warning,
)

setup_page("Population Analysis")
minimum_support = getattr(dashboard_config, "MIN_SUPPORT_PLAYERS", 3)

try:
    players = load_dataset("players")
    ranked_share_players = load_optional_dataset("ranked_mastery_cohorts")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players]))
hero(
    "Population analysis",
    "How does champion-pool composition vary by tier and role?",
    "Compare mastery-based playstyles across the tracked sample, then examine rank growth "
    "and estimated ranked activity during completed observation periods.",
)

st.sidebar.subheader("Current player profiles")
minimum_tracked = st.sidebar.slider("Minimum tracked days", 0, 60, 0, 5)
minimum_mastery = st.sidebar.slider("Minimum total mastery points", 0, 1_000_000, 0, 10_000, help="Applies to charts based on cumulative mastery points.")
st.sidebar.caption("Applies to population composition, role differences, and active versus lifetime classifications only.")
cohort = players.loc[players["days_tracked"].fillna(0) >= minimum_tracked].copy()

section("Population structure", "How playstyles are distributed")
controls = st.columns([1.2, 1.1], gap="small")
basis = controls[0].segmented_control(
    "Mastery window", ["Active (60 days)", "All-time"], default="Active (60 days)"
)
group_view = controls[1].selectbox("Compare by", ["Tier", "Role"])
group = "main_role" if group_view == "Role" else "tier"
composition = playstyle_composition(cohort, basis, group)
composition_players = int(composition["players"].sum())
if composition_players:
    composition["group_players"] = composition.groupby(group, observed=True)["players"].transform("sum")
    composition["confidence_half_width"] = composition.apply(
        lambda row: 1.96 * math.sqrt(row["share"] * (1 - row["share"]) / row["group_players"] + 1.96**2 / (4 * row["group_players"]**2)) / (1 + 1.96**2 / row["group_players"]), axis=1
    )
if not composition.empty:
    group_support = composition.groupby(group, observed=True)["players"].transform("sum")
    thin_groups = composition.loc[group_support < minimum_support, group].nunique()
    thin_segments = int(composition["players"].lt(minimum_support).sum())
    if thin_groups or thin_segments:
        show_thin_composition = support_warning(
            f"Insufficient data: {thin_groups} {group_view.lower()} group(s) and {thin_segments} "
            f"playstyle segment(s) fall below {minimum_support} players. Hidden by default; "
            "visible share bars may total less than 100%.",
            "overall_composition",
        )
        if not show_thin_composition:
            composition = composition.loc[
                (group_support >= minimum_support) & (composition["players"] >= minimum_support)
            ]
st.caption(
    f"Window: {basis} · Denominator: classified players within each displayed "
    f"{'role' if group == 'main_role' else 'tier'} · Classified players: {format_compact(composition_players)}"
)
if composition.empty:
    if composition_players:
        st.warning(f"Insufficient data: no group has at least {minimum_support} players in a playstyle segment.")
    else:
        st.info("No classified players match this selection.")
else:
    st.plotly_chart(composition_view_chart(composition, group), use_container_width=True)
    with st.expander("Composition support and uncertainty"):
        st.caption("95% Wilson intervals describe sampling uncertainty within the tracked players only; they do not correct selection bias.")
        st.dataframe(composition[[group, "playstyle", "players", "group_players", "share", "confidence_half_width"]], hide_index=True, width="stretch")

section("Player universe", "Pool shape by rank")
universe_basis = st.segmented_control("Pool window", ["Active (60 days)", "All-time"], default="Active (60 days)", key="universe_basis")
universe_metric = st.selectbox("Pool measure", ["Main pick share", "Off picks share", "Favoured picks count", "All picks count", "HHI"], key="universe_metric")
prefix = "active" if universe_basis == "Active (60 days)" else "alltime"
columns = {"Main pick share": f"{prefix}_top1_share", "Off picks share": "off_picks_share", "Favoured picks count": f"{prefix}_favoured_champion_count", "All picks count": "active_champion_count" if prefix == "active" else "champions_with_mastery", "HHI": f"{prefix}_hhi"}
pool = cohort.loc[cohort["tier"].isin(TIER_ORDER) & cohort["total_mastery_points"].ge(minimum_mastery)].copy()
pool["off_picks_share"] = (pool[f"{prefix}_favoured_champions_share"] - pool[f"{prefix}_top1_share"]).clip(lower=0)
if pool.empty:
    st.info("No players have this pool measure at the selected mastery threshold.")
else:
    fig = px.box(pool.dropna(subset=[columns[universe_metric]]), x="tier", y=columns[universe_metric], category_orders={"tier": TIER_ORDER}, points=False)
    fig.update_yaxes(title=universe_metric)
    fig.update_xaxes(title="Current tier")
    st.plotly_chart(fig, width="stretch")
    st.caption(f"One box per tier shows the player distribution. Window: {universe_basis}. Off picks share excludes the main pick from favoured-pick share. Favoured picks count is the selected core pool; all picks count includes every observed champion.")

section("Cumulative mastery", "Total mastery by tier")
mastery = cohort.loc[cohort["tier"].isin(TIER_ORDER) & cohort["total_mastery_points"].ge(max(1, minimum_mastery)), ["tier", "total_mastery_points"]].dropna()
if not mastery.empty:
    fig = px.box(mastery, x="tier", y="total_mastery_points", category_orders={"tier": TIER_ORDER}, points=False)
    fig.update_xaxes(title="Current tier")
    fig.update_yaxes(title="All-time total mastery points (log scale)", type="log")
    st.plotly_chart(fig, width="stretch")
    st.caption("Log scaling keeps typical and very high mastery totals visible. Zero values cannot appear on a log axis.")

section("Mastery and playstyle", "How playstyle composition changes with cumulative mastery")
mastery_basis = st.segmented_control("Classification window", ["Active (60 days)", "All-time"], default="All-time", key="mastery_style_basis")
mastery_tier = st.selectbox("Mastery tier", ["All tiers", *TIER_ORDER])
mastery_axis = st.toggle("Log mean mastery on horizontal axis", value=False, help="Log10 of the mean mastery in each band, calculated after the minimum mastery filter.")
bands = playstyle_mastery_bands(cohort, mastery_basis, minimum_mastery, tier=None if mastery_tier == "All tiers" else mastery_tier)
if not bands.empty:
    bands["Playstyle"] = bands["playstyle"].map(PLAYSTYLE_LABELS)
    fig = px.line(bands, x="log_mean_mastery" if mastery_axis else "mastery", y="share", color="Playstyle", markers=True, color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()})
    fig.update_xaxes(title="Log10 mean total mastery points" if mastery_axis else "Median total mastery points in band", type="linear" if mastery_axis else "log")
    fig.update_yaxes(title="Share", tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
    st.caption("Players are split into equal-frequency mastery bands; shares sum to 100% within each band before low-support filtering.")

left, right = st.columns(2, gap="large")
with left:
    section("Role association", "Playstyle share relative to the sample")
    role_basis = st.segmented_control("Role association window", ["Active (60 days)", "All-time"], default="Active (60 days)")
    st.caption(f"Window: {role_basis} · Percentage-point difference from all classified players with an inferred role")
    skew = role_playstyle_skew(cohort, role_basis)
    role_counts = skew.attrs.get("support_counts")
    if role_counts is not None and skew.isna().any().any():
        skew.attrs["show_sparse"] = support_warning(
            f"Insufficient data: thin role–playstyle cells are marked n<{minimum_support} or —. "
            "A zero in a supported role remains a measured zero.",
            "overall_role",
        )
    st.plotly_chart(role_difference_heatmap(skew), use_container_width=True)
with right:
    section("Time horizons", "Active pool versus lifetime mastery")
    st.caption("Underlying populated rows sum to 100% before low-support cells are hidden. This compares current active and lifetime classifications, not a transition over time.")
    transition = active_alltime_transition(cohort)
    transition_support = active_alltime_transition(cohort, normalize=False)
    transition.attrs["support_counts"] = transition_support
    thin_transitions = (transition_support.gt(0) & transition_support.lt(minimum_support)).any().any()
    thin_rows = transition_support.sum(axis=1).lt(minimum_support).any()
    if thin_transitions or thin_rows:
        transition.attrs["show_sparse"] = support_warning(
            f"Insufficient data: cells with fewer than {minimum_support} players are marked "
            f"n<{minimum_support} or —.",
            "overall_transition",
        )
    st.plotly_chart(transition_heatmap(transition), use_container_width=True)

section("Estimated ranked activity", "How much mastery gain is attributed to ranked play?")
st.warning("Selection bias: this estimate includes players with completed ranked observation periods. Players who mainly use other modes are underrepresented. Ranked Flex is excluded from the recorded queue and cannot be inferred from these fields.")
if ranked_share_players is None:
    st.info("Estimated ranked-mastery shares are unavailable in this dataset.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    window = controls[0].selectbox(
        "Rank-period window",
        ["All observed periods", "Last 60 days", "Last 30 days", "Latest completed period"],
    )
    x_dimension = controls[1].selectbox("Horizontal dimension", ["Tier", "Role", "Champion"])
    y_options = [dimension for dimension in ("Role", "Tier", "Champion") if dimension != x_dimension]
    y_dimension = controls[2].selectbox("Vertical dimension", y_options)
    ranked_cohort = ranked_share_players.loc[ranked_share_players["window_name"] == window].copy()
    minimum_cell_players = st.slider("Minimum players per cell", 1, 50, minimum_support, key="ranked_share_support")
    champion_selection = None
    if "Champion" in (x_dimension, y_dimension):
        champion_counts = ranked_cohort["favoured_champions"].explode().value_counts()
        champion_options = sorted(champion_counts.index.dropna().tolist())
        champion_selection = st.multiselect(
            "Champions to display",
            champion_options,
            default=champion_counts.head(15).index.tolist(),
            help="Players count once for each champion favoured in the selected rank-period window.",
        )
    summary = ranked_share_by_dimensions(
        ranked_cohort, x_dimension, y_dimension, 1, champion_selection
    )
    summary.attrs["minimum_players"] = minimum_cell_players
    if ranked_cohort.empty:
        st.info("No player periods are available for this window.")
    else:
        first_period = ranked_cohort["first_period_end"].min()
        last_period = ranked_cohort["last_period_end"].max()
        st.caption(
            f"Observed period ends: {first_period:%Y-%m-%d} to {last_period:%Y-%m-%d} · "
            f"Players: {len(ranked_cohort):,} · Cell values: mean of each player's median estimated share"
        )
        if summary.empty:
            st.info("No cells match the selected dimensions and champions.")
        else:
            thin_cells = int(summary["player_count"].lt(minimum_cell_players).sum())
            if thin_cells:
                summary.attrs["show_sparse"] = support_warning(
                    f"Insufficient data: {thin_cells} cell(s) have fewer than "
                    f"{minimum_cell_players} players and are marked n<{minimum_cell_players}.",
                    "overall_ranked_share",
                )
            st.plotly_chart(ranked_share_heatmap(summary, x_dimension, y_dimension), use_container_width=True)
        all_periods = ranked_share_players.loc[
            ranked_share_players["window_name"] == "All observed periods"
        ]
        if all_periods["first_period_end"].min() == all_periods["last_period_end"].max():
            st.caption(
                "Only one completed rank period is available so far. All time-window choices currently show the same observations."
            )
    st.caption(
        "Tier is the player's most recent starting tier in this window. Role is inferred from the player's most recently played champions. "
        "Champion means favoured in at least one period in the window; a player can belong to several champion cells. "
        "The share is estimated from ranked wins and losses versus all mastery gained, so it is not an observed game-mode rate."
    )
    st.caption("Time windows end at the latest observed period in the dataset, not today's date.")

with st.expander("Reading the classifications"):
    profile = profile_basis(cohort, basis)
    st.markdown(
        f"""
        **{basis}** is a current mastery profile. Specialist, multi-specialist, versatile, and generalist
        describe mastery-pool shapes, not skill or match tactics. Each label is the closest configured
        profile based on mastery shares, concentration, entropy, and favoured-pool size. There are
        **{profile['playstyle'].isin(PLAYSTYLE_ORDER).sum():,} classified players** in this selection.

        """
    )
