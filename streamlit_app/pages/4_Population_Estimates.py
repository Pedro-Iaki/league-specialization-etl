from __future__ import annotations

import pandas as pd
import plotly.express as px
from app_core.config import PLAYSTYLE_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset
from app_core.i18n import st, t
from app_core.population import category_summary, effective_sample_size, row_weights, weighted_mean, weighted_quantile
from app_core.population_ui import population_controls
from app_core.ui import data_source_caption, hero, render_load_error, section, setup_page

setup_page("Population Estimates")
try:
    players = load_dataset("players", include_all_tiers=True)
except (DashboardDataError, ValueError) as error:
    render_load_error(error)

data_source_caption(data_freshness([players]))
hero(
    "Analyst workspace",
    "Population estimates and sample sensitivity",
    "Compare the collected sample with estimates based on the frozen tier distribution, inspect coverage and download the results. All ten reference tiers are retained here.",
)
try:
    weighted, diagnostics, use_weights = population_controls(players)
except ValueError as error:
    render_load_error(error)

st.sidebar.subheader("Estimate filters")
cohort = weighted.copy()
for column, label in (("region", "Region"), ("queue", "Queue"), ("tier", "Tier"), ("main_role", "Role")):
    if column in cohort:
        options = sorted(players[column].dropna().unique().tolist())
        selected = st.sidebar.multiselect(
            label, options, key=f"estimate_{column}", help="An empty selection includes all available values."
        )
        if selected:
            cohort = cohort.loc[cohort[column].isin(selected)]
minimum_days = st.sidebar.slider("Minimum tracked days", 0, 60, 0, 5, key="estimate_days")
minimum_mastery = st.sidebar.number_input(
    "Minimum total mastery points", min_value=0, value=0, step=10000, key="estimate_mastery"
)
cohort = cohort.loc[
    cohort["days_tracked"].fillna(0).ge(minimum_days) & cohort["total_mastery_points"].ge(minimum_mastery)
].copy()
window = st.segmented_control(
    "Classification window", ["Active (60 days)", "All-time"], default="Active (60 days)", key="estimate_window"
)
prefix = "active" if window == "Active (60 days)" else "alltime"
if st.checkbox("Classified players only", value=False):
    cohort = cohort.loc[cohort[f"{prefix}_playstyle"].isin(PLAYSTYLE_ORDER)].copy()

weights = row_weights(cohort)
left, right = st.columns(2)
left.metric("Observed players in selection", f"{len(cohort):,}")
right.metric("Effective players in selection", f"{effective_sample_size(weights):,.1f}")
st.caption(
    "Effective players measures the information retained after unequal weighting; it is not a population count. Filters keep the original tier weights. Shares and means describe eligible players within this selection; missing metric values are excluded from that metric's denominator."
)

section("Population composition", "Collected shares versus estimated shares")
group = st.selectbox("Compare shares of", ["Playstyle", "Role", "Tier", "Primary champion"])
column = {
    "Playstyle": f"{prefix}_playstyle",
    "Role": "main_role",
    "Tier": "tier",
    "Primary champion": "active_primary_champion_name" if prefix == "active" else "top_champion_name",
}[group]
cohort["category"] = cohort[column].fillna("Unclassified")
shares = category_summary(cohort, "category")
if shares.empty or not shares["players"].sum():
    st.info("No supported players match the selected filters.")
else:
    chart = shares.melt(
        id_vars=["category", "players"],
        value_vars=["sample_share", "estimated_share"],
        var_name="Denominator",
        value_name="share",
    )
    fig = px.bar(
        chart,
        x="category",
        y="share",
        color="Denominator",
        barmode="group",
        custom_data=["players"],
        labels={"players": t("Players"), "category": t("category"), "share": t("Share")},
    )
    fig.update_yaxes(tickformat=".0%", title="Share within selection")
    fig.update_traces(
        hovertemplate="<b>%{x}</b><br>"
        + t("Share")
        + ": %{y:.1%}<br>"
        + t("Players")
        + ": %{customdata[0]:,}<extra></extra>"
    )
    st.plotly_chart(fig, width="stretch")
st.dataframe(shares, hide_index=True, width="stretch")
st.download_button(
    "Download composition estimates", shares.to_csv(index=False), "population_composition_estimates.csv", "text/csv"
)

section("Player metrics", "Means and medians under each denominator")
metrics = [
    "total_mastery_points",
    "rank_score",
    f"{prefix}_hhi",
    f"{prefix}_top1_share",
    "lp_per_game_recent",
    "win_rate_recent",
]
records = []
for metric in metrics:
    if metric not in cohort:
        continue
    values = pd.to_numeric(cohort[metric], errors="coerce")
    valid = values.notna() & weights.notna()
    records.append(
        {
            "metric": metric,
            "observed_players": int(valid.sum()),
            "effective_players": effective_sample_size(weights[valid]),
            "sample_mean": values[valid].mean(),
            "estimated_mean": weighted_mean(values, weights),
            "sample_median": values[valid].median(),
            "estimated_median": weighted_quantile(values, weights),
        }
    )
summary = pd.DataFrame(records)
st.dataframe(summary, hide_index=True, width="stretch")
st.download_button(
    "Download metric estimates", summary.to_csv(index=False), "population_metric_estimates.csv", "text/csv"
)

with st.expander("Analyst export and method"):
    st.caption(
        "The downloadable profiles contain anonymous analytical rows and relative weights. They contain no account identifiers. Use sum(weight × value) / sum(weight) over nonmissing observations. Keep weights attached when filtering; do not average tier means equally or treat weighted mass as a number of real players."
    )
    export = cohort.drop(columns=["category"], errors="ignore").copy()
    export["population_weight"] = weights
    export["reference_version"] = diagnostics["reference_version"].iloc[0]
    export["estimate_mode"] = "frozen_reference" if use_weights else "sample"
    export["calibration_tier"] = "current tier"
    st.download_button(
        "Download anonymous profiles with weights",
        export.to_csv(index=False),
        "population_weighted_profiles.csv",
        "text/csv",
    )
    st.caption(
        "Current player estimates use current tier. Recent outcomes remain conditional on observed players. The Population Analysis page also weights role composition, mastery bands, mastery baselines and active/lifetime comparisons. Its ranked-activity view calibrates the selected observed window by starting tier. Tier box plots remain within-tier descriptions. Champion aggregate marts, overlap summaries and historical outcome aggregates on other pages retain their sample definitions; pooled aggregates require player-level recomputation to become population estimates."
    )
    st.caption(
        "Manual maintenance: edit league_pipeline/seeds/rank_population_reference.csv, update all reference versions and review dates, and keep ten positive shares summing to 1. Additions to the rank system require updating the supported tier list and reviewing model and dashboard tier handling. The recorded date is when the estimate was supplied; its observation date is unknown."
    )
