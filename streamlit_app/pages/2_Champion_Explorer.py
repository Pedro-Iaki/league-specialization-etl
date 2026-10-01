from __future__ import annotations

import pandas as pd
import streamlit as st
from app_core.analysis import (
    AXIS_LABELS,
    binned_relationship,
    champion_ranked_share_by_tier,
    composition_vs_population,
    growth_column,
    playstyle_composition,
    specialization_trend,
)
from app_core.charts import (
    champion_ranked_share_chart,
    champion_role_chart,
    champion_tier_outcome_heatmap,
    composition_delta_chart,
    composition_view_chart,
    cooccurrence_chart,
    specialization_relationship_chart,
)
from app_core.config import PLAYSTYLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.metrics import champion_neighbors
from app_core.ui import (
    data_source_caption,
    format_compact,
    format_percent,
    format_signed,
    hero,
    render_load_error,
    section,
    setup_page,
)

setup_page("Champion Explorer")
try:
    players = load_dataset("players")
    champions = load_dataset("champions")
    styles = load_dataset("champion_playstyles")
    cooccurrence = load_dataset("cooccurrence")
    growth_players = load_optional_dataset("champion_growth_players")
    tier_growth = load_optional_dataset("champion_tier_growth")
    ranked_share_players = load_optional_dataset("ranked_mastery_cohorts")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players, champions]))
hero(
    "Champion explorer",
    "How does champion preference relate to climbing?",
    "Compare each champion's players with the wider population, inspect playstyle and role tendencies, "
    "and explore how mastery preference relates to climbing efficiency.",
)

names = sorted(champions["champion_name"].dropna().unique().tolist())
selected = st.selectbox("Champion", names, index=names.index("Ahri") if "Ahri" in names else 0)
champion = champions.loc[champions["champion_name"] == selected].iloc[0]
style_profile = styles.loc[styles["champion_name"] == selected].copy()
observations_all = (
    growth_players.loc[growth_players["champion_name"] == selected].copy()
    if growth_players is not None else None
)
new_growth = "climbing_efficiency" in champions

positions = champion.get("expected_positions")
if isinstance(positions, (list, tuple)):
    positions_label = ", ".join(map(str, positions))
elif hasattr(positions, "tolist"):
    positions_label = ", ".join(map(str, positions.tolist()))
else:
    positions_label = str(positions) if pd.notna(positions) else "Unavailable"
st.caption(f"Metadata positions: {positions_label} · Champion patch: {champion.get('champion_patch', '—')}")

trend = specialization_trend(observations_all) if observations_all is not None else None
cards = st.columns(6)
cards[0].metric(
    "Primary players",
    format_compact(champion.get("primary_player_count")),
    help="Players whose current active mastery pool is led by this champion.",
)
cards[1].metric(
    "Active players",
    format_compact(champion.get("active_player_count")),
    help="Players whose current active mastery pool contains this champion.",
)
cards[2].metric(
    "Observed players",
    format_compact(champion.get("observed_player_count")),
    help="Players who favoured this champion in at least one eligible completed rank period. Current primary or active status is not required.",
)
cards[3].metric("Observed win rate", format_percent(champion.get("observed_win_rate")))
cards[4].metric(
    "Climbing efficiency" if new_growth else "Legacy LP lift · preview",
    format_signed(champion.get(growth_column(champions))),
)
with cards[5]:
    label, cycle = st.columns([4, 1], gap="small")
    label.caption("Specialization efficiency")
    if cycle.button("↻", key="cycle_specialization", help="Cycle correlation, slope, and R²"):
        st.session_state["specialization_metric_index"] = (
            st.session_state.get("specialization_metric_index", 0) + 1
        ) % 3
    index = st.session_state.get("specialization_metric_index", 0)
    if trend is None:
        st.metric("Pearson r", "—")
    elif index == 0:
        st.metric("Pearson r", format_signed(trend["correlation"], digits=3))
    elif index == 1:
        st.metric("LP/game per +10 pp preference", format_signed(trend["slope_per_10pp"], digits=3))
    else:
        st.metric("R²", format_percent(trend["r_squared"], digits=2))
