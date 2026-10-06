from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from app_core import config as dashboard_config
from app_core.analysis import (
    AXIS_LABELS,
    binned_relationship,
    champion_overlap_summary,
    champion_ranked_share_by_tier,
    composition_vs_population,
    expert_share_vs_sample,
    growth_column,
    playstyle_composition,
    specialization_trend,
    tier_population_comparison,
)
from app_core.charts import (
    champion_ranked_share_chart,
    champion_role_chart,
    champion_tier_outcome_heatmap,
    composition_delta_chart,
    composition_view_chart,
    cooccurrence_chart,
    specialization_relationship_chart,
    style_figure,
)
from app_core.config import PLAYSTYLE_COLORS, PLAYSTYLE_LABELS, PLAYSTYLE_ORDER, TIER_ORDER
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
    support_warning,
)

setup_page("Champion Explorer")
minimum_support = getattr(dashboard_config, "MIN_SUPPORT_PLAYERS", 3)
try:
    players = load_dataset("players")
    champions = load_dataset("champions")
    styles = load_dataset("champion_playstyles")
    cooccurrence = load_dataset("cooccurrence")
    growth_players = load_optional_dataset("champion_growth_players")
    tier_growth = load_optional_dataset("champion_tier_growth")
    ranked_share_players = load_optional_dataset("ranked_mastery_cohorts")
    tier_mastery = load_optional_dataset("champion_tier_mastery")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players, champions]))
minimum_mastery = st.sidebar.slider("Minimum champion mastery points", 0, 90_000, 20_000, 10_000, help="Applies to the mastery-by-tier views. Mean and median mastery cards use at least 15K points, or this higher threshold when selected.")
hero(
    "Champion explorer",
    "How does champion preference relate to climbing?",
    "Compare each champion's players with the wider population, inspect playstyle and role tendencies, "
    "and explore how mastery share relates to rank growth.",
)

names = sorted(champions["champion_name"].dropna().unique().tolist())
selected = st.selectbox("Champion", names, index=names.index("Ahri") if "Ahri" in names else 0)
champion = champions.loc[champions["champion_name"] == selected].iloc[0]
historical_sample = champion.get("observed_player_count")
has_historical_support = pd.notna(historical_sample) and historical_sample >= minimum_support
show_thin_cards = False
if not has_historical_support and pd.notna(historical_sample) and historical_sample > 0:
    show_thin_cards = support_warning(
        f"Insufficient data: historical outcome cards use only {int(historical_sample)} "
        f"player(s), below the default of {minimum_support}. Hidden by default.",
        "champion_cards",
    )
display_historical = has_historical_support or show_thin_cards
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
st.caption(f"Reference positions: {positions_label} · Champion metadata patch: {champion.get('champion_patch', '—')}")

trend = specialization_trend(observations_all) if observations_all is not None else None
overlap = champion_overlap_summary(cooccurrence, selected)
period_all = ranked_share_players.loc[ranked_share_players["window_name"] == "All observed periods"] if ranked_share_players is not None else None
selected_period = period_all.loc[period_all["favoured_champions"].apply(lambda names: selected in names if isinstance(names, (list, tuple, np.ndarray)) else False)] if period_all is not None else None
historical_denominator = len(period_all) if period_all is not None else 0
card_mastery_threshold = max(15_000, minimum_mastery)
if tier_mastery is None:
    mastery_overall = None
    mastery_baselines = pd.Series(dtype=float)
else:
    mastery_cohort = tier_mastery.loc[
        tier_mastery["tier"].eq("ALL")
        & tier_mastery["minimum_mastery"].eq(card_mastery_threshold)
    ]
    matching_mastery = mastery_cohort.loc[mastery_cohort["champion_name"].eq(selected)]
    mastery_overall = matching_mastery.iloc[0] if not matching_mastery.empty else None
    mastery_baselines = mastery_cohort[["mean_mastery", "median_mastery"]].mean()


def toggle_count(key: str) -> None:
    state = f"show_{key}_pct"
    st.session_state[state] = not st.session_state.get(state, True)


def toggle_mastery_comparison(key: str) -> None:
    state = f"show_{key}_comparison"
    st.session_state[state] = not st.session_state.get(state, False)


