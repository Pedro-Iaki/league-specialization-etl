from __future__ import annotations

import plotly.express as px
from app_core import config as dashboard_config
from app_core.analysis import (
    champion_landscape_data,
    champion_overlap_summary,
    mastery_representation_by_tier,
    one_trick_tier_distribution,
    specialization_trend,
)
from app_core.charts import champion_efficiency_landscape, population_box_chart, style_figure
from app_core.config import TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.i18n import st
from app_core.population import apply_tier_weights, calibrate_population, weighted_summary
from app_core.population_champions import champion_estimates, population_pairs
from app_core.population_ui import population_controls
from app_core.ui import data_source_caption, hero, render_load_error, section, setup_page, support_warning

setup_page("Cross Champion View")
default_curve_champions = ["Teemo", "Mordekaiser", "Riven", "Caitlyn", "Hwei"]
try:
    players = load_dataset("players", include_all_tiers=True)
    champions = load_dataset("champions")
    pairs = load_dataset("cooccurrence")
    growth = load_optional_dataset("champion_growth_players")
    ranked = load_optional_dataset("ranked_mastery_cohorts")
    tier_mastery = load_optional_dataset("champion_tier_mastery")
    player_mastery = load_optional_dataset("champion_player_mastery_share")
    population_activity = load_optional_dataset("champion_population_activity")
    tier_pairs = load_optional_dataset("champion_population_pairs")
    growth_population = load_optional_dataset("growth_players")
except DashboardDataError as error:
    render_load_error(error)

data_source_caption(data_freshness([players, champions]))
hero("Cross-champion view", "Which champions stand out in the selected population?", "Rank champions by player outcomes, mastery depth, ladder position, estimated ranked activity, and active-pool overlap.")
try:
    players, population_diagnostics, use_population_weights = population_controls(players)
    if use_population_weights:
        if player_mastery is not None:
            player_mastery = apply_tier_weights(player_mastery, population_diagnostics)
        if tier_mastery is not None:
            tier_mastery = apply_tier_weights(tier_mastery.loc[tier_mastery["tier"].ne("ALL")], population_diagnostics)
        if population_activity is not None:
            population_activity = apply_tier_weights(population_activity, population_diagnostics)
        if tier_pairs is not None:
            pairs = population_pairs(apply_tier_weights(tier_pairs, population_diagnostics))
        if growth is not None and growth_population is not None:
            _, growth_diagnostics = calibrate_population(growth_population, tier_column="starting_tier")
            growth = apply_tier_weights(growth, growth_diagnostics, "starting_tier")
        if ranked is not None:
            ranked, _ = calibrate_population(ranked, tier_column="starting_tier", scope_columns=("window_name", "region", "queue"))
        champions = champion_estimates(champions, players, growth, ranked, player_mastery, tier_mastery, population_activity)
except ValueError as error:
    render_load_error(error)
st.caption("Population mode weights pooled summaries before filters; individual points and support counts remain observations. Historical estimates describe represented player–tier observations with completed periods, not all ranked players.")
st.caption("Champion overlap uses tier-preserving counts in population mode; support remains observed. Older snapshots without that export keep sample overlap.")
if use_population_weights and population_activity is None:
    st.info("Population estimates of active play rate and role mix need the champion_population_activity export. Refresh the snapshots to enable them.")

table = champions.copy()
if tier_mastery is not None:
    mastery_15k = tier_mastery.loc[tier_mastery["tier"].eq("ALL") & tier_mastery["minimum_mastery"].eq(15_000)].set_index("champion_name")
    if not mastery_15k.empty:
        table["mean_mastery_15k"] = table["champion_name"].map(mastery_15k["mean_mastery"])
        table["median_mastery_15k"] = table["champion_name"].map(mastery_15k["median_mastery"])
        table["mastery_players_15k"] = table["champion_name"].map(mastery_15k["player_count"])
if growth is not None:
    associations = growth.groupby("champion_name", observed=True).apply(specialization_trend, include_groups=False)
    for name, values in associations.items():
        table.loc[table["champion_name"] == name, "mg_association"] = values["correlation"]
        table.loc[table["champion_name"] == name, "association_players"] = values["players"]
for name in table["champion_name"]:
    result = champion_overlap_summary(pairs, name)
    table.loc[table["champion_name"] == name, "conditional_overlap"] = result["conditional"]
    table.loc[table["champion_name"] == name, "overlap_pairs"] = result["pairs"]
