from __future__ import annotations

import streamlit as st
from app_core.analysis import AXIS_LABELS, binned_relationship, champion_landscape_data, growth_scatter_data
from app_core.charts import champion_efficiency_landscape, specialization_relationship_chart
from app_core.config import ROLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.ui import data_source_caption, format_compact, hero, render_load_error, section, setup_page

setup_page("Overview")

try:
    players = load_dataset("players")
    champions = load_dataset("champions")
    growth_players = load_optional_dataset("growth_players")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players, champions]))
hero(
    "The central question",
    "Does a narrower champion pool help players climb?",
    "Explore the association between champion-pool concentration and rank growth. Each point below "
    "represents a player within a starting tier when historical player summaries are available.",
)

st.sidebar.subheader("Shared support settings")
minimum_periods = st.sidebar.slider("Minimum observed periods per player", 1, 6, 1)
minimum_champion_players = st.sidebar.slider("Minimum players per champion", 1, 100, 10, 5)

section("Primary relationship", "Specialization versus climbing efficiency")
available_bases = ["Observed rank periods", "Active (60 days)", "All-time"] if growth_players is not None else [
    "Active (60 days)", "All-time"
]
controls = st.columns([1.4, 1.2, 1, 1], gap="small")
basis = controls[0].selectbox("Specialization window", available_bases)
x_axis = controls[1].selectbox(
    "Specialization axis",
    ["specialization_hhi", "top_champion_share", "inverse_entropy"],
    format_func=lambda value: AXIS_LABELS[value],
)
tier = controls[2].selectbox("Starting/current tier", ["All tiers", *TIER_ORDER])
role = controls[3].selectbox("Current inferred role", ["All roles", *ROLE_ORDER])

scatter, outcome_label, window_label = growth_scatter_data(players, growth_players, basis)
minimum_games = st.slider("Minimum ranked games in outcome window", 1, 10, 2)
if basis == "Observed rank periods":
    minimum_ranked_share = st.slider(
        "Minimum estimated ranked mastery share", 0.0, 1.0, 0.0, 0.05,
        help="Expected mastery from ranked wins and losses divided by total mastery gained in each period, capped at 100%. This is an activity proxy.",
    )
    scatter = scatter.loc[scatter["estimated_ranked_mastery_share"].fillna(0) >= minimum_ranked_share]
else:
    scatter = scatter.loc[scatter["outcome"].abs() <= 50]
scatter = scatter.loc[scatter["support_games"].fillna(0) >= minimum_games]
if "period_count" in scatter:
    scatter = scatter.loc[scatter["period_count"] >= minimum_periods]
if tier != "All tiers":
    scatter = scatter.loc[scatter["tier"] == tier]
if role != "All roles":
    scatter = scatter.loc[scatter["main_role"] == role]

if growth_players is None:
    st.info(
        "Historical player summaries are awaiting the refreshed dbt build and snapshot. "
        "This view uses the current mastery profile and the latest rank week; its LP/game outcome is not tier adjusted. "
        "The preview excludes values beyond ±50 LP/game and requires at least two ranked games by default."
    )
st.caption(f"Window: {window_label} · Outcome: {outcome_label} · Players: {len(scatter):,}")
if scatter.empty:
    st.warning("No players match these controls.")
else:
    trend = binned_relationship(scatter, x_axis)
    st.plotly_chart(
        specialization_relationship_chart(scatter, x_axis, AXIS_LABELS[x_axis], outcome_label, trend),
        use_container_width=True,
    )
    st.caption(
        "Gold line: mean outcome within concentration bands. The relationship is descriptive; "
        "tier, role, activity, and player experience can affect both axes."
    )

section("Champion view", "Which champions sit where in the landscape?")
landscape, x_label = champion_landscape_data(champions, players)
landscape = landscape.loc[landscape["observed_player_count"].fillna(0) >= minimum_champion_players]
if "mean_commitment" not in champions:
    st.caption(
        "Preview from the included snapshot: x uses current primary players' active HHI; "
        "y uses the older champion growth estimate. A refreshed snapshot will align both axes to historical favoured pools."
    )
if landscape.empty:
    st.info("No champions meet the selected player threshold.")
else:
    y_label = (
        "Climbing efficiency (LP/game vs tier)"
        if "climbing_efficiency" in champions
        else "Legacy champion LP/game lift vs tier (preview)"
    )
    st.plotly_chart(champion_efficiency_landscape(landscape, x_label, y_label), use_container_width=True)

columns = st.columns(3)
columns[0].metric("Tracked players", format_compact(len(players)))
columns[1].metric("Champions", format_compact(len(champions)))
columns[2].metric("Players in relationship", format_compact(len(scatter)))

with st.expander("What the three time windows mean"):
    st.markdown(
        """
        - **Observed rank periods:** mastery distribution and rank movement measured within completed weekly periods.
        - **Active (60 days):** the current active champion pool inferred from recent mastery movement.
        - **All-time:** the player's cumulative mastery distribution.

        Historical growth comparisons use starting-tier baselines from this dataset. Mastery is an activity proxy; it does not identify the champion used in an individual ranked match.
        """
    )