def mastery_card(card, key: str, label: str, value: float, baseline: float) -> None:
    with card.container(key=f"{key}_metric"):
        compared = st.session_state.get(f"show_{key}_comparison", False)
        st.button(
            "→", key=f"toggle_{key}_comparison", on_click=toggle_mastery_comparison, args=(key,),
            help=f"{'Show champion value' if compared else 'Compare with the average across champions'} at the current mastery threshold.",
        )
        if compared:
            displayed = f"{100 * (value / baseline - 1):+.1f}%" if pd.notna(value) and pd.notna(baseline) and baseline > 0 else "—"
        else:
            displayed = format_compact(value)
        st.metric(
            f"{label} vs sample" if compared else label,
            displayed,
            help=f"Sample average across champions: {format_compact(baseline)}. Each champion contributes once; mastery holders meet the {card_mastery_threshold:,}-point threshold.",
        )


def cycle_ranked_share() -> None:
    st.session_state["ranked_share_metric_index"] = (st.session_state.get("ranked_share_metric_index", 0) + 1) % 3


def count_card(card, key: str, label: str, value: float, denominator: float, help_text: str) -> None:
    with card.container(key=f"{key}_metric"):
        percent = st.session_state.get(f"show_{key}_pct", True)
        st.button("%", key=f"toggle_{key}_pct", help=f"Show {'count' if percent else 'share of the relevant population'}", on_click=toggle_count, args=(key,))
        displayed = (format_percent(value / denominator) if denominator else "—") if percent else format_compact(value)
        st.metric(label, displayed, help=help_text)


def cycle_association_metric() -> None:
    st.session_state["specialization_metric_index"] = (
        st.session_state.get("specialization_metric_index", 0) + 1
    ) % 3


cards = st.columns(6)
count_card(cards[0], "primary", "Primary players", players["active_primary_champion_name"].eq(selected).sum(), len(players), "Players whose current active mastery pool is led by this champion. Percentage uses the current tracked sample through Master.")
count_card(cards[1], "active", "Active players", champion.get("active_player_count"), champion.get("active_pool_player_count"), "Players whose current active mastery pool contains this champion. Percentage uses all active-pool players in the same champion mart.")
count_card(cards[2], "historical", "Historical players", len(selected_period) if selected_period is not None else champion.get("observed_player_count"), historical_denominator, "Players who favoured this champion in the all-period ranked-share cohort. Percentage uses all players in that same cohort.")
cards[3].metric(
    "Mean player win rate", format_percent(champion.get("observed_win_rate")) if display_historical else "—",
    help="Mean player win rate from attributed ranked outcomes. This is not the champion's match-level win rate.",
)
cards[4].metric(
    "LP/game above tier" if new_growth else "LP/game lift (older estimate)",
    format_signed(champion.get(growth_column(champions))) if display_historical else "—",
    help="Positive values exceed the starting-tier baseline in this sample; negative values fall below it.",
)
with cards[5].container(key="association_metric"):
    index = st.session_state.get("specialization_metric_index", 0)
    metric_names = ("Pearson r", "slope", "R²")
    st.button(
        "→",
        key="cycle_specialization",
        help=f"Using: {metric_names[index]}. Click to cycle the specialization–growth association metric.",
        on_click=cycle_association_metric,
    )
    if trend is None or not display_historical:
        st.metric("SxG Association", "—")
    elif index == 0:
        st.metric("SxG Association", format_signed(trend["correlation"], digits=3))
    elif index == 1:
        st.metric("SxG Association", format_signed(trend["slope_per_10pp"], digits=3))
    else:
        st.metric("SxG Association", format_percent(trend["r_squared"], digits=2))
st.caption(
    "Primary = selected champion leads the current active pool; active = appears in that pool; "
    "historical = favoured in an eligible completed rank period. "
    f"Among players with an active pool, {format_percent(champion.get('active_play_rate'))} include this champion. "
    "Count-card denominators are stated in their tooltips; outcome cards use the full champion historical sample. SxG means specialization–growth association: it compares "
    "each player's mean mastery share on this champion in favoured rank periods with that player's median "
    "LP/game above the starting-tier baseline. It includes "
    f"{0 if trend is None else trend['players']:,} player–tier observations and is descriptive."
)
if not has_historical_support and not (pd.notna(historical_sample) and historical_sample > 0):
    st.warning(f"Insufficient data: historical outcome cards need at least {minimum_support} players for this champion.")
elif trend is not None and trend["players"] < minimum_support:
    st.warning(f"Insufficient data: SxG Association needs at least {minimum_support} player–tier observations.")