if ranked is not None:
    all_periods = ranked.loc[ranked["window_name"] == "All observed periods"].explode("favoured_champions")
    summaries = weighted_summary(all_periods, "favoured_champions", {"mean": "median_ranked_mastery_share"}).set_index("favoured_champions").rename(columns={"players": "count"})
    table["mean_ranked_share"] = table["champion_name"].map(summaries["mean"])
    table["ranked_share_players"] = table["champion_name"].map(summaries["count"])

metrics = {
    "Mastery/growth association (Pearson r)": ("mg_association", "association_players"),
    "Mean player win rate": ("observed_win_rate", "observed_player_count"),
    "LP/game above tier": ("climbing_efficiency", "observed_player_count"),
    "Expert player share": ("expert_player_share", "mastery_player_count"),
    "Active play rate": ("active_play_rate", "active_pool_player_count"),
    "Mean mastery (at least 15K)": ("mean_mastery_15k", "mastery_players_15k"),
    "Median mastery (at least 15K)": ("median_mastery_15k", "mastery_players_15k"),
    "Mean current primary-player rank score": ("avg_current_rank_score", "primary_player_count"),
    "Median current primary-player rank score": ("median_current_rank_score", "primary_player_count"),
    "Mean estimated ranked mastery share": ("mean_ranked_share", "ranked_share_players"),
    "Mean conditional active-pool overlap": ("conditional_overlap", "overlap_pairs"),
}
available = {label: pair for label, pair in metrics.items() if pair[0] in table and pair[1] in table}
section("Rankings", "Compare champions by one measure")
control = st.columns([2, 1, 1])
chosen = control[0].selectbox("Measure", list(available))
minimum = control[1].number_input("Minimum supporting players or pairs", min_value=1, max_value=1000, value=10)
top_n = control[2].slider("Champions shown", 5, 40, 20)
metric, support = available[chosen]
ranking = table.loc[table[support].fillna(0) >= minimum, ["champion_name", metric, support]].dropna().sort_values(metric, ascending=False).head(top_n)
if ranking.empty:
    st.info("No champions meet this support threshold.")
else:
    fig = px.bar(ranking.sort_values(metric), x=metric, y="champion_name", orientation="h", custom_data=[support])
    fig.update_xaxes(title=chosen, tickformat=".0%" if chosen in {"Expert player share", "Active play rate", "Mean estimated ranked mastery share", "Mean conditional active-pool overlap", "Mean player win rate"} else None)
    fig.update_yaxes(title="")
    st.plotly_chart(fig, width="stretch")
st.caption("The ranked-share measure includes only players with completed ranked observation periods. Pool overlap is a shared-player-weighted conditional probability across retained champion pairs. Rank score combines tier, division and LP; it is a ladder position measure, not money or performance.")

section("Champion comparison", "Mastery preference and rank growth by champion")
minimum_champion_players = st.slider("Minimum historical players per champion", 1, 100, getattr(dashboard_config, "MIN_SUPPORT_PLAYERS", 3), 1)
landscape, x_label = champion_landscape_data(champions, players)
hidden_champions = int(landscape["observed_player_count"].fillna(0).lt(minimum_champion_players).sum())
if hidden_champions:
    show_thin_champions = support_warning(
        f"Insufficient data: {hidden_champions} champion(s) have fewer than "
        f"{minimum_champion_players} historical players and are hidden by default.",
        "cross_champions",
    )
    if not show_thin_champions:
        landscape = landscape.loc[landscape["observed_player_count"].fillna(0) >= minimum_champion_players]
if "mean_commitment" not in champions:
    st.caption("This snapshot combines current primary players' active concentration with an older historical growth estimate. The axes describe different cohorts and time windows.")
if landscape.empty:
    st.info("No champions meet the selected player threshold.")
else:
    y_label = "LP/game above starting-tier baseline" if "climbing_efficiency" in champions else "LP/game above tier baseline (older estimate)"
    champion_display = st.segmented_control("Champion plot", ["2D", "3D with rank score"], default="2D")
    if champion_display == "3D with rank score" and "avg_end_rank_score" in landscape:
        fig = px.scatter_3d(landscape.dropna(subset=["specialization_axis", "outcome", "avg_end_rank_score"]), x="specialization_axis", y="outcome", z="avg_end_rank_score", size="observed_player_count", color="observed_win_rate", hover_name="champion_name", labels={"specialization_axis": x_label, "outcome": y_label, "avg_end_rank_score": "Mean observed ending rank score"})
        st.plotly_chart(fig, width="stretch")
    else:
        st.plotly_chart(champion_efficiency_landscape(landscape, x_label, y_label), width="stretch")
