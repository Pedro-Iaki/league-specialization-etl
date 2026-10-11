from __future__ import annotations

import pandas as pd
from app_core.business import (
    AUDIENCE_DIMENSIONS,
    CASH_DISCOUNT_COLUMNS,
    EXPERIENCE_METRICS,
    SYNTHETIC_CAPTION,
    audience_summary,
    cosmetic_summary,
    discount_summary,
    experience_summary,
)
from app_core.business_charts import audience_chart, cosmetic_chart, discount_chart, experience_chart
from app_core.config import MIN_SUPPORT_PLAYERS, ROLE_ORDER, TIER_ORDER
from app_core.data import DashboardDataError, data_freshness, load_optional_dataset
from app_core.i18n import st
from app_core.ui import architecture_flow, data_source_caption, hero, section, setup_page, support_warning


def supported(summary, count_columns, values, minimum, key):
    """Keep counts visible and break lines at omitted groups instead of connecting gaps."""
    if summary.empty:
        return summary
    thin = summary[count_columns].min(axis=1).lt(minimum)
    result = summary.copy()
    if thin.any() and not support_warning(
        f"Insufficient data: {int(thin.sum())} group(s) have fewer than {minimum} supporting players.", key,
    ):
        result.loc[thin, values] = float("nan")
    return result

setup_page("Business Sample")
hero(
    "Data engineering portfolio · business sample",
    "From player profiles to a spending model",
    "Spending data and its patterns are synthetic. Player metrics come from real Riot API snapshots. "
    "This small example shows how a private purchase endpoint could join an existing analytical pipeline.",
)
st.markdown(
    "League of Legends is a competitive game where players choose characters called **champions**. "
    "**Tier** describes competitive rank; player traits summarize experience and preferences. "
    "The real project studies character specialization and rank progression. This opening sample adds "
    "fictional purchases to demonstrate a familiar business reporting use case."
)
st.page_link("overview.py", label="Explore the real gameplay analysis →", icon="📊")
with st.expander("Reading the real player traits"):
    st.markdown(
        "**Role** approximates a player's usual position in the game. **Primary champion** is the leading character "
        "in their recent pool. **Playstyle** describes that pool's concentration, from specialists focused on a few "
        "characters to generalists using a wider mix. A higher **leading-champion share** indicates concentration; "
        "higher **normalized entropy** indicates more even use across the pool. These are inferred profile traits."
    )
with st.expander("How account age and total playtime are estimated"):
    st.markdown(
        "**Total playtime** is approximated by the player's cumulative mastery sum, used as a relative proxy for "
        "time spent playing. We compare relative playtime bands and do not convert points into hours. "
        "**Account age** is simulated time since the first generated purchase, not a verified account creation date."
    )

try:
    players = load_optional_dataset("business_players")
except DashboardDataError as error:
    st.warning(f"The business sample is unavailable: {error}")
    players = None

if players is None:
    st.info("This snapshot has no business sample yet. The real gameplay pages remain available through the link above and sidebar.")