st.caption(
    "Primary = selected champion leads the current active pool; active = appears in that pool; "
    "observed = favoured in an eligible completed rank period, regardless of current primary or active status. "
    f"Active play rate: {format_percent(champion.get('active_play_rate'))}. "
    "Climbing efficiency is the mean across players "
    "of their median LP/game lift versus starting tier. The cycle card summarizes the full-sample "
    f"linear association ({0 if trend is None else trend['players']:,} player-tier observations); it is descriptive."
)

section("Primary relationship", f"Champion preference versus climbing efficiency for {selected}")
if observations_all is None:
    st.info("Player-level champion growth observations are unavailable in this snapshot.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    starting_tier = controls[0].selectbox("Starting tier", ["All tiers", *TIER_ORDER])
    minimum_periods = controls[1].slider("Minimum observed periods", 1, 6, 1)
    minimum_games = controls[2].slider("Minimum attributed games", 1, 30, 1)
    observations = observations_all.loc[
        (observations_all["period_count"] >= minimum_periods)
        & (observations_all["attributed_games"] >= minimum_games)
    ].copy()
    if starting_tier != "All tiers":
        observations = observations.loc[observations["starting_tier"] == starting_tier]
    observations["outcome"] = observations["climbing_efficiency"]
    observations["support_games"] = observations["attributed_games"]
    observations["tier"] = observations["starting_tier"]
    st.caption(
        f"Window: observed rank periods · One point per player and starting tier · "
        f"Player-tier observations: {len(observations):,}"
    )
    if observations.empty:
        st.info("No player observations meet these controls.")
    else:
        st.plotly_chart(
            specialization_relationship_chart(
                observations,
                "champion_commitment",
                AXIS_LABELS["champion_commitment"],
                "Climbing efficiency (LP/game vs tier)",
                binned_relationship(observations, "champion_commitment"),
            ),
            width="stretch",
        )
        st.caption(
            "Champion preference is the mean share of mastery gained on this champion across its favoured periods. "
            "Period LP and games are each allocated by that share; their per-game ratio remains the period rate. "
            "Mastery gained on non-favoured champions leaves a corresponding share of period LP unassigned. "
            "Current primary or active status does not filter these points. Mastery estimates play representation, "
            "not the exact percentage of matches played on the champion."
        )

section("Player mix", f"Who currently specializes in {selected}?")
controls = st.columns([1, 1, 1], gap="small")
basis = controls[0].segmented_control(
    "Mastery window", ["Active (60 days)", "All-time"], default="Active (60 days)"
)
view = controls[1].selectbox("Compare by", ["Tier", "Role"])
over_under_mix = controls[2].toggle("Show over/under", key="mix_over_under")
group = "main_role" if view == "Role" else "tier"
composition = playstyle_composition(players, basis, group, champion_name=selected)
st.caption(
    f"Window: {basis} · Classified primary players: {int(composition['players'].sum()):,} · "
    "Over/under compares each playstyle share with all players in the same tier or role."
)
if composition.empty:
    st.info("No classified primary players match this selection.")
elif over_under_mix:
    baseline = playstyle_composition(players, basis, group)
    comparison = composition_vs_population(composition, baseline, group)
    st.plotly_chart(composition_delta_chart(comparison, group), width="stretch")
else:
    st.plotly_chart(composition_view_chart(composition, group), width="stretch")

left, right = st.columns(2, gap="large")
with left:
    section("Role context", "Inferred role mix")
    over_under_roles = st.toggle("Show over/under versus 20%", key="role_over_under")
    st.plotly_chart(champion_role_chart(champion, over_under_roles), width="stretch")
    st.caption(
        f"Role sample: {format_compact(champion.get('role_sample_player_count'))} players. "
        "The 20% line is an equal-share reference across five roles, not the population role mix. "
        "These are inferred player roles, not match lanes."
    )
with right:
    section("Mastery context", "How deep is mastery on this champion?")
    metrics = st.columns(3)
    metrics[0].metric("Mean mastery", format_compact(champion.get("avg_mastery_points")))
    metrics[1].metric("Median mastery", format_compact(champion.get("median_mastery_points")))
    metrics[2].metric("Players ≥100K", format_compact(champion.get("expert_player_count")))
    st.caption(
        f"Players with any mastery: {format_compact(champion.get('mastery_player_count'))}. "
        "The 100K threshold is configured in dbt. Exact-point modes are not useful for this broad distribution."
    )

section("Historical outcomes", "Playstyle by starting tier")
if tier_growth is None:
    st.info("Tier-specific champion growth observations are unavailable in this snapshot.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    outcome = controls[0].selectbox("Outcome", ["Climbing efficiency", "Win rate"])
    minimum_players = controls[1].slider("Minimum players per cell", 1, 50, 3, 1)
    over_under_outcome = controls[2].toggle("Show over/under", key="outcome_over_under")
    metric = "climbing_efficiency" if outcome == "Climbing efficiency" else "observed_win_rate"
    base = tier_growth.loc[
        (tier_growth["champion_name"] == selected)
        & (tier_growth["cohort_scope"] == "champion_tier")
    ].copy()
    tier_styles = tier_growth.loc[
        (tier_growth["champion_name"] == selected)
        & (tier_growth["cohort_scope"] == "champion_tier_playstyle")
        & (tier_growth["playstyle"].isin(PLAYSTYLE_ORDER))
        & (tier_growth["observed_player_count"] >= minimum_players)
    ].copy()
    st.caption(
        "Window: observed rank periods · Climbing efficiency is player-equal LP/game lift versus starting tier. "
        "Over/under subtracts this champion's average in the same starting tier; win-rate differences use percentage points."
    )
    if outcome == "Win rate" and not over_under_outcome:
        st.caption("Win-rate colors are zoomed to 45–55%; cells outside that range keep their actual value in the label and hover.")
    if tier_styles.empty:
        st.info("No tier and playstyle groups meet the selected player threshold.")
    else:
        st.plotly_chart(
            champion_tier_outcome_heatmap(tier_styles, base, metric, over_under_outcome),
            width="stretch",
        )

section("Ranked activity", f"Estimated ranked-mastery share for {selected} players")
if ranked_share_players is None:
    st.info("Ranked-mastery player summaries are unavailable in this snapshot.")
else:
    controls = st.columns([1.5, 1, 1], gap="small")
    window = controls[0].selectbox(
        "Rank-period window",
        ["All observed periods", "Last 60 days", "Last 30 days", "Latest completed period"],
    )
    minimum_ranked_players = controls[1].slider("Minimum players per tier", 1, 30, 3, 1)
    over_under_ranked = controls[2].toggle("Show over/under", key="ranked_over_under")
    period_players = ranked_share_players.loc[ranked_share_players["window_name"] == window]
    ranked_by_tier = champion_ranked_share_by_tier(period_players, selected)
    ranked_by_tier = ranked_by_tier.loc[ranked_by_tier["players"] >= minimum_ranked_players]
    st.caption(
        "Each player contributes their median estimated ranked-mastery share in the window. "
        "Over/under compares these players with all observed players in the same starting tier."
    )
    if ranked_by_tier.empty:
        st.info("No starting tiers meet the selected player threshold.")
    else:
        st.plotly_chart(champion_ranked_share_chart(ranked_by_tier, over_under_ranked), width="stretch")
    if period_players["first_period_end"].min() == period_players["last_period_end"].max():
        st.caption("Only one completed rank period is available so far; the window choices currently show the same observations.")

section("Affinity", "Champions in the same active player pools")
st.caption("Co-occurrence describes player preference, not team synergy or champions used together in a match.")
minimum_pair = st.slider("Minimum shared players", 20, 1000, 100, 20)
neighbors = champion_neighbors(cooccurrence, selected, minimum_pair)
if neighbors.empty:
    st.info("No champion pairs meet this support threshold.")
else:
    st.plotly_chart(cooccurrence_chart(neighbors), width="stretch")
    st.dataframe(
        neighbors.loc[:, ["related_champion", "pair_player_count", "lift", "npmi"]].head(20),
        hide_index=True,
        width="stretch",
    )

with st.expander("How to read these comparisons"):
    st.markdown(
        "Over/under shows a signed difference, not a percentage ratio. A climbing-efficiency difference "
        "is measured in LP per game; a share or win-rate difference is measured in percentage points. "
        "Players can favour several champions in one period. Ranked-mastery share estimates the portion "
        "of mastery gained from ranked games, not the exact portion of games played in ranked."
    )