st.caption("Each bubble represents a champion. Size shows observed support and color shows mean player win rate. Population mode pools player–tier summaries, so players observed in multiple tiers contribute once per tier.")

st.markdown("#### Champion mastery share by tier")
box_controls = st.columns(2, gap="small")
box_champions = sorted(champions["champion_name"].dropna().unique())
box_champion = box_controls[0].selectbox("Champion for mastery-share boxes", box_champions, index=box_champions.index("Ahri") if "Ahri" in box_champions else 0)
minimum_box_mastery = box_controls[1].slider("Minimum mastery for player boxes", 15_000, 100_000, 15_000, 5_000)
if player_mastery is None:
    st.info("Player mastery shares need the champion_player_mastery_share extract.")
else:
    box_rows = player_mastery.loc[
        player_mastery["champion_name"].eq(box_champion)
        & player_mastery["champion_points"].ge(minimum_box_mastery)
        & player_mastery["tier"].isin(TIER_ORDER)
    ]
    if box_rows.empty:
        st.info("No players meet the selected champion mastery threshold.")
    else:
        fig = population_box_chart(box_rows, "mastery_share", horizontal=True)
        fig.update_xaxes(title="Champion share of total mastery")
        fig.update_xaxes(tickformat=".0%", range=[0, 1])
        st.plotly_chart(style_figure(fig, height=490), width="stretch")
        st.caption(f"{len(box_rows):,} champion mastery holders at or above {minimum_box_mastery:,} points. Each box summarizes player shares in a tier; share = champion mastery / total mastery. Outlier points are hidden.")

section("Ladder curves", "Where each champion's mastery is concentrated by tier")
if tier_mastery is None:
    st.info("Champion tier mastery curves require the champion_tier_mastery extract.")
else:
    defaults = [name for name in default_curve_champions if name in set(tier_mastery["champion_name"])]
    selected = st.multiselect("Champions on chart", sorted(tier_mastery["champion_name"].unique()), default=defaults)
    threshold = st.slider("Minimum champion mastery", 0, 90_000, 0, 10_000)
    representation = mastery_representation_by_tier(tier_mastery, threshold)
    curves = representation.loc[
        representation["champion_name"].isin(selected)
        & representation["player_count"].ge(minimum)
    ].copy()
    if curves.empty:
        st.info("No champion tiers meet these controls.")
    else:
        fig = px.line(
            curves,
            x="tier",
            y="log2_representation", color="champion_name", markers=True,
            category_orders={"tier": TIER_ORDER},
            custom_data=["tier", "player_count", "champion_tier_share", "sample_tier_share", "representation_ratio"],
        )
        fig.update_traces(hovertemplate="<b>%{fullData.name}</b> · %{customdata[0]}<br>Champion mastery in tier: %{customdata[2]:.1%}<br>Reference mastery in tier: %{customdata[3]:.1%}<br>Representation: %{customdata[4]:.2f}×<br>Mastery holders: %{customdata[1]:,}<extra></extra>")
        fig.add_hline(y=0, line_dash="dot")
        fig.update_xaxes(title="Current tier")
        fig.update_yaxes(title="Mastery representation vs selected denominator (log2)", tickvals=[-2, -1, 0, 1, 2], ticktext=["¼×", "½×", "1×", "2×", "4×"])
        st.plotly_chart(style_figure(fig, height=520), width="stretch")
        st.caption("Each champion's mastery points are distributed across tiers using the selected analysis denominator. A point divides that champion's tier share by the tier's share of all champion mastery. 1× matches the selected denominator; 2× means twice the expected share. The mastery filter applies before both distributions.")

section("One-trick mains", "Where concentrated active mains sit on the ladder")
if tier_mastery is None:
    st.info("One-trick tier comparisons require the champion_tier_mastery extract.")