extra = st.columns(4)
if period_all is not None and not period_all.empty:
    ranked_values = selected_period["median_ranked_mastery_share"]
    baseline_values = period_all["median_ranked_mastery_share"]
    ranked_estimate = ranked_values.median()
    ranked_median_difference = ranked_estimate - baseline_values.median()
    ranked_mean_difference = ranked_values.mean() - baseline_values.mean()
else:
    ranked_estimate = float("nan")
    ranked_median_difference = float("nan")
    ranked_mean_difference = float("nan")
with extra[0].container(key="ranked_share_metric"):
    ranked_index = st.session_state.get("ranked_share_metric_index", 0)
    ranked_modes = ("Cohort median", "Median difference from all players", "Mean difference from all players")
    st.button("→", key="cycle_ranked_share", on_click=cycle_ranked_share, help=f"Showing: {ranked_modes[ranked_index]}. Click for the next ranked-share measure.")
    if ranked_index == 0:
        ranked_display = format_percent(ranked_estimate)
    else:
        difference = ranked_median_difference if ranked_index == 1 else ranked_mean_difference
        ranked_display = f"{100 * difference:+.1f} pp" if pd.notna(difference) else "—"
    st.metric("Ranked share", ranked_display, help="Cohort: players who favoured this champion in completed rank periods. Differences compare with all players in the same all-period ranked cohort. Estimated from ranked wins/losses and mastery gain; selection bias remains.")
extra[1].metric("Mean conditional pool overlap", format_percent(overlap["conditional"]), help=f"Shared-player-weighted P(other champion in pool | this champion in pool), across {overlap['pairs']} retained pairs. Pairs with fewer than five shared players are absent.")
extra[2].metric("Mean player active HHI", format_signed(players.loc[players["active_primary_champion_name"] == selected, "active_hhi"].mean(), 3), help="Mean active HHI from the current player-profile mart, among players whose current primary champion is selected. Each player has one current active pool; higher HHI means that pool's mastery is more concentrated.")
filtered_expert_share = mastery_overall["expert_player_count"] / mastery_overall["player_count"] if mastery_overall is not None and mastery_overall["player_count"] else float("nan")
extra[3].metric("Expert share among mastery holders", format_percent(filtered_expert_share), help=f"Players with at least 100,000 mastery points divided by tracked players with at least {card_mastery_threshold:,} points on this champion. This updates with the mastery threshold.")

