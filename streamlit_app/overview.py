from __future__ import annotations

import streamlit as st
from app_core import config as dashboard_config
from app_core.analysis import AXIS_LABELS, binned_relationship, growth_scatter_data
from app_core.charts import playstyle_outcome_chart, specialization_relationship_chart
from app_core.config import PLAYSTYLE_ORDER, ROLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.ui import (
    data_source_caption,
    format_compact,
    hero,
    render_load_error,
    section,
    setup_page,
    support_warning,
)

setup_page("Overview")
minimum_support = getattr(dashboard_config, "MIN_SUPPORT_PLAYERS", 3)

try:
    players = load_dataset("players")
    growth_players = load_optional_dataset("growth_players")
    growth_styles = load_optional_dataset("growth_player_styles")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players]))
hero(
    "Specialization and rank",
    "How does champion-pool concentration relate to rank growth?",
    "Compare mastery concentration with ranked progression in the tracked sample. "
    "These observational comparisons describe associations; they do not establish that specialization improves rank.",
)

section("Player comparison", "Pool concentration and rank growth")
available_bases = ["Observed rank periods", "Active (60 days)", "All-time"] if growth_players is not None else [
    "Active (60 days)", "All-time"
]
controls = st.columns([1.4, 1.2, 1], gap="small")
basis = controls[0].selectbox("Specialization window", available_bases, index=available_bases.index("Active (60 days)"))
x_axis = controls[1].selectbox(
    "Specialization axis",
    ["specialization_hhi", "top_champion_share", "inverse_entropy"],
    format_func=lambda value: AXIS_LABELS[value],
)
historical = basis == "Observed rank periods"
role = controls[2].selectbox("Current inferred role", ["All roles", *ROLE_ORDER])

scatter, outcome_label, window_label = growth_scatter_data(players, growth_players, basis)
if basis == "Observed rank periods":
    sliders = st.columns(3, gap="small")
    minimum_games = sliders[0].slider("Minimum ranked games in outcome window", 1, 10, 2)
    minimum_periods = sliders[1].slider("Minimum observed periods per player and tier", 1, 6, 1)
    minimum_ranked_share = sliders[2].slider(
        "Minimum estimated ranked share", 0.0, 1.0, 0.35, 0.05,
        help="Filters the player's median period estimate within a starting tier. Each period uses expected mastery from ranked wins and losses divided by total mastery gained, capped at 100%.",
    )
    scatter = scatter.loc[scatter["estimated_ranked_mastery_share"].fillna(0) >= minimum_ranked_share]
else:
    minimum_games = 2
    scatter = scatter.loc[scatter["outcome"].abs() <= 50]
scatter = scatter.loc[scatter["support_games"].fillna(0) >= minimum_games]
if historical and "period_count" in scatter:
    scatter = scatter.loc[scatter["period_count"] >= minimum_periods]
if role != "All roles":
    scatter = scatter.loc[scatter["main_role"] == role]

scatter = scatter.dropna(subset=[x_axis, "outcome"])
if not historical:
    st.info(
        "This comparison pairs the selected current mastery profile with the latest rank week. "
        "LP/game is not adjusted for tier. Values outside ±50 LP/game are excluded."
    )
observation_label = "Player–tier observations" if historical else "Players"
st.caption(f"Window: {window_label} · Outcome: {outcome_label} · {observation_label}: {len(scatter):,}")
if historical:
    st.caption("One point per player and starting tier. A player can appear in more than one tier. Zero means the starting-tier baseline.")
if scatter.empty:
    st.warning("No players match these controls.")
else:
    trend = binned_relationship(scatter, x_axis)
    thin_bands = int((trend["players"] < minimum_support).sum())
    if thin_bands:
        show_thin_bands = support_warning(
            f"Insufficient data: {thin_bands} concentration band(s) have fewer than "
            f"{minimum_support} observations. The gold line hides them by default.",
            "overview_bands",
        )
        if not show_thin_bands:
            trend.loc[trend["players"] < minimum_support, "outcome"] = float("nan")
    if len(scatter) < minimum_support:
        st.warning(f"Insufficient data: only {len(scatter)} player observations match these controls.")
    relationship_chart = specialization_relationship_chart(
        scatter, x_axis, AXIS_LABELS[x_axis], outcome_label, trend
    )
    relationship_chart.update_layout(legend_title_text="Starting tier" if historical else "Current tier")
    st.plotly_chart(
        relationship_chart,
        use_container_width=True,
    )
    st.caption(
        "Gold line: mean outcome in quantile bands with at least three observations. "
        "The optional local-median line is hidden in the legend by default and uses overlapping neighborhoods. "
        "Both are descriptive; tier, role, activity, and experience can affect the relationship."
    )

section("Rank growth", "Rank outcomes by observed playstyle")
if growth_styles is None:
    st.info("Historical playstyle outcomes are unavailable in this dataset.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    outcome_tier = controls[0].selectbox("Starting tier", ["All tiers", *TIER_ORDER], index=0)
    outcome_role = controls[1].selectbox("Current inferred role", ["All roles", *ROLE_ORDER], key="outcome_role")
    outcome = controls[2].selectbox("Outcome", ["LP/game above tier baseline", "Win rate"])
    minimum_players = st.slider("Minimum player–tier observations per playstyle", 1, 100, minimum_support, 1)
    growth = growth_styles.copy()
    if outcome_tier != "All tiers":
        growth = growth.loc[growth["starting_tier"] == outcome_tier]
    if outcome_role != "All roles":
        growth = growth.loc[growth["current_main_role"] == outcome_role]
    growth = growth.loc[growth["playstyle"].isin(PLAYSTYLE_ORDER)]
    if growth.empty:
        st.info("No player groups match the selected tier and role.")
    else:
        st.caption("The chart compares observed playstyles by starting tier; the tier selector narrows the observations.")
        summary = growth.groupby("playstyle", observed=True).agg(
            observed_player_count=("climbing_efficiency", "count"),
            observed_period_count=("period_count", "sum"),
            climbing_efficiency=("climbing_efficiency", "mean"),
            observed_win_rate=("win_rate", "mean"),
        ).reset_index()
        hidden_styles = int(summary["observed_player_count"].lt(minimum_players).sum())
        if hidden_styles:
            show_thin_outcomes = support_warning(
                f"Insufficient data: {hidden_styles} playstyle group(s) have fewer than "
                f"{minimum_players} player–tier observations and are hidden by default.",
                "overview_outcomes",
            )
            if not show_thin_outcomes:
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

columns = st.columns(3)
columns[0].metric("Tracked players", format_compact(len(players)))
columns[1].metric("Observed playstyles", format_compact(growth_styles["playstyle"].nunique()) if growth_styles is not None else "?")
columns[2].metric(observation_label, format_compact(len(scatter)))

with st.expander("What the three time windows mean"):
    st.markdown(
        """
        - **Observed rank periods:** mastery distribution and rank movement measured within completed weekly periods.
        - **Active (60 days):** the current pool inferred using up to 60 days of activity; shorter tracking histories may use recent-play fallback rules.
        - **All-time:** the player's cumulative mastery distribution.

        Historical growth comparisons use starting-tier baselines from this dataset. Mastery is an activity proxy; it does not identify the champion used in an individual ranked match.

        **Reading concentration:** HHI sums squared mastery shares; higher values indicate a narrower pool.
        Top champion share is the fraction assigned to the leading champion. Inverse normalized entropy
        measures how unevenly mastery is distributed. Higher values on all three axes mean greater concentration.
        """
    )