else:
    data_source_caption(data_freshness([players]))
    st.sidebar.caption("Business sample: synthetic purchase history joined to real frozen profiles. USD cash only.")
    recent_buyers = int(players["cash_purchase_count_60d"].gt(0).sum())
    columns = st.columns(3)
    columns[0].metric("Frozen real players", f"{len(players):,}")
    columns[1].metric("Synthetic cash purchasers · 60 days", f"{recent_buyers / len(players):.1%}" if len(players) else "—")
    columns[2].metric("Synthetic cash · 60 days (USD)", f"${players['cash_spent_usd_60d'].astype(float).sum():,.2f}")
    start = pd.to_datetime(players["purchase_window_start"]).min().date()
    end = pd.to_datetime(players["purchase_window_end"]).max().date()
    earliest = pd.to_datetime(players["snapshot_date"]).min().date()
    latest = pd.to_datetime(players["snapshot_date"]).max().date()
    as_of = pd.to_datetime(players["as_of_date"]).max().date()
    st.caption(f"Real profiles with core context frozen as of {as_of}; individual snapshots span {earliest} through {latest}. "
               f"Synthetic recent window: {start} through {end}, inclusive. "
               f"{recent_buyers:,} recent cash purchasers / {len(players):,} sampled players.")

    st.markdown("Choose an audience; each question below uses the same filtered players.")
    controls = st.columns(3)
    tiers = [tier for tier in [*TIER_ORDER, "GRANDMASTER", "CHALLENGER"] if tier in set(players["tier"])]
    tier = controls[0].selectbox("Current tier", ["All tiers", *tiers], key="business_tier")
    role = controls[1].selectbox("Inferred role", ["All roles", *ROLE_ORDER], key="business_role")
    minimum = controls[2].slider("Minimum supporting players", 1, 200, MIN_SUPPORT_PLAYERS, key="business_support")
    filtered = players.copy()
    for column, selected, all_label in (("tier", tier, "All tiers"), ("main_role", role, "All roles")):
        if selected != all_label:
            filtered = filtered.loc[filtered[column] == selected]
    st.caption(f"Filtered real profiles: {len(filtered):,} / {len(players):,}. All cash comparisons use the recent 60-day window.")
    if filtered.empty:
        st.warning("No profiles match this audience. Broaden the filters to view the comparisons.")
    else:
        section("Audience monetization", "How does spending vary across player traits?",
                "Each bubble combines cash purchaser share with USD per cash purchaser. Bubble size is the number of real profiles, including nonpayers.")
        group = st.selectbox("Group audiences by", list(AUDIENCE_DIMENSIONS), key="business_audience_dimension")
        dimension = AUDIENCE_DIMENSIONS[group]
        summary = audience_summary(filtered, dimension)
        plot = supported(summary, ["players", "cash_purchasers"], ["usd_per_purchaser"], minimum, "business_audience")
        plot = plot.dropna(subset=["usd_per_purchaser"])
        if plot.empty:
            st.info("No audience has enough cash purchasers to measure spending per purchaser.")
        else:
            st.plotly_chart(audience_chart(plot, dimension), width="stretch")
        if dimension == "playtime_band":
            st.caption("Playtime bands rank players by estimated total playtime within the selected audience. "
                       "They are relative groups, not measured hours; ties can reduce the number of bands.")
        elif dimension == "tenure_band":
            st.caption("Account age is simulated time since the first fictional purchase. It is not verified account age.")
        zero_groups = int(summary["cash_purchasers"].eq(0).sum())
        st.caption(f"Purchaser share uses every filtered profile; spending per purchaser uses cash purchasers only. "
                   f"{zero_groups} audience(s) have no cash purchasers and an undefined conditional mean.")
        st.caption(SYNTHETIC_CAPTION)
        with st.expander("Audience support and spending"):
            st.dataframe(summary[["audience", "players", "cash_purchasers", "cash_purchaser_share", "usd_per_player", "usd_per_purchaser"]], hide_index=True, width="stretch")

        section("Experience and tenure", "Does spending vary with experience within comparable tenure groups?",
                "Mastery sum is cumulative gameplay experience, not measured hours. Simulated tenure is time since the first fictional purchase, not real account age.")
        metric = st.selectbox("Experience outcome", list(EXPERIENCE_METRICS), format_func=EXPERIENCE_METRICS.get)
        summary = experience_summary(filtered)
        counts = ["players", "cash_purchasers"] if metric == "usd_per_purchaser" else ["players"]
        plot = supported(summary, counts, [metric], minimum, "business_experience")
        if plot.empty or plot[metric].notna().sum() == 0:
            st.info("No experience bands have enough observations for this outcome.")
        else:
            st.plotly_chart(experience_chart(plot, metric), width="stretch")
        st.caption("Points summarize mastery quantile bands, with a separate line for each simulated tenure band. "
                   "USD per player and purchaser share include nonpayers; USD per cash purchaser excludes them. Counts and mastery ranges appear in hover.")
        st.caption(SYNTHETIC_CAPTION)

        section("Content preference", "Does champion-pool concentration relate to cosmetic preference?",
                "Content means champion unlocks and cosmetics. A cosmetic event can use RP, but adds no cash revenue to this chart.")
        axes = {"Leading champion share": "active_top1_share", "Champion-pool diversity (entropy)": "active_normalized_entropy"}
        axis_label = st.selectbox("Champion-pool measure", list(axes))
        dimension = "active_playstyle"
        summary = cosmetic_summary(filtered, axes[axis_label], dimension)
        plot = supported(summary, ["players"], ["mean_cosmetic_share", "q1", "q3"], minimum, "business_cosmetics")
        if plot.empty or plot["mean_cosmetic_share"].notna().sum() == 0:
            st.info("No content-purchase groups have enough observations for this comparison.")
        else:
            st.plotly_chart(cosmetic_chart(plot, dimension, axis_label), width="stretch")
        st.caption("Lines average each player's cosmetic-event share within 10-point pool bands across the full generated history. "
                   "Shading is the middle 50% of player shares, not a confidence interval. Cash top-ups are excluded. "
                   "Each line represents a playstyle. Entropy describes pool diversity, not gameplay regularity.")
        st.caption(SYNTHETIC_CAPTION)

        section("Cash discounts", "Which audiences use cash discounts more often, and how deep are they?",
                "Compare the discounted share of recent fiat events with discount depth conditional on a discounted fiat purchase.")
        if not CASH_DISCOUNT_COLUMNS.issubset(filtered.columns):
            st.info("This snapshot does not include a cash-only discount breakdown.")
        else:
            dimensions = {"Role": "main_role", "Tier": "tier", "Playstyle": "active_playstyle"}
            dimension = dimensions[st.selectbox("Compare cash discounts by", list(dimensions))]
            summary = discount_summary(filtered, dimension)
            plot = supported(summary, ["cash_purchasers", "discounted_cash_purchasers"], ["cash_discount_mean"], minimum, "business_discounts")
            plot = plot.dropna(subset=["cash_discount_mean"])
            if plot.empty:
                st.info("No audiences have enough discounted cash purchasers to measure conditional discount depth.")
            else:
                st.plotly_chart(discount_chart(plot, dimension), width="stretch")
            st.caption("Bubble size counts recent cash purchasers. Discount share is discounted fiat events / all fiat events; "
                       "depth is weighted by discounted events. RP/BE discounts are excluded. Discount usage does not establish promotion effectiveness or price sensitivity.")
            st.caption("Axes fit the observed group means; compare the labeled percentage values.")
            with st.expander("Cash discount support"):
                st.dataframe(summary.drop(columns="discount_fraction_sum"), hide_index=True, width="stretch")
        st.caption(SYNTHETIC_CAPTION)

    with st.expander("How this scenario is generated"):
        st.markdown(
            "Editable weights impose differences by real tier, inferred role, primary champion, playstyle, mastery, "
            "estimated ranked-mastery share and champion-pool shape, plus simulated tenure and customer type. "
            "Seeded residual noise lets groups overlap. The charts display those choices; they do not discover customer behavior.\n\n"
            "Every player receives fictional Blue Essence champion acquisitions and an independently simulated inventory of at least 20. "
            "Real champions with mastery, simulated owned champions and purchase counts represent different things: "
            "rewards, rotations and unused characters can separate them.\n\n"
            "Cash totals sum the hypothetical endpoint's USD amounts for fiat purchases only. RP and BE are game currencies; "
            "their content events contribute to product mix without adding cash revenue."
        )
        metadata = players.attrs.get("business_scenario")
        if metadata:
            st.caption(f"Scenario {metadata['scenario_id']} · generator {metadata['generator_version']} · seed {metadata['generator_seed']} · "
                       f"full generated history {metadata['history_start_at'][:10]} to {metadata['history_end_at'][:10]}.")

section("About the project", "Built by Pedro Iaki")
st.markdown(
    "I’m a software developer moving from mobile games into data engineering. I built this project to practice "
    "reliable API collection, historical warehouse modeling and a usable analytical product. "
    "The real Riot API branch handles rate limits, retries, player refresh and rank/mastery snapshots. "
    "dbt turns those snapshots into player profiles and rank-period analysis.\n\n"
    "The separate business branch freezes a ranked-player cohort, generates historical transactions and builds one spending mart. "
    "Anonymous Parquet exports serve this dashboard without exposing player IDs or warehouse credentials. "
    "[Source code and modeling documentation](https://github.com/Pedro-Iaki/league-specialization-etl)"
)
architecture_flow()
st.page_link("pages/1_Overall_Analysis.py", label="Continue to real player population analysis →", icon="🎮")