section("Historical relationship", f"Mastery share and rank growth for {selected}")
if observations_all is None:
    st.info("Player-level champion growth observations are unavailable in this snapshot.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    starting_tier = controls[0].selectbox("Starting tier", ["All tiers", *TIER_ORDER])
    minimum_periods = controls[1].slider("Minimum observed periods", 1, 6, 1)
    minimum_games = controls[2].slider(
        "Minimum mastery-weighted games", 1, 30, 1,
        help="Ranked games allocated by mastery share; these are estimated game equivalents, not observed champion matches.",
    )
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
        trend_bands = binned_relationship(observations, "champion_commitment")
        thin_bands = int(trend_bands["players"].lt(minimum_support).sum())
        if thin_bands:
            show_thin_bands = support_warning(
                f"Insufficient data: {thin_bands} mastery-share band(s) have fewer than "
                f"{minimum_support} observations. The gold line hides them by default.",
                "champion_bands",
            )
            if not show_thin_bands:
                trend_bands.loc[trend_bands["players"] < minimum_support, "outcome"] = float("nan")
        if len(observations) < minimum_support:
            st.warning(f"Insufficient data: only {len(observations)} player–tier observations match these controls.")
        st.plotly_chart(
            specialization_relationship_chart(
                observations,
                "champion_commitment",
                AXIS_LABELS["champion_commitment"],
                "LP/game above starting-tier baseline",
                trend_bands,
            ),
            width="stretch",
        )
        st.caption(
            "Mastery share is the mean share gained on this champion across periods where it was favoured. "
            "Gold line: mean outcome in mastery-share bands with at least three observations. "
            "The optional local-median line is hidden in the legend by default. "
            "Period LP and games are each allocated by that share; their per-game ratio remains the period rate. "
            "Mastery gained on non-favoured champions leaves a corresponding share of period LP unassigned. "
            "Current primary or active status does not filter these points. Mastery estimates play representation, "
            "not the exact percentage of matches played on the champion."
        )

section("Player mix", f"Who has {selected} as their primary champion?")
controls = st.columns([1, 1, 1], gap="small")
basis = controls[0].segmented_control(
    "Mastery window", ["Active (60 days)", "All-time"], default="Active (60 days)"
)
view = controls[1].selectbox("Compare by", ["Tier", "Rank score", "Role"])
over_under_mix = controls[2].toggle("Difference from sample", key="mix_over_under")
mix_display = st.segmented_control("Progression display", ["Progression lines", "Bars"], default="Progression lines", key="mix_display") if view != "Role" else "Bars"
group = "main_role" if view == "Role" else "rank_band" if view == "Rank score" else "tier"
mix_players = players.copy()
if group == "rank_band":
    mix_players["rank_band"] = (mix_players["rank_score"] // 200 * 200).astype("Int64")
composition = playstyle_composition(mix_players, basis, group, champion_name=selected)
composition_players = int(composition["players"].sum())
show_thin_composition = False
if not composition.empty:
    group_support = composition.groupby(group, observed=True)["players"].transform("sum")
    thin_groups = composition.loc[group_support < minimum_support, group].nunique()
    thin_segments = int(composition["players"].lt(minimum_support).sum())
    if thin_groups or thin_segments:
        show_thin_composition = support_warning(
            f"Insufficient data: {thin_groups} {view.lower()} group(s) and {thin_segments} "
            f"playstyle segment(s) fall below {minimum_support} primary players. Hidden by default; "
            "visible share bars may total less than 100%.",
            "champion_composition",
        )
        if not show_thin_composition:
            composition = composition.loc[group_support >= minimum_support]
st.caption(
    f"Window: {basis} · Classified primary players: {composition_players:,} · "
    "Primary means the leading champion in the selected mastery window. Differences compare "
    "playstyle shares with classified players in the same current tier, rank-score band, or role."
)
if composition.empty:
    if composition_players:
        st.warning(f"Insufficient data: no group has at least {minimum_support} primary players.")
    else:
        st.info("No classified primary players match this selection.")
elif over_under_mix:
    baseline = playstyle_composition(mix_players, basis, group)
    comparison = composition_vs_population(composition, baseline, group)
    if not show_thin_composition:
        comparison = comparison.loc[comparison["players"] >= minimum_support]
    if comparison.empty:
        st.warning(f"Insufficient data: no playstyle comparison has at least {minimum_support} primary players.")
    else:
        if mix_display == "Progression lines":
            comparison["Playstyle"] = comparison["playstyle"].map(PLAYSTYLE_LABELS)
            fig = px.line(comparison, x=group, y="difference_pp", color="Playstyle", markers=True, category_orders={group: TIER_ORDER, "Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]} if group == "tier" else {"Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]}, color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()}, custom_data=["players", "share", "population_share"])
            fig.add_hline(y=0, line_dash="dot")
            fig.update_traces(line={"width": 3}, marker={"size": 8}, hovertemplate="%{x}<br>%{fullData.name}: %{y:+.1f} pp<br>Players: %{customdata[0]:,}<br>Champion share: %{customdata[1]:.1%}<br>Sample share: %{customdata[2]:.1%}<extra></extra>")
            fig.update_xaxes(title="Current tier" if group == "tier" else "Rank score (200-point bands)")
            fig.update_yaxes(title="Difference from sample (percentage points)")
            st.plotly_chart(style_figure(fig, height=460), width="stretch")
        else:
            st.plotly_chart(composition_delta_chart(comparison, group), width="stretch")
