from __future__ import annotations

import math

import plotly.express as px
from app_core import config as dashboard_config
from app_core.analysis import (
    climber_playstyle_composition,
    mastery_normalized_composition,
    playstyle_composition,
    playstyle_mastery_bands,
    profile_basis,
    ranked_share_by_dimensions,
    role_playstyle_skew,
)
from app_core.charts import (
    composition_view_chart,
    population_box_chart,
    ranked_share_heatmap,
    role_difference_heatmap,
    transition_heatmap,
)
from app_core.config import PLAYSTYLE_COLORS, PLAYSTYLE_LABELS, PLAYSTYLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_optional_dataset
from app_core.experience import experience_bands, experience_cells, experience_chart, experience_display
from app_core.i18n import st
from app_core.metrics import active_alltime_transition
from app_core.population import calibrate_population, direct_standardized_means
from app_core.population_ui import population_controls
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
    players = load_dataset("players", include_all_tiers=True)
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

try:
    raw_players = players.copy()
    players, population_diagnostics, use_population_weights = population_controls(players)
except ValueError as error:
    render_load_error(error)
if st.session_state.get("_dashboard_app_shell"):
    st.page_link("pages/4_Population_Estimates.py", label="Open population estimates and analyst downloads")
else:
    st.caption("Open Population Estimates from the dashboard navigation for comparisons and analyst downloads.")

st.sidebar.subheader("Current player profiles")
minimum_tracked = st.sidebar.slider("Minimum tracked days", 0, 60, 0, 5)
minimum_mastery = st.sidebar.slider("Minimum total mastery points", 0, 1_000_000, 0, 10_000, help="Applies to charts based on cumulative mastery points.")
st.sidebar.caption("Applies to population composition, role differences, and active versus lifetime classifications only.")
minimum_cell_players = st.sidebar.slider("Minimum players per cell", 1, 50, minimum_support, key="ranked_share_support")
cohort = players.loc[players["days_tracked"].fillna(0) >= minimum_tracked].copy()

section("Population structure", "How playstyles are distributed")
controls = st.columns([2, 1.1], gap="small")
basis = controls[0].segmented_control(
    "Mastery window", ["Active (60 days)", "All-time", "Active and observed"], default="Active (60 days)"
)
if basis == "Active and observed":
    st.caption("Active playstyles for players with an available LP delta in the latest completed observation period. Positive, zero, and negative deltas are included.")
group_view = controls[1].selectbox("Compare by", ["Tier", "Role"])
group = "main_role" if group_view == "Role" else "tier"
normalize_mastery = st.toggle(
    "Normalize by mastery baseline", value=False,
    help="Divide each playstyle share by its expected share at the group's median total mastery. The baseline uses all selected players, pooled across tiers and roles.",
)
composition_cohort = cohort.loc[cohort["total_mastery_points"].ge(minimum_mastery)]
# Resolve this view before calling shared helpers: a running Streamlit process may
# still have an imported helper from before the new window label was introduced.
population_cohort = composition_cohort
population_basis = basis
if basis == "Active and observed":
    population_cohort = composition_cohort.loc[composition_cohort["lp_delta_recent"].notna()]
    population_basis = "Active (60 days)"
composition = (
    mastery_normalized_composition(population_cohort, population_basis, group, minimum_mastery)
    if normalize_mastery else playstyle_composition(population_cohort, population_basis, group)
)
composition_players = int(composition["players"].sum())
if composition_players:
    composition["group_players"] = composition.groupby(group, observed=True)["players"].transform("sum")
    composition["confidence_half_width"] = composition.apply(
        lambda row: 1.96 * math.sqrt(row["share"] * (1 - row["share"]) / row["group_players"] + 1.96**2 / (4 * row["group_players"]**2)) / (1 + 1.96**2 / row["group_players"]), axis=1
    )
    if use_population_weights:
        # Raw-count Wilson intervals are inappropriate for unequal weights.
        # Leave them undefined rather than imply a design-based confidence interval.
        composition["confidence_half_width"] = float("nan")