else:
    otp_names = sorted(tier_mastery["champion_name"].dropna().unique())
    otp_selected = st.multiselect(
        "Champions for one-trick comparison", otp_names,
        default=[name for name in default_curve_champions if name in otp_names],
    )
    otp_controls = st.columns(3, gap="small")
    otp_criterion = otp_controls[0].selectbox("One-trick concentration rule", ["Main share or HHI", "Main share", "HHI"])
    otp_mastery = otp_controls[1].number_input(
        "Minimum total mastery for one-tricks", min_value=0, value=300_000, step=50_000,
    )
    otp_support = otp_controls[2].number_input("Minimum one-tricks per tier", min_value=1, value=getattr(dashboard_config, "MIN_SUPPORT_PLAYERS", 3))
    otp_thresholds = st.columns(2, gap="small")
    otp_share = otp_thresholds[0].slider("Minimum active main share", 0.0, 1.0, 0.8, 0.05)
    otp_hhi = otp_thresholds[1].slider("Minimum active HHI", 0.0, 1.0, 0.65, 0.05)
    otp_view = st.segmented_control("One-trick tier view", ["Tier shares", "Relative representation"], default="Tier shares")
    otp = one_trick_tier_distribution(players, tier_mastery, otp_mastery, otp_share, otp_hhi, otp_criterion)
    otp = otp.loc[otp["champion_name"].isin(otp_selected)].copy()
    st.caption("One-tricks are assigned to their active primary champion. The mastery minimum applies to total account mastery; concentration uses active main share or active HHI. Each player counts once. These are current tiers, not observed final career ranks.")
    st.caption("The baseline is each champion's distribution of all mastery holders across tiers, counted as players at the zero mastery threshold. It includes one-tricks and uses no concentration or account-mastery filter. Both distributions sum to 100% before support filtering.")
    if otp.empty:
        st.info("No active mains meet the selected one-trick filters.")
    else:
        thin = otp["one_trick_total"].lt(otp_support) | (
            otp["one_trick_players"].gt(0) & otp["one_trick_players"].lt(otp_support)
        ) | (otp["champion_players"].gt(0) & otp["champion_players"].lt(otp_support))
        show_thin = False
        if thin.any():
            show_thin = support_warning(
                f"Insufficient data: {int(thin.sum())} one-trick comparison tier(s) have fewer than {otp_support} supporting players. Hidden points leave gaps in the curves.",
                "cross_one_tricks",
            )
        plot_otp = otp.copy()
        if not show_thin:
            plot_otp.loc[thin, ["one_trick_share", "champion_share", "representation_ratio"]] = float("nan")
        if otp_view == "Tier shares":
            plot_otp = plot_otp.melt(
                id_vars=["champion_name", "tier", "one_trick_players", "champion_players", "representation_ratio"],
                value_vars=["one_trick_share", "champion_share"], var_name="Cohort", value_name="Tier share",
            )
            plot_otp["Cohort"] = plot_otp["Cohort"].map({"one_trick_share": "One-trick mains", "champion_share": "All champion mastery holders"})
            fig = px.line(
                plot_otp, x="tier", y="Tier share", color="champion_name", line_dash="Cohort", markers=True,
                category_orders={"tier": TIER_ORDER},
                custom_data=["Cohort", "one_trick_players", "champion_players", "representation_ratio"],
            )
            fig.update_traces(hovertemplate="<b>%{fullData.name}</b> · %{x}<br>%{customdata[0]}: %{y:.1%}<br>One-tricks in tier: %{customdata[1]:,}<br>Champion holders in tier: %{customdata[2]:,}<br>Relative representation: %{customdata[3]:.2f}×<extra></extra>")
            fig.update_yaxes(title="Share of each champion's players", tickformat=".0%", rangemode="tozero")
        else:
            fig = px.line(
                plot_otp, x="tier", y="representation_ratio", color="champion_name", markers=True,
                category_orders={"tier": TIER_ORDER},
                custom_data=["one_trick_players", "champion_players", "one_trick_share", "champion_share"],
            )
            fig.update_traces(hovertemplate="<b>%{fullData.name}</b> · %{x}<br>Relative representation: %{y:.2f}×<br>One-trick tier share: %{customdata[2]:.1%}<br>Champion tier share: %{customdata[3]:.1%}<br>One-tricks in tier: %{customdata[0]:,}<br>Champion holders in tier: %{customdata[1]:,}<extra></extra>")
            fig.add_hline(y=1, line_dash="dot")
            fig.update_yaxes(title="One-trick share / champion baseline share", rangemode="tozero")
        fig.update_xaxes(title="Current tier")
        fig.update_traces(connectgaps=False)
        st.plotly_chart(style_figure(fig, height=520), width="stretch")
        st.caption("Relative representation of 1 means the one-trick tier share matches that champion's general tier share. Zero one-tricks is a measured zero when the champion has sufficient total support; zero baseline holders gives an undefined ratio.")
        with st.expander("One-trick tier counts and shares"):
            st.dataframe(otp, hide_index=True, width="stretch")