else:
    supported_composition = composition if show_thin_composition else composition.loc[
        composition["players"] >= minimum_support
    ]
    if supported_composition.empty:
        st.warning(f"Insufficient data: no playstyle segment has at least {minimum_support} primary players.")
    else:
        if mix_display == "Progression lines":
            supported_composition["Playstyle"] = supported_composition["playstyle"].map(PLAYSTYLE_LABELS)
            fig = px.line(supported_composition, x=group, y="share", color="Playstyle", markers=True, category_orders={group: TIER_ORDER, "Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]} if group == "tier" else {"Playstyle": [PLAYSTYLE_LABELS[item] for item in PLAYSTYLE_ORDER]}, color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()}, custom_data=["players"])
            fig.update_traces(line={"width": 3}, marker={"size": 8}, hovertemplate="%{x}<br>%{fullData.name}: %{y:.1%}<br>Players: %{customdata[0]:,}<extra></extra>")
            fig.update_xaxes(title="Current tier" if group == "tier" else "Rank score (200-point bands)")
            fig.update_yaxes(title="Share within group", tickformat=".0%")
            st.plotly_chart(style_figure(fig, height=460), width="stretch")
        else:
            st.plotly_chart(composition_view_chart(supported_composition, group), width="stretch")

left, right = st.columns(2, gap="large")
with left:
    section("Role context", "Estimated roles of this champion's players")
    over_under_roles = st.toggle("Difference from equal role shares (20%)", key="role_over_under")
    role_sample = champion.get("role_sample_player_count")
    if pd.isna(role_sample) or role_sample < minimum_support:
        show_thin_roles = support_warning(
            f"Insufficient data: fewer than {minimum_support} players support this role mix.",
            "champion_roles",
        ) if pd.notna(role_sample) and role_sample > 0 else False
        if not show_thin_roles and not (pd.notna(role_sample) and role_sample > 0):
            st.warning("Insufficient data: no players support this role mix.")
    else:
        show_thin_roles = False
    if pd.notna(role_sample) and (role_sample >= minimum_support or show_thin_roles):
        st.plotly_chart(champion_role_chart(champion, over_under_roles), width="stretch")
    st.caption(
        f"Role sample: {format_compact(champion.get('role_sample_player_count'))} players. "
        "The 20% line is an equal-share reference across five roles, not the population role mix. "
        "The chart averages inferred roles of players who recently used this champion, not the lanes where they played it."
    )
with right:
    section("Mastery context", "How deep is mastery on this champion?")
    mastery_sample = mastery_overall["player_count"] if mastery_overall is not None else float("nan")
    if pd.isna(mastery_sample) or mastery_sample < minimum_support:
        show_thin_mastery = support_warning(
            f"Insufficient data: fewer than {minimum_support} players have mastery on this champion.",
            "champion_mastery",
        ) if pd.notna(mastery_sample) and mastery_sample > 0 else False
        if not show_thin_mastery and not (pd.notna(mastery_sample) and mastery_sample > 0):
            st.warning("Insufficient data: no mastery observations are available for this champion.")
    else:
        show_thin_mastery = False
    if pd.notna(mastery_sample) and (mastery_sample >= minimum_support or show_thin_mastery):
        metrics = st.columns(2)
        mastery_card(metrics[0], "mastery_mean", "Mean mastery", mastery_overall["mean_mastery"], mastery_baselines.get("mean_mastery"))
        mastery_card(metrics[1], "mastery_median", "Median mastery", mastery_overall["median_mastery"], mastery_baselines.get("median_mastery"))
    if mastery_overall is None:
        st.info("Mastery cards need a refreshed champion tier mastery extract with 15K and all-tier summaries.")
    st.caption(
        f"Mastery holders at or above {card_mastery_threshold:,} points: {format_compact(mastery_sample)}. "
        "Mean and median use cumulative champion mastery among these players. The arrow shows percentage difference from the equal-weight average across champions at this threshold."
    )

section("Rank representation", f"Where {selected} players sit in the ladder")
representation_basis = st.segmented_control("Primary-player window", ["Active (60 days)", "All-time"], default="Active (60 days)", key="representation_basis")
population_table = tier_population_comparison(players, selected, representation_basis)
representation = population_table.dropna(subset=["representation_ratio"])
if not representation.empty:
    fig = go.Figure(go.Scatter(
        x=representation["tier"], y=representation["representation_ratio"], mode="lines+markers",
        line={"color": "#D8A52D", "width": 3}, marker={"size": 9},
        customdata=representation[["tier", "champion_players", "all_players"]].to_numpy(),
        hovertemplate="%{customdata[0]}<br>Representation: %{y:.2f}×<br>Champion primary players: %{customdata[1]:,}<br>All tracked players: %{customdata[2]:,}<extra></extra>",
    ))
    fig.add_hline(y=1, line_dash="dot", line_color="#9AABC0")
    fig.update_xaxes(title="Current tier", categoryorder="array", categoryarray=TIER_ORDER)
    fig.update_yaxes(title="Representation difference from sample", range=[0, 3], tickvals=[0, 1, 2, 3], ticktext=["−100%", "0%", "+100%", "+200%"])
    st.plotly_chart(style_figure(fig, height=430), width="stretch")
st.caption("Each point compares the champion's primary-player share in a tier with that tier's share of all tracked players. The dotted line is equal representation (1×); the visible vertical range is capped at 3×.")
primary_players = players.loc[players["active_primary_champion_name" if representation_basis == "Active (60 days)" else "top_champion_name"] == selected]
rank_cards = st.columns(2)
rank_cards[0].metric("Mean primary-player rank score", format_compact(primary_players["rank_score"].mean()))
rank_cards[1].metric("Median primary-player rank score", format_compact(primary_players["rank_score"].median()))

section("Mastery by tier", f"{selected} mastery and expert population")
if tier_mastery is None:
    st.info("Champion-by-tier mastery requires the new champion_tier_mastery extract. Run the snapshot exporter to populate this view.")
else:
    tier_rows = expert_share_vs_sample(tier_mastery, selected, minimum_mastery)
    tier_rows["tier"] = pd.Categorical(tier_rows["tier"], categories=TIER_ORDER, ordered=True)
    tier_rows = tier_rows.sort_values("tier")
    if tier_rows.empty:
        st.info("No mastery holders meet this threshold.")
    else:
        measure = st.segmented_control("Tier measure", ["Expert players", "Mastery distribution"], default="Expert players")
        if measure == "Expert players":
            normalize_experts = st.toggle("Difference from sampled expert share", help="Compare this champion's expert share with the pooled expert share among all champion mastery holders in the same tier, using the selected minimum mastery threshold.")
            value_column = "expert_share_difference_pct" if normalize_experts else "expert_player_count"
            fig = px.line(tier_rows, x="tier", y=value_column, markers=True, custom_data=["player_count", "expert_player_count", "expert_share", "sample_expert_share"])
            if normalize_experts:
                fig.add_hline(y=0, line_dash="dot", line_color="#9AABC0")
                fig.update_traces(hovertemplate="%{x}<br>Difference: %{y:+.1f}%<br>Champion expert share: %{customdata[2]:.1%}<br>Sample expert share: %{customdata[3]:.1%}<br>Mastery holders: %{customdata[0]:,}<extra></extra>")
            else:
                fig.update_traces(hovertemplate="%{x}<br>Experts: %{y:,}<br>Champion expert share: %{customdata[2]:.1%}<br>Sample expert share: %{customdata[3]:.1%}<br>Mastery holders: %{customdata[0]:,}<extra></extra>")
            fig.update_xaxes(title="Current tier")
            fig.update_yaxes(title="Difference from sampled tier expert share (%)" if normalize_experts else "Players with at least 100K champion mastery")
        else:
            fig = go.Figure()
            log_mastery = lambda column: np.log10(tier_rows[column].clip(lower=1))
            fig.add_trace(go.Box(x=tier_rows["tier"], q1=log_mastery("q1_mastery"), median=log_mastery("median_mastery"), q3=log_mastery("q3_mastery"), lowerfence=log_mastery("min_mastery"), upperfence=log_mastery("max_mastery"), name=selected, boxpoints=False))
            fig.update_xaxes(title="Current tier")
            fig.update_yaxes(title="Log10 champion mastery points")
        st.plotly_chart(style_figure(fig, height=460), width="stretch")
        st.caption(f"Minimum champion mastery: {minimum_mastery:,} points. Expert means at least 100,000 points. Difference mode compares expert shares, using the pooled sample share in each tier as 0%. Tier summaries use all mastery holders, not only primary players. Log mastery transforms the displayed quartiles and fences after the threshold filter.")

section("Historical outcomes", "Success by playstyle in tiers")
st.caption("Starting tier × observed playstyle × player outcome. Each cell averages player summaries and shows its player count.")
if tier_growth is None:
    st.info("Tier-specific champion growth observations are unavailable in this snapshot.")
else:
    controls = st.columns([1, 1, 1], gap="small")
    outcome = controls[0].selectbox("Outcome", ["LP/game above tier baseline", "Win rate"])
    minimum_players = controls[1].slider("Minimum players per cell", 1, 50, minimum_support, 1)
    over_under_outcome = controls[2].toggle("Difference from champion's tier average", key="outcome_over_under")
    metric = "climbing_efficiency" if outcome == "LP/game above tier baseline" else "observed_win_rate"
    base = tier_growth.loc[
        (tier_growth["champion_name"] == selected)
        & (tier_growth["cohort_scope"] == "champion_tier")
    ].copy()
    tier_styles = tier_growth.loc[
        (tier_growth["champion_name"] == selected)
        & (tier_growth["cohort_scope"] == "champion_tier_playstyle")
        & (tier_growth["playstyle"].isin(PLAYSTYLE_ORDER))
    ].copy()
    thin_cells = int(tier_styles["observed_player_count"].lt(minimum_players).sum())
    tier_styles.attrs["minimum_players"] = minimum_players
    if thin_cells:
        tier_styles.attrs["show_sparse"] = support_warning(
            f"Insufficient data: {thin_cells} tier–playstyle cell(s) have fewer than "
            f"{minimum_players} players and are marked n<{minimum_players}.",
            "champion_tier_outcomes",
        )
    st.caption(
        "Each cell averages player summaries from eligible rank periods. Difference mode subtracts "
        "this champion's average in the same starting tier; win-rate differences use percentage points."
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
    minimum_ranked_players = controls[1].slider("Minimum players per tier", 1, 30, minimum_support, 1)
    over_under_ranked = controls[2].toggle("Difference from all players in tier", key="ranked_over_under")
    period_players = ranked_share_players.loc[ranked_share_players["window_name"] == window]
    ranked_by_tier = champion_ranked_share_by_tier(period_players, selected)
    thin_tiers = int(ranked_by_tier["players"].lt(minimum_ranked_players).sum())
    if thin_tiers:
        show_thin_ranked = support_warning(
            f"Insufficient data: {thin_tiers} tier(s) have fewer than "
            f"{minimum_ranked_players} players and are hidden by default.",
            "champion_ranked_activity",
        )
        if not show_thin_ranked:
            ranked_by_tier = ranked_by_tier.loc[ranked_by_tier["players"] >= minimum_ranked_players]
    st.caption(
        "Each player contributes their median estimated ranked-mastery share in the window. "
        "Difference mode compares these players with all observed players in the same starting tier. "
        "Windows end at the latest observed period, not today. Membership means this champion was favoured in at least one period."
    )
    if ranked_by_tier.empty:
        st.info("No starting tiers meet the selected player threshold.")
    else:
        st.plotly_chart(champion_ranked_share_chart(ranked_by_tier, over_under_ranked), width="stretch")
    if period_players["first_period_end"].min() == period_players["last_period_end"].max():
        st.caption("Only one completed rank period is available so far; the window choices currently show the same observations.")

section("Pool overlap", "Champions in the same active player pools")
st.caption("Co-occurrence describes player preference, not team synergy or champions used together in a match.")
st.caption("The source mart retains pairs with at least five shared players, even when this control is set lower.")
minimum_pair = st.slider("Minimum shared players", minimum_support, 1000, 100, 1)
neighbor_limit = st.slider("Champions shown in overlap plot", 5, 50, 20, 1)
neighbors = champion_neighbors(cooccurrence, selected, minimum_support)
thin_pairs = int(neighbors["pair_player_count"].lt(minimum_pair).sum())
if thin_pairs:
    show_thin_pairs = support_warning(
        f"Insufficient data: {thin_pairs} champion pair(s) have fewer than "
        f"{minimum_pair} shared players and are hidden by default.",
        "champion_pairs",
    )
    if not show_thin_pairs:
        neighbors = neighbors.loc[neighbors["pair_player_count"] >= minimum_pair]
if neighbors.empty:
    st.info("No champion pairs meet this support threshold.")
else:
    st.plotly_chart(cooccurrence_chart(neighbors, top_n=neighbor_limit), width="stretch")

with st.expander("How to read these comparisons"):
    st.markdown(
        "Difference mode shows a signed difference, not a percentage ratio. A rank-growth difference "
        "is measured in LP per game; a share or win-rate difference is measured in percentage points. "
        "Players can favour several champions in one period. Ranked-mastery share estimates the portion "
        "of mastery gained from ranked games, not the exact portion of games played in ranked."
    )
    st.markdown(
        "**LP/game above tier baseline** averages players' mastery-share-weighted median period outcomes "
        "relative to their starting-tier baseline. Zero means the baseline, not zero LP gained. "
        "**Pearson r** summarizes linear association; **slope** is the fitted LP/game difference for a "
        "10-percentage-point increase in mastery share; **R²** describes the variation captured by that linear fit. "
        "None establishes causation or predicts an individual player's result."
    )
