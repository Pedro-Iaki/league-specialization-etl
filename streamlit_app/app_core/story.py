"""The recruiter-facing story; analytical controls live in the separate explorers."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.charts import style_figure
from app_core.audience import (
    RANK_GROUPS, WINDOWS as AUDIENCE_WINDOWS, audience_grid, concentration_cells,
    load_reference as load_audience_reference, maturity_summary, prepare_audience,
)
from app_core.audience_charts import concentration_chart, rank_band_sizes_chart, rank_count_chart, recap_chart
from app_core.config import BLUE, GOLD, MIN_SUPPORT_PLAYERS, PLAYSTYLE_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_manifest, load_optional_dataset
from app_core.experience import experience_display, experience_focus_cells
from app_core.i18n import focus_label, st, story_text, t, terminology_selector
from app_core.story_analysis import (
    CASE_GROUPS, coverage_counts, champion_case_comparison, detectable_gap, growth_uncertainty,
)
from app_core.story_charts import (
    BAND_COLORS, RANK_COLORS, audience_band_chart,
    case_chart, coverage_chart, growth_interval_chart,
)
from app_core.ui import data_source_caption, render_load_error, setup_page

REPOSITORY = "https://github.com/Pedro-Iaki/league-specialization-etl"
STORY_PAGES = [
    ("story/01_pipeline.py", "Pipeline and data"),
    ("story/02_transactions.py", "What transactions would add"),
    ("story/03_tiers.py", "Comparing audiences"),
    ("story/04_growth.py", "Specialization and growth"),
    ("story/05_champions.py", "Champion case studies"),
    ("story/06_findings.py", "Findings and limits"),
]

STORY_CSS = """
<style>
.stApp { background: #080f19; }
h1, h2, h3, .story-heading { font-family: "Segoe UI", system-ui, sans-serif; }
.block-container { max-width: 1200px; padding-top: 3.5rem; padding-bottom: 3rem; }
[data-testid="stSidebar"] { background: #0b1725; }
[data-testid="stSidebarNav"] { max-height: none; }
[data-testid="stSidebarNav"] ul { padding-top: 1rem; }
[data-testid="stNavSectionHeader"] p { color: #e2b344; font-size: .72rem; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.story-progress { color: #e2b344; font-size: .75rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; margin: .5rem 0 1rem; }
[data-testid="stMarkdownContainer"] .story-heading { font-size: clamp(1.85rem, 3.3vw, 2.75rem); font-weight: 700; line-height: 1.16; max-width: 28ch; padding: 0; margin: 0 0 1rem; color: #f5f7fb; letter-spacing: -.025em; }
[data-testid="stMarkdownContainer"] .story-deck { color: #c2cedc; font-size: 1.1rem; line-height: 1.75; max-width: 72ch; margin-bottom: 1rem; }
[data-testid="stMarkdownContainer"] .story-prose { color: #c2cedc; font-size: 1.05rem; line-height: 1.75; max-width: 75ch; margin: .25rem 0 1rem; }
[data-testid="stMarkdownContainer"] .story-meta { color: #a8b9cc; font-size: .85rem; line-height: 1.65; margin: .25rem 0 1rem; }
.story-note { border-left: 3px solid #4ea5d9; padding: .1rem 0 .1rem 1rem; margin: .75rem 0 1.25rem; }
.story-note p { margin: .3rem 0; }
.story-brand { font-size: .8rem; color: #a8b9cc; letter-spacing: .03em; margin-bottom: .4rem; }
[data-testid="stMarkdownContainer"] .story-band-title { color: #e8eef6; font-size: 1rem; font-weight: 650; margin: .5rem 0 0; }
[data-testid="stMarkdownContainer"] .story-band-range { color: #a8b9cc; font-size: .8rem; line-height: 1.5; margin: .15rem 0 .25rem; }
.st-key-story-focus [data-testid="stHorizontalBlock"] { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 1rem; }
.st-key-story-focus [data-testid="stColumn"] { width: 100% !important; min-width: 0 !important; }
.st-key-story-focus [data-testid="stPlotlyChart"] { border: 0; padding: 0; background: transparent; }
.st-key-story-focus [data-testid="stColumn"] > div { border-top: 1px solid #30435a; }
.story-band-swatch { display: inline-block; width: 1.4rem; height: .5rem; margin-right: .35rem; vertical-align: middle; }
.story-focus-legend { display: flex; flex-wrap: wrap; gap: .65rem 1.2rem; margin: .5rem 0; font-size: .85rem; color: #c2cedc; }
.story-focus-swatch { display: inline-block; width: .7rem; height: .7rem; margin-right: .4rem; border-radius: 2px; }
.st-key-story-band-key [data-testid="stHorizontalBlock"] { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr)); gap: .75rem; }
.st-key-story-band-key [data-testid="stColumn"] { width: 100% !important; min-width: 0 !important; }
.st-key-story-methods [data-testid="stMarkdownContainer"] p { max-width: 75ch; line-height: 1.7; }
.st-key-story-footer { margin-top: 1.5rem; }
.st-key-story-footer button { min-height: 3rem; }
.block-container a:focus-visible, .block-container button:focus-visible { outline: 3px solid #e2b344; outline-offset: 3px; }
.story-card { background: #0e1b2b; border: 1px solid #253951; border-radius: 12px; padding: 1.25rem; margin: .3rem 0 1rem; }
.story-card h2 { color: #e8eef6; font-size: 1.3rem; line-height: 1.4; margin: .65rem 0; padding: 0; }
.story-card p { color: #b7c4d4; line-height: 1.7; margin: .45rem 0 0; }
.story-kicker { color: #e2b344; text-transform: uppercase; font-size: .72rem; font-weight: 750; letter-spacing: .12em; }
.story-hypothesis { border-color: #7b6228; }
.story-section { margin: 2rem 0 .3rem; }
.story-status { display: inline-block; color: #b7c4d4; border: 1px solid #385477; border-radius: 20px; padding: .2rem .6rem; margin: 0 0 .5rem .5rem; font-size: .68rem; letter-spacing: .07em; }
.story-flow { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 1.2rem; padding: 0; list-style: none; margin: 1rem 0; }
.story-flow li { position: relative; padding: 1rem .8rem; border: 1px solid #253951; border-radius: 10px; background: #0b1725; }
.story-flow li:not(:last-child)::after { content: "→"; position: absolute; right: -1.12rem; top: 1rem; color: #e2b344; }
.story-flow strong { display: block; color: #e8eef6; }
.story-flow span { display: block; color: #9aabc0; font-size: .8rem; margin-top: .45rem; }
[data-testid="stMetric"] { border-radius: 12px; background: #0e1b2b; border-color: #253951; }
[data-testid="stPlotlyChart"] { background: #0e1b2b; border: 1px solid #253951; border-radius: 12px; padding: .35rem; }
[data-testid="stBaseButton-primary"] { color: #0b1725; background: #e2b344; border-color: #e2b344; font-weight: 700; }
@media (max-width: 900px) { .story-flow { grid-template-columns: repeat(3, 1fr); } .story-flow li:nth-child(3)::after { content: none; } }
@media (max-width: 540px) { .story-flow { grid-template-columns: repeat(2, 1fr); } .story-flow li:nth-child(3)::after { content: "→"; } .story-flow li:nth-child(2n)::after { content: none; } .block-container { padding-left: 1rem; padding-right: 1rem; } [data-testid="stMarkdownContainer"] .story-deck, [data-testid="stMarkdownContainer"] .story-prose { font-size: 1rem; } }
</style>
"""


def pipeline_page() -> None:
    players = story_start(1, "From the Riot API to a privacy-safe data product",
                          "A League of Legends portfolio: collect player snapshots, model their history, and ask whether focusing on fewer champions relates to rank. Start with the engineering, then follow the evidence.")
    resource_links()
    manifest = load_manifest()
    core_profiles = manifest.get("datasets", {}).get("business_players", {}).get("rows")
    metrics = st.columns(4)
    for column, label, value in zip(metrics, ["Player profiles", "Recorded dbt build", "Recorded incremental run", "Serving mode"],
                                    [f"{len(players):,}", "150/150", "2m 39s", "Parquet"], strict=True):
        column.metric(label, value)
    st.caption("Build evidence: 2026-09-30 · 21 models and 129 tests. Historical validation run, before later model changes; not a fresh build result.")
    story_section("Architecture", "Six stages, two state stores")
    steps = [("Collect", "Python, token buckets"), ("Land", "Parquet to Databricks"), ("Bronze", "Raw, deduplicated"),
             ("Silver", "History and current state"), ("Gold", "Analytical marts"), ("Serve", "Anonymous snapshots")]
    items = "".join(f"<li><strong>{i} · {escape(t(title))}</strong><span>{escape(t(copy))}</span></li>"
                    for i, (title, copy) in enumerate(steps, 1))
    st.markdown(f'<ol class="story-flow">{items}</ol>', unsafe_allow_html=True)
    st.caption("State: SQLite keeps the local task ledger; Postgres keeps the shared registry and cursors. Synthetic purchases use a separate sample branch.")
    left, right = st.columns(2, gap="medium")
    with left:
        story_section("Coverage", "A large profile sample, a small follow-up")
        st.plotly_chart(coverage_chart(coverage_counts(players, core_profiles)), width="stretch")
        st.caption("Core context uses the frozen business cohort. Usable recent-week outcomes require at least two ranked games and finite LP/game; the growth chapter uses a separate observed-period extract.")
    with right:
        story_section("Observation dates", "When current profiles were last seen")
        dates = pd.to_datetime(players["snapshot_date"]).dt.normalize().value_counts().sort_index()
        fig = go.Figure(go.Bar(x=dates.index, y=dates.values, marker_color=BLUE,
                              hovertemplate="%{x|%Y-%m-%d}<br>Players: %{y:,}<extra></extra>"))
        fig.update_xaxes(title="Latest profile observation", tickformat="%d %b")
        fig.update_yaxes(title="Players")
        st.plotly_chart(style_figure(fig, height=290), width="stretch")
        st.caption("One latest observation per current profile. This is coverage by date, not collection throughput or a count of all historical snapshots.")
    cards = st.columns(3, gap="medium")
    with cards[0]:
        story_card("Tested", "Checks at each boundary", "Extraction tests, dbt contracts and reconciliation, anonymous export contracts, and dashboard checks.")
    with cards[1]:
        story_card("What broke", "Messy data shaped the design", "Unexpected champion IDs, single-champion mastery profiles, and rank counter resets became explicit modeling cases.")
    with cards[2]:
        story_card("Open gaps", "Measured claims need measurements", "Collection throughput has not been benchmarked. Recovery still requires an operator; the app serves a manually exported snapshot.")
    left, right = st.columns(2, gap="medium")
    with left:
        story_card("Design decisions", "Snapshots made breadth affordable", "Snapshots reach more players per API request, at the cost of noisier activity estimates. Separate stores own separate jobs; player identifiers stay out of serving files.")
    with right:
        story_card("Request economics", "1 + 1/205 ≈ 1.005 requests per new player", "One full ranked page shared across 205 players, then one mastery request each. Refreshing a known player needs two requests. These are request-cost estimates, not measured throughput.")
    story_footer(1)


def transactions_page() -> None:
    story_start(2, "What would transaction data add?",
                "Riot purchase history is unavailable to this project. This chapter explains the business questions a transaction feed could unlock, and the synthetic branch built to demonstrate the reporting flow.")
    st.info("Illustrative only. Purchases and spending patterns are synthetic; player traits come from real profiles. No spending finding is claimed about real customers.")
    for column, kicker, title, body in zip(st.columns(3, gap="medium"), ["Question 1", "Question 2", "Question 3"],
        ["Who pays?", "What do they buy?", "Who uses discounts?"], [
            "Purchaser share and cash per purchaser by tier, role and playstyle. This would inform which audiences to approach first.",
            "Champions versus cosmetics, compared with champion-pool concentration. This would inform the content roadmap.",
            "Discount usage and depth by audience. A real feed could describe usage; an experiment would still be needed to measure promotional lift.",
        ], strict=True):
        with column:
            story_card(kicker, title, body)
    story_section("Ready to ingest", "An implemented reporting contract")
    left, right = st.columns(2, gap="medium")
    with left:
        story_card("The flow", "Real profiles + synthetic transactions → player spending", "A seeded generator supplies fictional events over a frozen real cohort. Bronze transactions, Silver facts and the Gold spending mart turn those inputs into one row per scenario player.")
        st.markdown("A real feed would need an adapter to the raw contract and validated identifiers, currencies and reference tables. The downstream reporting contract is already implemented.")
    with right:
        story_card("Input contract", "What a real feed must supply", "Private player linkage, event and product keys, region, currency, original price, amounts spent and USD value, timestamp, and scenario provenance.")
        st.code("transaction_id · player_id (private) · product_id\nregion_at_purchase · currency_id · original_price\namount_spent · amount_usd · occurred_at · scenario_id", language=None)
        st.caption("Reconciliation checks cash totals, player grain and currency separation. Player, event and product identifiers are excluded from the public business export.")
    story_card("Portfolio value", "Business questions with a working data path", "The sample demonstrates cohort selection, reproducible generation, transaction modeling and tested reporting. It does not validate a relationship between playstyle and real spending.")
    story_footer(2, "business.py", "Business sample explorer")


def tiers_page() -> None:
    terminology_selector()
    players = story_start(
        3,
        story_text("Rank differences need activity context.", "Tier differences need mastery context."),
        story_text(
            "How concentrated are character interests at different ranks and activity levels? Compare the same people among active characters and across their whole history, then locate those audiences on one consistent map.",
            "How does champion concentration differ across tiers and lifetime mastery? Compare the same players within their recent pool and whole history, using fixed mastery bands.",
        ),
    )
    try:
        reference = load_audience_reference()
        banded = prepare_audience(players, reference)
    except DashboardDataError as error:
        st.info(
            "This audience comparison is unavailable for the current snapshot. A matching frozen audience reference and active-pool concentration fields are required."
        )
        with st.expander("Snapshot details"):
            st.code(str(error), language=None)
        story_footer(3, "pages/1_Overall_Analysis.py", "Population explorer")
        return

    cells = concentration_cells(banded)
    n = len(banded)
    missing_recent = int((~players.recent_playstyle.isin(PLAYSTYLE_ORDER)).sum())
    zero_pool = int(
        (players.recent_playstyle.isin(PLAYSTYLE_ORDER) & players.active_pool_lifetime_mastery_points.eq(0)).sum()
    )
    story_prose(
        t(
            "Collected sample · {p0} paired profiles · Same people in both views · Equal weight per profile",
            p0=f"{n:,}",
        ),
        css="story-meta",
    )
    story_prose(
        t(
            "Of {p0} available profiles, {p1} have no Recent classification and {p2} have zero accumulated points in their active pool. They are outside this comparison; missing context is not zero activity.",
            p0=f"{len(players):,}",
            p1=f"{missing_recent:,}",
            p2=f"{zero_pool:,}",
        ),
        css="story-meta",
    )

    story_section("01 · Audience size", "See how much of the sample each group represents")
    story_prose(
        story_text(
            "The five activity bands run from lower to higher accumulated activity. Their boundaries are fixed across this chapter and its two concentration views. Rank counts describe this collected sample, not the size of the market.",
            "Five pooled lifetime-mastery bands use fixed boundaries across both concentration views. Tier counts describe the collected sample, not the ranked population.",
        )
    )
    left, right = st.columns(2, gap="medium")
    with left:
        story_prose(story_text("Profiles by rank group", "Players by tier group"), css="story-band-title")
        st.plotly_chart(
            rank_count_chart(banded),
            key="story-audience-rank-counts",
            width="stretch",
            config={"displayModeBar": False},
        )
    with right:
        story_prose(
            story_text("Profiles within activity bands", "Players within mastery bands"), css="story-band-title"
        )
        st.plotly_chart(
            rank_band_sizes_chart(cells),
            key="story-audience-cell-counts",
            width="stretch",
            config={"displayModeBar": False},
        )

    story_section("02 · Concentration", "Compare active interests with whole history")
    story_prose(
        story_text(
            "Leading-character share is the leading character's accumulated activity score divided by the total across the characters being considered. One view includes the full active pool; the other includes the whole history. Neither ratio measures the share of recent matches played.",
            "Leading-champion share divides the highest lifetime champion mastery by total mastery in the selected pool. The recent-pool and lifetime views use accumulated points, not recent mastery gains or observed match shares.",
        )
    )
    with st.container(key="story-band-key"):
        ranges = banded.groupby("activity_band").lifetime_mastery_points.agg(["min", "max"])
        for band, column in enumerate(st.columns(5, gap="small"), 1):
            with column:
                story_prose(story_text("Activity band {p0}", "Mastery band {p0}", p0=band), css="story-band-title")
                if band in ranges.index:
                    low, high = ranges.loc[band, ["min", "max"]]
                    story_prose(t("{p0}–{p1} points", p0=f"{low:,.0f}", p1=f"{high:,.0f}"), css="story-band-range")
                    story_prose(
                        t("≈ {p0}–{p1} hour-equivalents", p0=f"{low / 1200:,.0f}", p1=f"{high / 1200:,.0f}"),
                        css="story-band-range",
                    )
                else:
                    story_prose("No profiles", css="story-band-range")
    st.caption(
        "Hour-equivalents assume 600 points per match and 30 minutes per match: score / 1,200. They are illustrative, not observed hours, account age or time needed to reach a rank."
    )

    bands_on_x = st.toggle(
        story_text("Activity bands on the horizontal axis", "Mastery bands on the horizontal axis"),
        value=True,
        key="story_focus_bands_on_x",
    )
    quartiles = st.toggle("Show the middle 50% of profiles", key="story_concentration_quartiles")
    labels = (
        RANK_GROUPS
        if bands_on_x
        else [story_text("Activity band {p0}", "Mastery band {p0}", p0=b) for b in range(1, 6)]
    )
    colors = RANK_COLORS if bands_on_x else BAND_COLORS
    legend = "".join(
        f"<span>{story_line_swatch(color, i)}{escape(t(label))}</span>"
        for i, (label, color) in enumerate(zip(labels, colors, strict=True))
    )
    st.markdown(f'<div class="story-focus-legend">{legend}</div>', unsafe_allow_html=True)
    st.caption(
        "Lines show medians. Optional whiskers span the middle 50% of profiles; they are distribution ranges, not confidence intervals. Both panels use the same 0–100% scale."
    )
    with st.container(key="story-focus"):
        for column, (window, label) in zip(st.columns(2, gap="medium"), AUDIENCE_WINDOWS.items(), strict=True):
            with column:
                story_prose(
                    story_text(
                        label,
                        "Within the recent champion pool" if window == "active_pool_lifetime" else "Whole history",
                    ),
                    css="story-band-title",
                )
                st.plotly_chart(
                    concentration_chart(cells.loc[cells.window.eq(window)], bands_on_x=bands_on_x, quartiles=quartiles),
                    key=f"story-concentration-{window}",
                    width="stretch",
                    config={"displayModeBar": False},
                )
    mature = int(banded.days_tracked.ge(30).sum())
    story_prose(
        t(
            "Active membership is inferred. {p0} profiles use the mature 60-day/gain rule; the other {p1} use the short-history 30-day recency rule. Accumulated weighting does not remove this difference in pool selection.",
            p0=f"{mature:,}",
            p1=f"{n - mature:,}",
        ),
        css="story-meta",
    )

    story_section("What this shows", "Read the differences within their context")
    if {1, 5}.issubset(set(banded.activity_band)):
        medians = banded.groupby("activity_band")[["active_pool_lifetime_top1_share", "lifetime_top1_share"]].median()
        story_prose(
            t(
                "From activity band 1 to band 5, median leading share changes from {p0} to {p1} among active characters, and from {p2} to {p3} across whole history.",
                p0=f"{medians.loc[1].iloc[0]:.1%}",
                p1=f"{medians.loc[5].iloc[0]:.1%}",
                p2=f"{medians.loc[1].iloc[1]:.1%}",
                p3=f"{medians.loc[5].iloc[1]:.1%}",
            )
        )
    comparison = (
        cells.loc[cells.window.eq("active_pool_lifetime") & cells.n.ge(MIN_SUPPORT_PLAYERS)]
        .pivot(
            index="activity_band",
            columns="rank_group",
            values="median",
        )
        .reindex(columns=RANK_GROUPS)
    )
    supported = comparison.dropna(subset=["Diamond+", "Gold-Platinum"])
    if not supported.empty:
        higher = int(supported["Diamond+"].gt(supported["Gold-Platinum"]).sum())
        story_prose(
            t(
                "Diamond+ has a higher median than Gold–Platinum in {p0} of {p1} supported activity bands. The rank ordering is not a universal staircase; inspect each band and its sample size.",
                p0=higher,
                p1=len(supported),
            )
        )
    story_prose(
        "These audience differences can frame content, discovery and onboarding questions. They do not show that specialization caused a faster climb; engagement or purchase data would be needed to evaluate a commercial hypothesis.",
        css="story-prose story-note",
    )

    story_section("03 · The audience map", "Add rank to the same activity-and-focus grid")
    story_prose(
        "Each tile counts profiles in one activity band and one 10-percentage-point interval of leading share. The four rank panels add up to the same paired audience. These intervals are display bins, not new playstyle labels."
    )
    window_labels = {
        "active_pool_lifetime": story_text("Among active characters", "Within the recent champion pool"),
        "lifetime": t("Whole history"),
    }
    window = st.radio(
        "Audience map view",
        list(AUDIENCE_WINDOWS),
        format_func=window_labels.__getitem__,
        horizontal=True,
        key="story_audience_map_window",
    )
    grids = {w: audience_grid(banded, w) for w in AUDIENCE_WINDOWS}
    grid = grids[window]
    maximum = max(int(g.profiles.max()) for g in grids.values())
    st.plotly_chart(
        recap_chart(grid, maximum=maximum),
        key="story-audience-recap",
        width="stretch",
        config={"displayModeBar": False},
    )
    st.caption(
        "Horizontal axis: leading-character share, 0–100%. Vertical axis: activity band, 1–5. Color shows profile count on the same scale in both views. This is a cross-section, not a path or a market-size estimate."
    )

    with st.expander("Historical focus groups"):
        st.markdown(
            "All four existing Lifetime focus groups remain useful historical context. These shares use the same paired profiles and fixed bands; they do not classify the new active-pool concentration measure."
        )
        historical = experience_focus_cells(banded.rename(columns={"activity_band": "mastery_band"}))
        with st.container(key="story-historical-focus"):
            for row in (PLAYSTYLE_ORDER[:2], PLAYSTYLE_ORDER[2:]):
                for column, style in zip(st.columns(2), row, strict=True):
                    with column:
                        story_prose(focus_label(style), css="story-band-title")
                        st.plotly_chart(
                            audience_band_chart(historical.loc[historical.playstyle.eq(style)], bands_on_x=bands_on_x),
                            key=f"story-history-{style}",
                            width="stretch",
                            config={"displayModeBar": False},
                        )
        st.caption(
            "Historical category proportions have individual 95% Wilson intervals in the table and hover details. Those intervals do not apply to the concentration medians above; panel scales differ here."
        )
        st.dataframe(focus_table(historical), hide_index=True, width="stretch")

    with st.container(key="story-methods"):
        with st.expander("How pool membership affects concentration"):
            st.markdown(
                "Short-history pools include characters last played within 0–30 days. At 30 tracked days, membership instead requires 0–60-day recency and sufficient observed gain. A narrow selected pool can produce high concentration without proving exclusive recent use."
            )
            table = maturity_summary(banded).rename(
                columns={
                    "maturity": "Tracking history",
                    "n": "Profiles",
                    "active_median": "Active-pool median",
                    "history_median": "Whole-history median",
                }
            )
            for field in ("Active-pool median", "Whole-history median"):
                table[field] = table[field].map(lambda x: f"{x:.1%}")
            st.dataframe(table, hide_index=True, width="stretch")
            st.markdown(
                "The existing Recent classifier combines gain-weighted and equal-membership profiles. It is separate from this Lifetime-weighted active-pool comparison. Neither membership nor accumulated points measures a uniform window of recent match frequency."
            )
        with st.expander("How this comparison is calculated"):
            st.markdown(
                "The paired cohort requires both existing classifications, a recognized rank, positive accumulated account and active-pool points, and valid concentration measures. No ranked follow-up, known character type or spending record is required. Each profile has equal weight."
            )
            st.markdown(
                "The five score cuts are frozen for this source snapshot. Equal scores stay together; filtering by rank or changing the chart orientation never recalculates the cuts. Diamond+ includes all apex ranks present, including Grandmaster. No separate apex-rank finding is claimed."
            )
            st.markdown(
                "The leading-character reporting cutoff of 15,000 points belongs to the character chapter. It does not filter this concentration comparison or remove points from the active-pool denominator."
            )
            st.markdown(
                "The historical focus groups use the existing SQL classifications. No new four-class rule, Fan threshold or preferred-subset calculation is introduced. Profiles are latest-known observations, not a live census."
            )
            st.link_button("Metrics and methods", f"{REPOSITORY}/blob/main/docs/reference/metrics-and-methods.md")
        with st.expander("Inspect values and counts"):
            display = cells.copy()
            display["window"] = display.window.map(window_labels)
            for field in ("median", "q1", "q3"):
                display[field] = display[field].map(lambda x: f"{x:.2%}" if pd.notna(x) else "Not shown")
            st.dataframe(
                display.rename(
                    columns={
                        "activity_band": "Activity band",
                        "rank_group": "Rank group",
                        "window": "View",
                        "n": "Profiles",
                        "median": "Median leading share",
                        "q1": "25th percentile",
                        "q3": "75th percentile",
                        "median_hhi": "Median HHI",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            st.dataframe(
                grid.rename(
                    columns={
                        "activity_band": "Activity band",
                        "rank_group": "Rank group",
                        "focus_bin": "Concentration bin (0–9)",
                        "profiles": "Profiles",
                        "n": "Profiles in rank-band cell",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
    story_footer(3, "pages/1_Overall_Analysis.py", "Population explorer")


def story_line_swatch(color: str, index: int) -> str:
    dash = ["none", "7 4", "2 4", "7 4 2 4", "12 4"][index]
    return f'<svg class="story-band-swatch" viewBox="0 0 24 8" aria-hidden="true"><line x1="0" y1="4" x2="24" y2="4" stroke="{color}" stroke-width="3" stroke-dasharray="{dash}"/></svg>'


def focus_table(cells: pd.DataFrame) -> pd.DataFrame:
    """Present counts and intervals without changing canonical classifications or support."""
    display = experience_display(cells, MIN_SUPPORT_PLAYERS)
    display["playstyle"] = display["playstyle"].map(focus_label)
    for field in ["share", "lower", "upper"]:
        display[field] = display[field].map(lambda value: f"{value:.2%}" if pd.notna(value) else "Not shown")
    return display.drop(columns=["omitted", "count_label"]).rename(columns={
        "mastery_band": story_text("Activity band", "Mastery band"), "tier_group": story_text("Rank group", "Tier group"),
        "playstyle": story_text("Character focus", "Playstyle"), "main_role": "Inferred role",
        "n": "Profiles in group", "members": "Profiles in focus group", "share": "Share of profiles",
        "lower": "95% lower", "upper": "95% upper",
    })


def growth_page() -> None:
    story_start(4, "Specialization and rank growth: an unresolved question",
                "League Points (LP) measure ranked progress. Here the outcome is LP gained per game above the player's starting-tier baseline. Zero means matching that baseline, not making no progress.")
    try:
        growth = load_optional_dataset("growth_player_styles")
    except DashboardDataError as error:
        render_load_error(error)
    if growth is None:
        st.info("This snapshot has no observed-period growth extract. The rank explorer still provides the available current-profile comparisons.")
        story_footer(4, "overview.py", "Specialization and rank explorer")
        return
    summary = growth_uncertainty(growth)
    total = int(summary["observations"].sum())
    st.caption(t("{p0} player–tier–playstyle observations · at least one ranked game · observed rank periods. A player can contribute to more than one group.", p0=f"{total:,}"))
    story_section("Estimates", "The observed means and their uncertainty", "95% bootstrap intervals")
    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        st.plotly_chart(growth_interval_chart(summary), width="stretch")
    with right:
        supported = summary.loc[summary["observations"].ge(MIN_SUPPORT_PLAYERS)]
        if supported.empty:
            st.info("There are too few observations for intervals in this snapshot.")
        elif supported["low"].le(0).all() and supported["high"].ge(0).all():
            story_card("What the intervals say", "Every interval includes zero", "This sample does not separate any playstyle mean from its tier baseline. That leaves the size and direction of a possible association unresolved.")
        else:
            story_card("What the intervals say", "Read the estimate with its interval", "An interval excluding zero describes this selected sample. Comparing playstyles requires a direct difference test, and an association would still not establish causation.")
        st.caption("Intervals resample observations 2,000 times with seed 42. They include all four playstyles and use measured variability. Anonymous exports cannot support clustering repeated observations by player; baseline estimation uncertainty is not included.")
    with st.expander("See counts and measured estimates"):
        display = summary.copy()
        display["playstyle"] = display["playstyle"].map({"specialist": "Specialist", "multispecialist": "Multi-specialist", "versatile": "Versatile", "generalist": "Generalist"})
        st.dataframe(display, hide_index=True, width="stretch")
    story_section("Sensitivity", "How big a gap could a sample this size see?", "Measured spread · approximate power")
    sizes = np.array([50, 100, 250, 500, 1_000, 2_000, 4_000])
    gaps = detectable_gap(summary, sizes)
    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        fig = go.Figure(go.Scatter(x=sizes, y=gaps, mode="lines", line={"color": BLUE}, name="Detectable gap"))
        current_size = int(supported["observations"].median()) if not supported.empty else 0
        if current_size:
            fig.add_trace(go.Scatter(x=[current_size], y=detectable_gap(summary, np.array([current_size])),
                                     name="Typical observed group", mode="markers", marker={"color": GOLD, "size": 12}))
        fig.update_xaxes(title="Observations per group")
        fig.update_yaxes(title="Detectable LP/game gap", rangemode="tozero")
        st.plotly_chart(style_figure(fig, height=300), width="stretch")
    with right:
        story_card("Planning calculation", "Smaller differences need larger groups", "The curve uses the pooled within-playstyle sample variance, equal independent groups, a two-sided 5% test and 80% power. It is a normal-approximation planning calculation, not observed statistical power or a causal test.")
        if current_size:
            gap = detectable_gap(summary, np.array([current_size]))[0]
            st.markdown(t("At about {p0} observations per group, the detectable gap is roughly {p1} LP per game.",
                          p0=f"{current_size:,}", p1=f"{gap:.1f}"))
    left, right = st.columns(2, gap="medium")
    with left:
        story_card("Why filters change the picture", "Small cells move easily", "Five roles, eight tiers and four playstyles create 160 possible cells. Splitting a small follow-up sample that far makes estimates sensitive to a handful of observations.")
    with right:
        story_card("What would settle it", "Follow the same players for longer", "Collect more completed weeks, preserve private linkage for player-clustered intervals, and track within-player pool changes. More data alone would still not prove causation.")
    story_card("Business read · hypothesis to test", "Earn the recommendation before building it", "This evidence is too limited to justify a 'specialize to climb' feature. The pipeline provides a way to keep collecting the observations needed to investigate it.", hypothesis=True)
    story_footer(4, "overview.py", "Specialization and rank explorer")


def champions_page() -> None:
    players = story_start(5, "The champion changes the picture",
                          "Selected champion groups illustrate how the tier distribution of highly concentrated players can differ. These are exploratory case studies, chosen after seeing the data; they do not establish a champion-difficulty effect.")
    st.caption("One-trick here means at least 300,000 lifetime mastery points and a recent main-champion share of at least 80% OR recent HHI of at least 0.65. It describes an inferred recent pool, not exclusive play in every match.")
    try:
        comparison = champion_case_comparison(players, load_dataset("champion_tier_mastery"))
    except DashboardDataError as error:
        render_load_error(error)
    for name, champions in CASE_GROUPS.items():
        frame = comparison.loc[comparison["group"].eq(name)]
        mains = frame.loc[frame["series"].eq("One-tricks")]
        count = int(mains["total"].iloc[0])
        story_section(name, " · ".join(champions), "Actual counts · exploratory selection")
        left, right = st.columns([1.2, 1], gap="medium")
        with left:
            st.plotly_chart(case_chart(frame), width="stretch")
        with right:
            st.metric("One-tricks in selected champions", f"{count:,}")
            if count >= MIN_SUPPORT_PLAYERS:
                featured_tier = "IRON" if name == "Case group A" else "Diamond+"
                featured = frame.loc[frame["tier"].eq(featured_tier)].set_index("series")
                st.markdown(t("{p0} of these one-tricks are in {p1}, compared with {p2} of champion-holder records.",
                              p0=f"{featured.loc['One-tricks', 'share']:.0%}", p1=t(featured_tier),
                              p2=f"{featured.loc['Champion holders', 'share']:.0%}"))
            story_card("Read the baseline", "Two comparisons, different questions", "Champion holders show where all mastery holders of these champions sit. The all-champion one-trick line shows where the broader concentrated-player cohort sits. Diamond and Master are pooled as Diamond+.")
    left, right = st.columns(2, gap="medium")
    with left:
        story_card("What this cannot say", "Where players sit is not who climbs", "Low-tier concentration could reflect a beginner audience, selection, or slower climbing. High-tier concentration has similarly competing explanations. These small groups cannot distinguish them.")
    with right:
        story_card("How to firm it up", "Define difficulty independently first", "Choose an external difficulty classification before examining outcomes, compare every sufficiently supported champion, and match on experience. No easy-versus-hard claim is made here.")
    story_card("Business read · hypothesis to test", "Test content needs by champion audience", "Beginner onboarding and advanced practice content may serve different audiences. Validate demand and learning outcomes before turning these descriptive groups into a product decision.", hypothesis=True)
    story_card("Caveat", "Counts are small and baselines overlap", "One-tricks contribute once through their primary champion. Holder counts pool player–champion records, so someone holding several selected champions can contribute several times. Shares are sample-based, with no population correction.")
    story_footer(5, "pages/2_Champion_Explorer.py", "Champion explorer")


def findings_page() -> None:
    story_start(6, "What this project shows, and what it cannot show",
                "The result is a working data product and a disciplined reading of its evidence: some descriptive patterns, an unresolved growth question, and clear next steps.")
    columns = st.columns(3, gap="medium")
    for column, kicker, title, body in zip(columns, ["Finding 1 · Tiers", "Finding 2 · Growth", "Finding 3 · Champions"],
        ["Definitions change the story", "The growth question needs more evidence", "Champion audiences differ"], [
            "Lifetime and recent concentration produce different ladder patterns. A mastery-adjusted ratio and the experience-stratified comparison help expose that distinction. Trust: descriptive, dependent on the pool definition.",
            "The observed-period estimates come from a small selected sample. Bootstrap intervals and the measured-spread sensitivity curve show why modest differences remain hard to resolve. Trust: inconclusive about a general specialization benefit.",
            "Selected one-trick groups have different tier distributions. Post-selection, small cohorts and overlapping holder baselines limit interpretation. Trust: exploratory, not a difficulty or climbing effect.",
        ], strict=True):
        with column:
            story_card(kicker, title, body)
    columns = st.columns(3, gap="medium")
    with columns[0]:
        story_card("What the pipeline demonstrates", "Engineering from collection to delivery", "Rate-limited collection, durable state, layered history models, tested reporting contracts and identifier-free serving. The synthetic transaction branch extends the same project to business reporting.")
    with columns[1]:
        story_card("Limits", "Coverage is not representativeness", "Roughly even tier sampling; limited completed follow-up; inferred recent pools; mastery as an experience proxy; snapshots rather than individual match histories. None of these comparisons identifies a causal effect.")
    with columns[2]:
        story_card("Next", "Measure, follow up, validate", "Benchmark extraction throughput. Collect more completed weeks. Add player-clustered analysis before anonymous export. Prespecify champion comparisons and validate product hypotheses with real outcomes.")
    story_card("About the work", "A portfolio in making data usable", "This project connects Python collection and orchestration, SQL and dbt modeling on Databricks, analytical reasoning and a readable data product. The repository documents the choices, failures and tradeoffs behind it.")
    resource_links(contact=True)
    story_footer(6, "pages/1_Overall_Analysis.py", "Open the data explorers")


def story_start(number: int, title: str, deck: str) -> pd.DataFrame:
    setup_page(STORY_PAGES[number - 1][1], project_name="players-as-customers-pipeline")
    st.markdown(STORY_CSS, unsafe_allow_html=True)
    st.markdown('<div class="story-brand">players-as-customers-pipeline</div>', unsafe_allow_html=True)
    progress = t("The story · {p0} of 6", p0=number) + " · " + t(STORY_PAGES[number - 1][1])
    st.markdown(f'<div class="story-progress">{escape(progress)}</div><h1 class="story-heading">{escape(t(title))}</h1><p class="story-deck">{escape(t(deck))}</p>', unsafe_allow_html=True)
    try:
        players = load_dataset("players", include_all_tiers=number == 3).drop(columns="population_weight", errors="ignore")
    except DashboardDataError as error:
        render_load_error(error)
    data_source_caption(data_freshness([players]))
    if number == 3:
        manifest = load_manifest()
        exported = manifest.get("exported_at_utc")
        exported = pd.Timestamp(exported).strftime("%Y-%m-%d") if exported else t("Not recorded")
        story_prose(t("Profiles as of {p0} · Exported {p1} · Frozen snapshot",
                      p0=data_freshness([players]), p1=exported), css="story-meta")
    return players


def story_prose(message: str, *, css: str = "story-prose") -> None:
    st.markdown(f'<p class="{css}">{escape(t(message))}</p>', unsafe_allow_html=True)


def story_section(kicker: str, title: str, status: str | None = None) -> None:
    badge = f'<span class="story-status">{escape(t(status))}</span>' if status else ""
    st.markdown(f'<div class="story-section"><span class="story-kicker">{escape(t(kicker))}</span>{badge}</div>', unsafe_allow_html=True)
    st.subheader(title)


def story_card(kicker: str, title: str, body: str, *, hypothesis: bool = False) -> None:
    css = "story-card story-hypothesis" if hypothesis else "story-card"
    st.markdown(f'<section class="{css}"><div class="story-kicker">{escape(t(kicker))}</div><h2>{escape(t(title))}</h2><p>{escape(t(body))}</p></section>', unsafe_allow_html=True)


def resource_links(*, contact: bool = False) -> None:
    links = [
        ("Repository", REPOSITORY),
        ("Model reference", f"{REPOSITORY}/blob/main/docs/reference/data-models.md"),
        ("Engineering journey", f"{REPOSITORY}/blob/main/docs/wiki/engineering-decisions.md"),
    ]
    if contact:
        links.append(("Pedro on GitHub", "https://github.com/Pedro-Iaki"))
    for column, (label, url) in zip(st.columns(len(links)), links, strict=True):
        column.link_button(label, url, width="stretch")


def story_footer(number: int, explorer: str | None = None, explorer_label: str = "") -> None:
    with st.container(key="story-footer"):
        st.divider()
        left, right = st.columns([1, 1], gap="medium")
        if number > 1:
            previous, previous_label = STORY_PAGES[number - 2]
            if left.button(t("← Previous · {p0}", p0=t(previous_label)), key=f"story_previous_{number}", width="stretch"):
                st.switch_page(previous)
        else:
            left.link_button("View the repository", REPOSITORY)
        destination, label = STORY_PAGES[number % len(STORY_PAGES)]
        if right.button("Back to the start" if number == 6 else t("Next → {p0}", p0=t(label)),
                        key=f"story_next_{number}", type="primary", width="stretch"):
            st.switch_page(destination)
        if explorer:
            st.page_link(explorer, label=t("Explore this yourself → {p0}", p0=t(explorer_label)))
