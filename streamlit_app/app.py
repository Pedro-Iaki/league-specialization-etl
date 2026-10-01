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
    "Specialization and rank",
    "How does champion-pool concentration relate to rank growth?",
    "Compare mastery concentration with ranked progression in the tracked sample. "
    "These observational comparisons describe associations; they do not establish that specialization improves rank.",
)

st.sidebar.subheader("Champion comparison")
minimum_champion_players = st.sidebar.slider("Minimum historical players per champion", 1, 100, 10, 5)
st.sidebar.caption("Applies only to the champion comparison below.")

section("Player comparison", "Pool concentration and rank growth")
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
historical = basis == "Observed rank periods"
tier = controls[2].selectbox("Starting tier" if historical else "Current tier", ["All tiers", *TIER_ORDER])
role = controls[3].selectbox("Current inferred role", ["All roles", *ROLE_ORDER])

scatter, outcome_label, window_label = growth_scatter_data(players, growth_players, basis)
minimum_games = st.slider("Minimum ranked games in outcome window", 1, 10, 2)
if basis == "Observed rank periods":
    minimum_periods = st.slider("Minimum observed periods per player and tier", 1, 6, 1)
    minimum_ranked_share = st.slider(
        "Minimum estimated ranked mastery share", 0.0, 1.0, 0.0, 0.05,
        help="Filters the player's median period estimate within a starting tier. Each period uses expected mastery from ranked wins and losses divided by total mastery gained, capped at 100%.",
    )
    scatter = scatter.loc[scatter["estimated_ranked_mastery_share"].fillna(0) >= minimum_ranked_share]
else:
    scatter = scatter.loc[scatter["outcome"].abs() <= 50]
scatter = scatter.loc[scatter["support_games"].fillna(0) >= minimum_games]
if historical and "period_count" in scatter:
    scatter = scatter.loc[scatter["period_count"] >= minimum_periods]
if tier != "All tiers":
    scatter = scatter.loc[scatter["tier"] == tier]
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
    relationship_chart = specialization_relationship_chart(
        scatter, x_axis, AXIS_LABELS[x_axis], outcome_label, trend
    )
    relationship_chart.update_layout(legend_title_text="Starting tier" if historical else "Current tier")
    st.plotly_chart(
        relationship_chart,
        use_container_width=True,
    )
    st.caption(
        "Gold line: mean outcome in quantile bands of concentration, not a fitted prediction. "
        "tier, role, activity, and player experience can affect both axes."
    )

section("Champion comparison", "Mastery preference and rank growth by champion")
landscape, x_label = champion_landscape_data(champions, players)
landscape = landscape.loc[landscape["observed_player_count"].fillna(0) >= minimum_champion_players]
if "mean_commitment" not in champions:
    st.caption(
        "This snapshot combines current primary players' active concentration with an older historical growth estimate. "
        "The two axes describe different cohorts and time windows."
    )
if landscape.empty:
    st.info("No champions meet the selected player threshold.")
else:
    y_label = (
        "LP/game above starting-tier baseline"
        if "climbing_efficiency" in champions
        else "LP/game above tier baseline (older estimate)"
    )
    st.plotly_chart(champion_efficiency_landscape(landscape, x_label, y_label), use_container_width=True)
    st.caption("Each bubble is a champion; size shows historical players and color shows mean player win rate. Player filters above do not apply here.")

columns = st.columns(3)
columns[0].metric("Tracked players", format_compact(len(players)))
columns[1].metric("Champions", format_compact(len(champions)))
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