if not composition.empty:
    group_support = composition.groupby(group, observed=True)["players"].transform("sum")
    thin_groups = composition.loc[group_support < minimum_support, group].nunique()
    thin_segments = int(composition["players"].lt(minimum_support).sum())
    if thin_groups or thin_segments:
        show_thin_composition = support_warning(
            f"Insufficient data: {thin_groups} {group_view.lower()} group(s) and {thin_segments} "
            f"playstyle segment(s) fall below {minimum_support} players. Hidden by default; "
            + ("Some ratios are hidden." if normalize_mastery else "Visible share bars may total less than 100%."),
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
    st.plotly_chart(composition_view_chart(composition, group, normalized=normalize_mastery), use_container_width=True)
    with st.expander("Composition support and uncertainty"):
        if use_population_weights:
            st.caption("Weighted shares retain observed counts and effective group size. Confidence intervals are omitted because raw-count Wilson intervals do not account for these weights or uncertainty in the frozen reference.")
        else:
            st.caption("95% Wilson intervals describe sampling uncertainty within the tracked players only; they do not correct selection bias.")
        if normalize_mastery:
            st.caption("Intervals describe raw shares. Baseline estimation uncertainty is not included in the ratios.")
        support_columns = [group, "playstyle", "players", "group_players", "share", "confidence_half_width"]
        support_columns += ["weighted_mass", "effective_group_players"]
        if normalize_mastery:
            support_columns += ["median_mastery", "baseline_share", "relative_share"]
        st.dataframe(composition[support_columns], hide_index=True, width="stretch")
if normalize_mastery:
    st.caption("1 = expected share at this group's median total mastery; above 1 = overrepresented. Expected shares are interpolated between pooled equal-frequency mastery bands. This adjusts for median mastery only; it does not remove all mastery-related differences.")
    st.caption("Players with missing or zero total mastery are excluded. A zero expected share produces an undefined ratio and no bar.")

section("Experience-stratified specialization", "Does the tier pattern survive at similar total mastery?")
st.caption("All-time playstyle only. Five equal-count mastery bands use the full classified sample before profile filters or Master exclusion. Raw shares ignore population weights. Ties are split in snapshot order; band counts differ by at most one. Missing, infinite or negative mastery is excluded.")
experience_controls = st.columns(2, gap="small")
experience_lines = experience_controls[0].toggle("Lines across mastery bands", value=False,
    help="Off: five panels with tier groups on the x-axis. On: one line per tier group across mastery bands.")
include_master = experience_controls[1].toggle("Merge Master into Diamond+", value=True,
    help="Turn off to exclude Master. Mastery bands stay fixed.")
banded_players = experience_bands(raw_players)
stratified_cells = experience_cells(banded_players, include_master)
show_experience_omitted = False
thin_experience = stratified_cells["n"].lt(minimum_cell_players)
if thin_experience.any():
    show_experience_omitted = support_warning(
        f"Insufficient data: {int(thin_experience.sum())} experience cells have fewer than {minimum_cell_players} classified players. Hidden by default; empty cells cannot be shown.",
        "experience_specialization",
    )
experience_plot = experience_display(stratified_cells, minimum_cell_players, show_experience_omitted)
st.plotly_chart(experience_chart(experience_plot, experience_lines), use_container_width=True)
st.caption("Compare tier groups within the same mastery band. Lines or bars that sit apart mean tier differs among similarly experienced players; overlapping intervals are consistent with experience explaining the pattern, but do not prove it.")
st.caption("95% Wilson intervals describe sampling uncertainty within the tracked players only; they do not correct selection bias.")
with st.expander("Experience bands and cell support"):
    band_support = banded_players.groupby("mastery_band").agg(
        n=("total_mastery_points", "size"),
        mastery_min=("total_mastery_points", "min"), mastery_max=("total_mastery_points", "max"),
    ).reset_index()
    st.dataframe(band_support, hide_index=True, width="stretch")
    st.dataframe(experience_plot.drop(columns="count_label"), hide_index=True, width="stretch")
st.caption("Numeric check skipped: statsmodels is not an existing project dependency. The requested ordinal-tier logistic regression would compare the tier coefficient with and without log(total mastery points); a linear tier term alone cannot test a U-shape.")

section("Observed climbers", "Playstyles of players who gained LP")
climber_controls = st.columns(2, gap="small")
climber_basis = climber_controls[0].segmented_control(
    "Climber mastery window", ["Active (60 days)", "All-time"], default="Active (60 days)",
)
climber_group_view = climber_controls[1].selectbox("Compare climbers by", ["Tier", "Role"])
climber_group = "main_role" if climber_group_view == "Role" else "tier"
normalize_climbers = st.toggle(
    "Normalize by mastery baseline", value=False, key="normalize_climbers",
    help="Divide each climber playstyle share by the population's expected share at the climber group's median total mastery.",
)
climbers = climber_playstyle_composition(
    composition_cohort, climber_basis, climber_group,
    normalized=normalize_climbers, minimum_mastery=minimum_mastery,
)
climber_players = int(climbers["players"].sum())
st.caption("Only players with positive net LP and at least one ranked game in the latest completed observation period are included. Each player counts once; playstyle is their selected current mastery profile. Tier and role are current.")
st.caption(f"Classified climbers: {climber_players:,}")
if not climbers.empty:
    climber_support = climbers.groupby(climber_group, observed=True)["players"].transform("sum")
    thin_climbers = climbers["players"].lt(minimum_support) | climber_support.lt(minimum_support)
    if thin_climbers.any():
        show_thin_climbers = support_warning(
            f"Insufficient data: {int(thin_climbers.sum())} climber playstyle segment(s) have fewer than {minimum_support} players. Hidden by default; "
            + ("some ratios are hidden." if normalize_climbers else "visible share bars may total less than 100%."),
            "overall_climbers",
        )
        if not show_thin_climbers:
            climbers = climbers.loc[~thin_climbers]
if climbers.empty:
    st.info("No classified climbers meet the selected filters and support threshold.")
else:
    st.plotly_chart(composition_view_chart(climbers, climber_group, normalized=normalize_climbers), use_container_width=True)
    with st.expander("Climber composition support"):
        st.dataframe(climbers, hide_index=True, width="stretch")
if normalize_climbers:
    st.caption("The baseline uses all selected classified players, including those who did not climb. Each climber group's median total mastery sets its expected playstyle shares. 1 = expected share; above 1 = overrepresented. This adjusts for median mastery only.")
    st.caption("Players with missing or zero total mastery are excluded. A zero expected share produces an undefined ratio and no bar.")

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
    fig = population_box_chart(pool, columns[universe_metric])
    fig.update_yaxes(title=universe_metric)
    fig.update_xaxes(title="Current tier")
    st.plotly_chart(fig, width="stretch")
    st.caption(f"One box per tier shows the player distribution. Window: {universe_basis}. Off picks share excludes the main pick from favoured-pick share. Favoured picks count is the selected core pool; all picks count includes every observed champion.")

section("Cumulative mastery", "Total mastery by tier")
mastery = cohort.loc[cohort["tier"].isin(TIER_ORDER) & cohort["total_mastery_points"].ge(max(1, minimum_mastery))].dropna(subset=["total_mastery_points"])
if not mastery.empty:
    fig = population_box_chart(mastery, "total_mastery_points")
    fig.update_xaxes(title="Current tier")
    fig.update_yaxes(title="All-time total mastery points (log scale)", type="log")
    st.plotly_chart(fig, width="stretch")
    st.caption("Log scaling keeps typical and very high mastery totals visible. Zero values cannot appear on a log axis.")

section("Mastery and playstyle", "How playstyle composition changes with cumulative mastery")
mastery_basis = st.segmented_control("Classification window", ["Active (60 days)", "All-time"], default="All-time", key="mastery_style_basis")
mastery_tier = st.selectbox("Mastery tier", ["All tiers", *TIER_ORDER])
bands = playstyle_mastery_bands(cohort, mastery_basis, minimum_mastery, tier=None if mastery_tier == "All tiers" else mastery_tier)
if not bands.empty:
    bands["Playstyle"] = bands["playstyle"].map(PLAYSTYLE_LABELS)
    fig = px.line(bands, x="mastery", y="share", color="Playstyle", markers=True, color_discrete_map={PLAYSTYLE_LABELS[key]: color for key, color in PLAYSTYLE_COLORS.items()})
    fig.update_xaxes(title="Median total mastery points in band", type="log")
    fig.update_yaxes(title="Share", tickformat=".0%")
    st.plotly_chart(fig, width="stretch")
    st.caption("Players are split into equal-frequency mastery bands; shares sum to 100% within each band before low-support filtering.")

left, right = st.columns(2, gap="large")
with left:
    section("Role association", "Playstyle share relative to the selected denominator")
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
    if use_population_weights:
        ranked_cohort, ranked_diagnostics = calibrate_population(ranked_cohort, tier_column="starting_tier")
        st.caption("Ranked-activity weights use starting-tier shares in this observed window. They estimate the represented observed cohort under the frozen tier distribution; they do not correct the selection of players with completed periods.")
        with st.expander("Ranked-activity weighting diagnostics"):
            st.dataframe(ranked_diagnostics, hide_index=True, width="stretch")
    with st.expander("Ranked-observed means at a common starting-tier mix"):
        standardized_ranked, standardized_tiers = direct_standardized_means(
            ranked_cohort, ["median_ranked_mastery_share"], tier_column="starting_tier",
        )
        st.caption(
            "Direct standardization uses each starting tier's mean among players observed in this window, "
            "then combines supported tier means using the frozen reference. Minimum support is five valid players "
            "per tier. This comparison remains conditional on completed observations; it does not recover "
            "outcomes for unobserved players. Champion selections below control the displayed cells."
        )
        if not standardized_ranked.empty and standardized_ranked["coverage_status"].ne("adequate_coverage").any():
            st.warning("Ranked-observed standardization covers less than 99% of the reference in at least one scope.")
        st.dataframe(standardized_ranked, hide_index=True, width="stretch")
        st.dataframe(standardized_tiers, hide_index=True, width="stretch")
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
    profile = profile_basis(population_cohort, population_basis)
    st.markdown(
        f"""
        **{basis}** is a current mastery profile. Specialist, multi-specialist, versatile, and generalist
        describe mastery-pool shapes, not skill or match tactics. Each label is the closest configured
        profile based on mastery shares, concentration, entropy, and favoured-pool size. There are
        **{profile['playstyle'].isin(PLAYSTYLE_ORDER).sum():,} classified players** in this selection.

        """
    )
