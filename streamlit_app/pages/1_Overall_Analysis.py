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
    "How does champion-pool composition vary by tier and role?",
    "Compare mastery-based playstyles across the tracked sample, then examine rank growth "
    "and estimated ranked activity during completed observation periods.",
)

st.sidebar.subheader("Current player profiles")
minimum_tracked = st.sidebar.slider("Minimum tracked days", 0, 60, 0, 5)
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
    section("Role association", "Playstyle share relative to the sample")
    st.caption(f"Window: {basis} · Percentage-point difference from all classified players with an inferred role")
    skew = role_playstyle_skew(cohort, basis)
    st.plotly_chart(role_difference_heatmap(skew), use_container_width=True)
with right:
    section("Time horizons", "Active pool versus lifetime mastery")
    st.caption("Each populated row sums to 100%: among players with this active playstyle, how is lifetime playstyle distributed? This is not a transition over time.")
    st.plotly_chart(transition_heatmap(active_alltime_transition(cohort)), use_container_width=True)

section("Rank growth", "Rank outcomes by observed playstyle")
if growth_styles is None:
    st.info("Historical playstyle outcomes are unavailable in this dataset.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    outcome_tier = controls[0].selectbox("Starting tier", ["All tiers", *TIER_ORDER], index=0)
    outcome_role = controls[1].selectbox("Current inferred role", ["All roles", *ROLE_ORDER])
    outcome = controls[2].selectbox("Outcome", ["LP/game above tier baseline", "Win rate"])
    minimum_players = st.slider("Minimum player–tier observations per playstyle", 1, 100, 10, 5)
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
            value = "climbing_efficiency" if outcome == "LP/game above tier baseline" else "observed_win_rate"
            title = "LP/game above starting-tier baseline" if value == "climbing_efficiency" else "Mean player win rate"
            st.caption(
                "Each player contributes once per starting-tier and playstyle group. With all tiers selected, "
                "players observed in multiple tiers contribute multiple times. Players can also appear in multiple playstyles."
            )
            st.plotly_chart(playstyle_outcome_chart(summary, value, title), use_container_width=True)

section("Estimated ranked activity", "How much mastery gain is attributed to ranked play?")
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

        The outcome chart uses the pool observed within each rank period. Its role selector uses the
        player's **current inferred role**, because a historical match role is unavailable.
        """
    )
