from __future__ import annotations

import streamlit as st
from app_core.analysis import playstyle_composition, profile_basis, ranked_share_by_dimensions, role_playstyle_skew
from app_core.charts import (
    composition_view_chart,
    playstyle_outcome_chart,
    ranked_share_heatmap,
    role_difference_heatmap,
    transition_heatmap,
)
from app_core.config import PLAYSTYLE_ORDER, ROLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.metrics import active_alltime_transition
from app_core.ui import data_source_caption, format_compact, hero, render_load_error, section, setup_page

setup_page("Overall Analysis")

try:
    players = load_dataset("players")
    growth_styles = load_optional_dataset("growth_player_styles")
    ranked_share_players = load_optional_dataset("ranked_mastery_cohorts")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players]))
hero(
    "Population analysis",
    "How do specialization, tier, and role move together?",
    "Compare the shape of champion pools across the ladder, then inspect player-equal rank outcomes "
    "for the playstyle observed during completed rank periods.",
)

st.sidebar.subheader("Shared player filters")
minimum_tracked = st.sidebar.slider("Minimum tracked days", 0, 60, 0, 5)
minimum_players = st.sidebar.slider("Minimum players per result", 1, 100, 10, 5)
cohort = players.loc[players["days_tracked"].fillna(0) >= minimum_tracked].copy()

section("Population structure", "How playstyles are distributed")
controls = st.columns([1.2, 1.1], gap="small")
basis = controls[0].segmented_control(
    "Mastery window", ["Active (60 days)", "All-time"], default="Active (60 days)"
)
group_view = controls[1].selectbox("Compare by", ["Tier", "Role"])
group = "main_role" if group_view == "Role" else "tier"
composition = playstyle_composition(cohort, basis, group)
st.caption(
    f"Window: {basis} · Denominator: classified players within each displayed "
    f"{'role' if group == 'main_role' else 'tier'} · Players: {format_compact(composition['players'].sum())}"
)
if composition.empty:
    st.info("No classified players match this selection.")
else:
    st.plotly_chart(composition_view_chart(composition, group), use_container_width=True)

left, right = st.columns(2, gap="large")
with left:
    section("Role association", "Playstyle skew by inferred role")
    st.caption(f"Window: {basis} · Percentage-point difference from all classified players with an inferred role")
    skew = role_playstyle_skew(cohort, basis)
    st.plotly_chart(role_difference_heatmap(skew), use_container_width=True)
with right:
    section("Time horizons", "Active pool versus lifetime mastery")
    st.caption("Rows sum to 100%. This compares two current player classifications, not historical rank periods.")
    st.plotly_chart(transition_heatmap(active_alltime_transition(cohort)), use_container_width=True)

section("Climbing outcomes", "Do observed playstyles differ within a starting tier?")
if growth_styles is None:
    st.info("Player-equal historical outcomes will appear after the new growth marts and snapshot are refreshed.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    outcome_tier = controls[0].selectbox("Starting tier", ["All tiers", *TIER_ORDER], index=0)
    outcome_role = controls[1].selectbox("Current inferred role", ["All roles", *ROLE_ORDER])
    outcome = controls[2].selectbox("Outcome", ["Climbing efficiency", "Win rate"])
    growth = growth_styles.copy()
    if outcome_tier != "All tiers":
        growth = growth.loc[growth["starting_tier"] == outcome_tier]
    if outcome_role != "All roles":
        growth = growth.loc[growth["current_main_role"] == outcome_role]
    growth = growth.loc[growth["playstyle"].isin(PLAYSTYLE_ORDER)]
    if growth.empty:
        st.info("No player groups match the selected tier and role.")
    else:
        summary = growth.groupby("playstyle", observed=True).agg(
            observed_player_count=("climbing_efficiency", "count"),
            observed_period_count=("period_count", "sum"),
            climbing_efficiency=("climbing_efficiency", "mean"),
            observed_win_rate=("win_rate", "mean"),
        ).reset_index()
        summary = summary.loc[summary["observed_player_count"] >= minimum_players]
        if summary.empty:
            st.info("No playstyle reaches the selected player threshold.")
        else:
            value = "climbing_efficiency" if outcome == "Climbing efficiency" else "observed_win_rate"
            title = "Climbing efficiency (LP/game vs tier)" if outcome == "Climbing efficiency" else "Mean player win rate"
            st.caption("Window: observed rank periods · One vote per player within each tier and playstyle group")
            st.plotly_chart(playstyle_outcome_chart(summary, value, title), use_container_width=True)

section("Queue mix", "Where is ranked play a larger share of mastery?")
if ranked_share_players is None:
    st.info("This view will appear after the ranked-mastery player summary is exported.")
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
    minimum_cell_players = st.slider("Minimum players per cell", 1, 50, 5, key="ranked_share_support")
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
        ranked_cohort, x_dimension, y_dimension, minimum_cell_players, champion_selection
    )
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
            st.info("No cells meet the selected champion and player-count settings.")
        else:
            st.plotly_chart(ranked_share_heatmap(summary, x_dimension, y_dimension), use_container_width=True)
        all_periods = ranked_share_players.loc[
            ranked_share_players["window_name"] == "All observed periods"
        ]
        if all_periods["first_period_end"].min() == all_periods["last_period_end"].max():
            st.caption(
                "Only one completed rank period is available so far. All time-window choices currently show the same observations."
            )
    st.caption(
        "Tier is the player's most recent starting tier in this window. Role is inferred from the current active pool. "
        "Champion means favoured in at least one period in the window; a player can belong to several champion cells. "
        "The share is estimated from ranked wins and losses versus all mastery gained, so it is not an observed game-mode rate."
    )

with st.expander("Reading the classifications"):
    profile = profile_basis(cohort, basis)
    st.markdown(
        f"""
        **{basis}** is a current mastery profile. Specialist, multi-specialist, versatile, and generalist
        are deterministic labels based on concentration and favoured-pool features. There are
        **{profile['playstyle'].isin(PLAYSTYLE_ORDER).sum():,} classified players** in this selection.

        The outcome chart uses the pool observed within each rank period. Its role selector uses the
        player's **current inferred role**, because a historical match role is unavailable.
        """
    )
