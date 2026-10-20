"""The recruiter-facing story; analytical controls live in the separate explorers."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.charts import style_figure
from app_core.audience import (
    RANK_GROUPS, WINDOWS as AUDIENCE_WINDOWS, audience_grid, band_distributions,
    character_type_counts, concentration_cells, historical_mix, label_comparison, leader_states,
    leading_characters, load_reference as load_audience_reference, maturity_summary, overview_grid, prepare_audience,
)
from app_core.audience_charts import (
    character_counts_chart, concentration_chart, distribution_chart, historical_mix_chart,
    overview_chart, rank_band_sizes_chart, rank_count_chart, recap_chart,
)
from app_core.config import BLUE, GOLD, MIN_SUPPORT_PLAYERS, PLAYSTYLE_COLORS, PLAYSTYLE_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_manifest, load_optional_dataset
from app_core.experience import experience_display, experience_focus_cells
from app_core.i18n import focus_label, st, story_text, t, terminology_selector
from app_core.story_analysis import (
    detectable_gap, growth_uncertainty,
)
from app_core.story_charts import (
    BAND_COLORS, RANK_COLORS, audience_band_chart,
    growth_interval_chart,
)
from app_core.ui import data_source_caption, render_load_error, setup_page

REPOSITORY = "https://github.com/Pedro-Iaki/league-specialization-etl"
STORY_PAGES = [
    ("story/01_pipeline.py", "The audience question"),
    ("story/02_audience.py", "Defining an audience"),
    ("story/03_tiers.py", "Comparing audiences"),
    ("story/04_characters.py", "Character interests"),
    ("story/05_transactions.py", "What transactions would add"),
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
    terminology_selector()
    players = story_start(
        1, "Turn behavioral observations into audience context.",
        "A useful audience definition connects what people choose with how active they are and their competitive context. This project builds that view from collected observations, then demonstrates how it could connect to transaction reporting.",
    )
    story_prose(story_text(
        "The source is League of Legends: a game where players choose characters and can compete in ranked matches. Riot's API supplies character activity and rank observations. Purchase history is simulated in a separate branch.",
        "Riot's API supplies champion mastery and solo/duo rank snapshots. The pipeline turns them into historical models and audience comparisons; a separate simulated purchase branch demonstrates business reporting.",
    ))
    manifest = load_manifest()
    try:
        reference = load_audience_reference()
        paired_n = len(prepare_audience(players, reference))
    except DashboardDataError:
        paired_n = None
    scenario = manifest.get("datasets", {}).get("business_players", {})
    scenario_n = scenario.get("rows")
    scenario_date = scenario.get("scenario", {}).get("as_of_date", t("Not recorded"))
    with st.container(key="story-coverage"):
        columns = st.columns(3)
        columns[0].metric("Collected profiles", f"{len(players):,}")
        columns[1].metric("Paired audience profiles", f"{paired_n:,}" if paired_n is not None else t("Unavailable"))
        columns[2].metric("Frozen scenario profiles", f"{scenario_n:,}" if scenario_n is not None else t("Not recorded"))
    story_prose(t(
        "The analytical audience is a subset of the collected profiles. The transaction scenario is a separate cohort frozen on {p0}; these three counts are not a nested funnel.", p0=scenario_date,
    ), css="story-meta")

    story_section("01 · The useful output", "An audience you can describe and inspect")
    for column, kicker, title, body in zip(st.columns(3, gap="medium"),
        ["Activity and focus", "Rank and character interests", "Transaction integration"],
        ["Define whom you mean", "Add context and content", "Connect definitions to outcomes"],
        ["Compare accumulated interests within active characters and across whole history. Keep the same people and activity boundaries throughout.",
         "Show where groups sit in the collected sample, which characters lead their active pools and which interests overlap.",
         "A simulated purchase feed demonstrates the reporting contract. Real purchasing data would be needed to investigate customer value or demand."], strict=True):
        with column:
            story_card(kicker, title, body)

    story_section("02 · From source to audience", "A traceable path through the pipeline")
    steps = [("Collect", "Riot API observations"), ("Retain history", "Dated snapshots"),
             ("Model", "Checked analytical marts"), ("Define audiences", "Activity, focus and rank"),
             ("Connect outcomes", "Separate simulated purchases"), ("Deliver", "Local anonymous snapshots")]
    items = "".join(f"<li><strong>{i} · {escape(t(title))}</strong><span>{escape(t(copy))}</span></li>"
                    for i, (title, copy) in enumerate(steps, 1))
    st.markdown(f'<ol class="story-flow">{items}</ol>', unsafe_allow_html=True)
    story_prose("Python handles collection and orchestration; SQL and dbt model history on Databricks; Streamlit presents manually exported local snapshots. SQLite owns the local task ledger, while Postgres holds shared collection coordination.")

    story_section("03 · Read the dates", "Profiles are observations, not a live census")
    dates = pd.to_datetime(players.snapshot_date).dt.normalize().value_counts().sort_index()
    fig = go.Figure(go.Bar(x=dates.index.tolist(), y=dates.tolist(), marker_color=BLUE,
                          hovertemplate="%{x|%Y-%m-%d}<br>Players: %{y:,}<extra></extra>"))
    fig.update_xaxes(title="Latest profile observation", tickformat="%d %b")
    fig.update_yaxes(title="Profiles")
    st.plotly_chart(style_figure(fig, height=260), key="story-observation-dates", width="stretch",
                    config={"displayModeBar": False})
    st.caption("One latest observation per collected profile. Observation dates differ across people; this chart is not collection throughput or a count of all historical snapshots.")
    with st.expander("Engineering evidence and boundaries"):
        st.markdown("Checks cover extraction, model contracts and reconciliation, anonymous exports and dashboard behavior. Historical build evidence records 150 successful nodes on September 30, 2026: 21 models and 129 tests. It is not a fresh build result for this snapshot.")
        st.markdown("Snapshot collection reaches more people per request, at the cost of inferred activity rather than individual match histories. Request-cost estimates and dated validation are documented in the repository; collection throughput has not been benchmarked.")
        st.markdown("The dashboard reads local files. Refreshing data is a manual operation; recovery still requires an operator. Player and interval identifiers are excluded from public serving extracts.")
        resource_links()
    story_prose("First define activity and character focus for the same people.", css="story-prose story-note")
    story_footer(1)


def audience_page() -> None:
    terminology_selector()
    players = story_start(
        2, "Active interests and whole history describe different things.",
        "An old favorite can remain prominent in a person's history after leaving their active pool. Compare accumulated character concentration within active characters and across whole history, using the same people and activity bands.",
    )
    banded = story_audience(players, 2)
    if banded is None:
        return
    story_cohort_note(players, banded)
    story_section("01 · Two views of interest", "Keep the people fixed; change the denominator")
    story_prose(story_text(
        "Leading-character share divides the leading character's accumulated activity score by the total across the characters being considered. The active-pool view filters membership, then uses accumulated scores; it does not measure recent match frequency.",
        "Leading-champion share divides the highest lifetime mastery by total mastery in the selected pool. The recent-pool view uses existing active membership and lifetime points, not recent gains or ranked-match observations.",
    ))
    with st.expander("A small example of the two denominators"):
        st.markdown("Illustration only: an inactive character has 100,000 points; three active characters have 60,000, 30,000 and 10,000. Whole-history leading share is 100,000 / 200,000 = 50%. Among active characters it is 60,000 / 100,000 = 60%. The leader and denominator can both change.")
        st.caption("The active-pool share can also be lower than the whole-history share. Filtering characters does not guarantee a higher concentration when the historical leader is outside the active pool.")
    story_band_key(banded)
    summary = band_distributions(banded)
    with st.container(key="story-focus"):
        for column, window in zip(st.columns(2, gap="medium"), AUDIENCE_WINDOWS, strict=True):
            with column:
                story_prose(story_window_label(window), css="story-band-title")
                st.plotly_chart(distribution_chart(summary.loc[summary.window.eq(window)]),
                                key=f"story-distribution-{window}", width="stretch", config={"displayModeBar": False})
    st.caption("Boxes span the middle 50% of profiles; the line and label mark the median. Whiskers span the 10th–90th percentiles. These are distributions, not confidence intervals; both panels use the same 0–100% scale.")
    medians = banded[["active_pool_lifetime_top1_share", "lifetime_top1_share"]].median()
    story_prose(t("Across this paired audience, median leading share is {p0} among active characters and {p1} across whole history. The views describe different scopes of accumulated interest, not a measured change over time.",
                  p0=f"{medians.iloc[0]:.1%}", p1=f"{medians.iloc[1]:.1%}"))
    story_membership_note(banded)

    story_section("02 · Historical context", "Keep the complete mix of focus groups")
    story_prose("The four existing Lifetime groups summarize historical concentration. They complement the continuous shares above; they do not classify the new active-pool measure or give exact counts of preferred characters.")
    legend = "".join(f'<span><i class="story-focus-swatch" style="background:{PLAYSTYLE_COLORS[s]}"></i>{escape(focus_label(s))}</span>' for s in PLAYSTYLE_ORDER)
    st.markdown(f'<div class="story-focus-legend">{legend}</div>', unsafe_allow_html=True)
    mix = historical_mix(banded)
    st.plotly_chart(historical_mix_chart(mix), key="story-historical-mix", width="stretch", config={"displayModeBar": False})
    with st.expander("How the existing labels differ"):
        st.markdown("Rows use the existing Lifetime classification; columns use the existing Recent classification. The Recent classifier combines gain weights with equal-membership weights and maturity-dependent membership. This table compares definitions for the same people; it does not show switching between playstyles.")
        comparison = label_comparison(banded)
        comparison.index = comparison.index.map(focus_label)
        comparison.columns = comparison.columns.map(focus_label)
        comparison.index.name = t("Whole history")
        comparison.columns.name = t("Existing Recent classification")
        st.dataframe(comparison, width="stretch")
        st.caption(t("Counts sum to {p0} paired profiles. No new four-class active-pool rule is introduced.", p0=f"{len(banded):,}"))

    story_section("03 · The audience map", "Locate activity and focus before adding rank")
    story_prose("Each tile counts profiles in a fixed activity band and a 10-percentage-point interval of leading share. These intervals are display bins, not behavior labels. The next chapter splits this same grid by rank.")
    grids = {window: overview_grid(banded, window) for window in AUDIENCE_WINDOWS}
    maximum = max(int(grid.profiles.max()) for grid in grids.values())
    with st.container(key="story-audience-overview"):
        for column, window in zip(st.columns(2, gap="medium"), AUDIENCE_WINDOWS, strict=True):
            with column:
                story_prose(story_window_label(window), css="story-band-title")
                st.plotly_chart(overview_chart(grids[window], maximum=maximum), key=f"story-overview-{window}",
                                width="stretch", config={"displayModeBar": False})
    st.caption("Color shows profile count on one scale across both views. The five bands and ten focus bins stay fixed in later chapters. This is a cross-section of the collected sample, not a market-size estimate or a path through time.")
    with st.expander("Inspect distributions, counts and membership"):
        display = summary.copy()
        display["window"] = display.window.map(story_window_label)
        st.dataframe(display.rename(columns={"window": "View", "activity_band": "Activity band", "n": "Profiles",
                     "p10": "10th percentile", "q1": "25th percentile", "median": "Median leading share",
                     "q3": "75th percentile", "p90": "90th percentile", "median_hhi": "Median HHI"}), hide_index=True, width="stretch")
        for window, grid in grids.items():
            st.markdown(story_window_label(window))
            st.dataframe(grid.rename(columns={"activity_band": "Activity band", "focus_bin": "Concentration bin (0–9)",
                         "profiles": "Profiles"}), hide_index=True, width="stretch")
        st.dataframe(maturity_summary(banded).rename(columns={"maturity": "Tracking history", "n": "Profiles",
                     "active_median": "Active-pool median", "history_median": "Whole-history median"}),
                     hide_index=True, width="stretch")
        st.markdown("At 30 tracked days, membership changes from 0–30-day recency to the existing 0–60-day recency and gain rule. The two scopes are not a uniform recent-play window. Concentration alone does not establish loyalty or exclusive use.")
        st.link_button("Metrics and methods", f"{REPOSITORY}/blob/main/docs/reference/metrics-and-methods.md")
    story_prose("Rank adds a layer without changing the people or activity cuts.", css="story-prose story-note")
    story_footer(2, "pages/1_Overall_Analysis.py", "Population explorer")


def story_audience(players: pd.DataFrame, number: int) -> pd.DataFrame | None:
    try:
        if number == 4:
            fields = {"active_pool_lifetime_primary_champion_key", "active_pool_lifetime_primary_champion_name",
                      "active_pool_lifetime_primary_champion_points"}
            if not fields.issubset(players.columns):
                raise DashboardDataError("Character reporting requires the active-pool leader fields")
        return prepare_audience(players, load_audience_reference())
    except DashboardDataError as error:
        st.info("This audience comparison is unavailable for the current snapshot. A matching frozen audience reference and active-pool concentration fields are required.")
        with st.expander("Snapshot details"):
            st.code(str(error), language=None)
        story_footer(number, "pages/1_Overall_Analysis.py", "Population explorer")
        return None


def story_cohort_note(players: pd.DataFrame, banded: pd.DataFrame) -> None:
    story_prose(t("Collected sample · {p0} paired profiles · Same people in both views · Equal weight per profile",
                  p0=f"{len(banded):,}"), css="story-meta")
    missing = int((~players.recent_playstyle.isin(PLAYSTYLE_ORDER)).sum())
    zero = int((players.recent_playstyle.isin(PLAYSTYLE_ORDER) & players.active_pool_lifetime_mastery_points.eq(0)).sum())
    story_prose(t("Of {p0} available profiles, {p1} have no Recent classification and {p2} have zero accumulated points in their active pool. They are outside this comparison; missing context is not zero activity.",
                  p0=f"{len(players):,}", p1=f"{missing:,}", p2=f"{zero:,}"), css="story-meta")


def story_window_label(window: str) -> str:
    return story_text("Among active characters", "Within the recent champion pool") if window == "active_pool_lifetime" else t("Whole history")


def story_membership_note(banded: pd.DataFrame) -> None:
    mature = int(banded.days_tracked.ge(30).sum())
    story_prose(t("Active membership is inferred. {p0} profiles use the mature 60-day/gain rule; the other {p1} use the short-history 30-day recency rule. Accumulated weighting does not remove this difference in pool selection.",
                  p0=f"{mature:,}", p1=f"{len(banded) - mature:,}"), css="story-meta")


def story_band_key(banded: pd.DataFrame) -> None:
    with st.container(key="story-band-key"):
        ranges = banded.groupby("activity_band").lifetime_mastery_points.agg(["min", "max"])
        for band, column in enumerate(st.columns(5, gap="small"), 1):
            with column:
                story_prose(story_text("Activity band {p0}", "Mastery band {p0}", p0=band), css="story-band-title")
                if band in ranges.index:
                    low, high = ranges.loc[band, ["min", "max"]]
                    story_prose(t("{p0}–{p1} points", p0=f"{low:,.0f}", p1=f"{high:,.0f}"), css="story-band-range")
                    story_prose(t("≈ {p0}–{p1} hour-equivalents", p0=f"{low / 1200:,.0f}", p1=f"{high / 1200:,.0f}"), css="story-band-range")
                else:
                    story_prose("No profiles", css="story-band-range")
    st.caption("Hour-equivalents assume 600 points per match and 30 minutes per match: score / 1,200. They are illustrative, not observed hours, account age or time needed to reach a rank.")


def transactions_page() -> None:
    story_start(5, "What would transaction data add?",
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
    story_footer(5, "business.py", "Business sample explorer")


def characters_page() -> None:
    terminology_selector()
    players = story_start(
        4, "Character interests make the audience more specific.",
        "Activity, focus and rank describe the shape of an audience. Character choices add content: inferred character types, leading active characters and shared interests. Each lens answers a different question.",
    )
    banded = story_audience(players, 4)
    if banded is None:
        return
    story_cohort_note(players, banded)
    story_section("01 · Character type", "A separate lens on inferred preferences")
    story_prose(story_text(
        "Types A–E summarize the existing inferred preference for five character-position associations. They are nominal labels, not character archetypes or a ranking of player quality. The type describes the profile, not the leading character's class.",
        "Character type summarizes the profile's inferred lane association: A=Top, B=Jungle, C=Middle, D=Bottom, E=Support. These estimates are not observed match positions and are separate from audience-derived champion archetypes.",
    ))
    types = character_type_counts(banded)
    known = int(types.profiles.sum())
    left, right = st.columns([1.2, 1], gap="medium")
    with left:
        st.plotly_chart(character_counts_chart(types, denominator=known, types=True),
                        key="story-character-types", width="stretch", config={"displayModeBar": False})
    with right:
        story_card("Type and archetype", "Two different definitions",
                   "Character type is an existing inferred position preference. A character archetype would group characters with similar audiences after adjusting for active-pool breadth. A–E are reserved for types; they are not cluster names.")
    st.caption(t("Type shares use {p0} profiles with an inferred type; {p1} without one are excluded from this chart only and retained in the audience reference.",
                 p0=f"{known:,}", p1=f"{len(banded) - known:,}"))
    with st.expander("How character type is inferred"):
        st.markdown("A=Top · B=Jungle · C=Middle · D=Bottom · E=Support. These associations come from the existing profile model. Their weights have not been recomputed using the new accumulated active-pool weights; they do not measure the share of matches played in each position.")
        st.dataframe(types.rename(columns={"character_type": "Character type", "profiles": "Profiles"}), hide_index=True, width="stretch")

    story_section("02 · Leading active characters", "Describe content interests with a clear reporting cutoff")
    story_prose(story_text(
        "The leader has the most accumulated points among the model's active characters. Require at least 15,000 points for character reporting, after computing concentration. Lower-point characters remain in the pool denominator, and nobody is moved to a different activity band.",
        "Select the highest-lifetime-mastery champion within the full existing recent pool, then require at least 15,000 points for leader reporting. This is separate from the log-gap preferred subset and the one-trick rule; it does not use equal recent weights to infer a favorite.",
    ))
    states = leader_states(banded)
    qualified = int(states.eq("qualified").sum())
    below = int(states.eq("below").sum())
    unavailable = int(states.eq("unavailable").sum())
    columns = st.columns(3)
    columns[0].metric("Qualifying leaders", f"{qualified:,}")
    columns[1].metric("Below reporting cutoff", f"{below:,}")
    columns[2].metric("Leader unavailable", f"{unavailable:,}")
    leaders = leading_characters(banded)
    featured = leaders.loc[leaders.profiles.ge(MIN_SUPPORT_PLAYERS)].head(10)
    st.plotly_chart(character_counts_chart(featured, denominator=qualified), key="story-leading-characters",
                    width="stretch", config={"displayModeBar": False})
    st.caption(t("Ten largest supported leading-character audiences; shares use {p0} qualifying profiles. Counts of at least three are shown. The leader is an accumulated preference indicator, not a uniquely proven favorite or a recent match-share estimate.", p0=f"{qualified:,}"))
    st.caption("Equal leader scores resolve by character key in the current export. Without tie metadata, a deterministic leader does not establish a unique favorite.")

    story_section("03 · Shared interests", "Overlap has a direction and a denominator")
    story_prose("Two characters can attract many of the same people without being substitutes or forming a validated archetype. This example explains membership overlap; its source is the full classified membership cohort, separate from the paired concentration reference.")
    try:
        pairs = load_dataset("cooccurrence")
    except DashboardDataError as error:
        st.info("Character overlap is unavailable for this snapshot. The paired audience and leading-character views remain available.")
        with st.expander("Overlap snapshot details"):
            st.code(str(error), language=None)
        pairs = None
    pair_fields = {"recent_pool_player_count", "player_count_a", "player_count_b", "prob_b_given_a", "prob_a_given_b", "as_of_date"}
    if pairs is not None and pair_fields.issubset(pairs.columns):
        example = pairs.loc[pairs.champion_name_a.eq("Caitlyn") & pairs.champion_name_b.eq("Jhin")]
        if example.empty:
            example = pairs.loc[pairs.champion_name_a.eq("Jhin") & pairs.champion_name_b.eq("Caitlyn")]
        if not example.empty:
            pair = example.iloc[0]
            shared = int(pair.pair_player_count)
            a, b = pair.champion_name_a, pair.champion_name_b
            union = int(pair.player_count_a + pair.player_count_b - shared)
            counts = [int(pair.player_count_a) - shared, shared, int(pair.player_count_b) - shared]
            labels = [t("{p0} only", p0=a), t("Both characters"), t("{p0} only", p0=b)]
            fig = go.Figure(go.Bar(x=counts, y=labels, orientation="h", marker_color=[BLUE, GOLD, BLUE],
                                  text=[f"{n:,}" for n in counts], textposition="outside", cliponaxis=False,
                                  hovertemplate="%{y}<br>Profiles: %{x:,}<extra></extra>"))
            style_figure(fig, height=230)
            fig.update_layout(margin={"l": 100, "r": 50, "t": 15, "b": 50})
            fig.update_xaxes(title="Profiles", range=[0, max(1, max(counts)) * 1.2], fixedrange=True)
            fig.update_yaxes(autorange="reversed", fixedrange=True)
            st.plotly_chart(fig, key="story-overlap-example", width="stretch", config={"displayModeBar": False})
            story_prose(t("{p0} profiles contain both {p1} and {p2}: {p3} of the {p4} audience and {p5} of the {p6} audience. Their combined distinct reach is {p7} profiles.",
                          p0=f"{shared:,}", p1=a, p2=b, p3=f"{pair.prob_b_given_a:.1%}", p4=a,
                          p5=f"{pair.prob_a_given_b:.1%}", p6=b, p7=f"{union:,}"))
            story_prose(t("Raw lift is {p0}: observed overlap relative to the two overall audience sizes. It does not adjust for differences in how many characters each person has in their pool.", p0=f"{pair.lift:.2f}"))
            st.caption(t("Pair source: {p0} classified membership profiles as of {p1}; the concentration reference has {p2}. This illustrative pair was selected for explanation, not as the strongest association.",
                         p0=f"{int(pair.recent_pool_player_count):,}", p1=pd.Timestamp(pair.as_of_date).strftime("%Y-%m-%d"), p2=f"{len(banded):,}"))
        else:
            st.info("The illustrative pair is not present in this snapshot. No overlap estimate is substituted.")
        if len(pairs):
            st.caption(t("{p0} of {p1} published pairs have raw lift above one. Pool breadth can create widespread overlap; raw lift alone is not a character taxonomy.",
                         p0=f"{int(pairs.lift.gt(1).sum()):,}", p1=f"{len(pairs):,}"))
    elif pairs is not None:
        st.info("This overlap snapshot lacks the audience denominators needed for the example. No overlap estimate is substituted.")
    with st.expander("What a character archetype would require"):
        st.markdown("No validated archetype assignments are available in this snapshot. The declared method conditions character associations on pool breadth, compares the resulting association profiles and checks cluster stability with whole-player resampling and cutoff sensitivities before assigning names.")
        st.markdown("Rank, activity, focus and spending are subsequent comparison dimensions, not clustering features. A leading-character-to-archetype map can be joined by character key after validation; unsupported characters must remain unassigned. The current overlap export does not contain the breadth strata or player-level fitting state needed for those checks.")

    story_section("04 · The audience map", "Add character interests to the same audience reference")
    story_prose("Select an overall reporting state or one of the ten leading-character audiences. The activity bands, focus bins and rank facets stay fixed. This view describes the leading active character; it is not a complete profile of every interest.")
    labels = {"all": t("All paired profiles"), "qualified": t("Qualifying leaders"), "below": t("Below reporting cutoff")}
    if unavailable:
        labels["unavailable"] = t("Leader unavailable")
    for row in featured.itertuples():
        labels[int(row.character_key)] = row.character
    selection = st.selectbox("Audience slice", list(labels), format_func=labels.__getitem__, key="story_character_audience")
    if selection == "all":
        selected = banded
    elif isinstance(selection, str):
        selected = banded.loc[states.eq(selection)]
    else:
        selected = banded.loc[states.eq("qualified") & banded.active_pool_lifetime_primary_champion_key.eq(selection)]
    story_prose(t("Showing {p0} of {p1} reference profiles; {p2} remain outside this selection. Filters select people without recalculating activity bands.",
                  p0=f"{len(selected):,}", p1=f"{len(banded):,}", p2=f"{len(banded) - len(selected):,}"), css="story-meta")
    window_labels = {w: story_window_label(w) for w in AUDIENCE_WINDOWS}
    window = st.radio("Audience map view", list(AUDIENCE_WINDOWS), format_func=window_labels.__getitem__,
                      horizontal=True, key="story_character_map_window")
    grids = {w: audience_grid(selected, w) for w in AUDIENCE_WINDOWS}
    maximum = max(int(audience_grid(banded, w).profiles.max()) for w in AUDIENCE_WINDOWS)
    st.plotly_chart(recap_chart(grids[window], maximum=maximum), key="story-character-recap",
                    width="stretch", config={"displayModeBar": False})
    st.caption("The count scale stays fixed to the complete paired reference across selections and both concentration views. Sparse audiences may appear faint; inspect the count table. Character archetypes have not been assigned.")
    with st.expander("Inspect character coverage and map counts"):
        st.dataframe(pd.DataFrame({"Reporting state": [t("Qualifying leaders"), t("Below reporting cutoff"), t("Leader unavailable")],
                                   "Profiles": [qualified, below, unavailable]}), hide_index=True, width="stretch")
        st.dataframe(featured.rename(columns={"character_key": "Character key", "character": "Character", "profiles": "Profiles"}),
                     hide_index=True, width="stretch")
        st.dataframe(grids[window].rename(columns={"activity_band": "Activity band", "rank_group": "Rank group",
                     "focus_bin": "Concentration bin (0–9)", "profiles": "Profiles", "n": "Profiles in rank-band cell"}),
                     hide_index=True, width="stretch")
    story_prose("These audiences can guide questions about character content and discovery. Purchasing preferences need real transaction outcomes; transactions are the next reporting layer.", css="story-prose story-note")
    story_footer(4, "pages/2_Champion_Explorer.py", "Champion explorer")


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
    banded = story_audience(players, 3)
    if banded is None:
        return
    cells = concentration_cells(banded)
    story_cohort_note(players, banded)

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
    story_band_key(banded)

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
    story_membership_note(banded)

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


def growth_evidence() -> None:
    st.markdown("League Points (LP) measure ranked progress. Here the outcome is LP gained per game above the player's starting-tier baseline. Zero means matching that baseline, not making no progress.")
    try:
        growth = load_optional_dataset("growth_player_styles")
    except DashboardDataError as error:
        render_load_error(error)
    if growth is None:
        st.info("This snapshot has no observed-period growth extract. The rank explorer still provides the available current-profile comparisons.")
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


def findings_page() -> None:
    story_start(6, "What this project shows, and what it cannot show",
                "The result is a working data product and a disciplined reading of its evidence: some descriptive patterns, an unresolved growth question, and clear next steps.")
    columns = st.columns(3, gap="medium")
    for column, kicker, title, body in zip(columns, ["Finding 1 · Tiers", "Finding 2 · Growth", "Finding 3 · Champions"],
        ["Definitions change the story", "The growth question needs more evidence", "Champion audiences differ"], [
            "Active-pool and whole-history concentration describe different scopes of accumulated interest. Fixed activity bands and rank facets keep comparisons on the same profiles. These are descriptive sample results, dependent on pool membership.",
            "The observed-period estimates come from a small selected sample. Bootstrap intervals and the measured-spread sensitivity curve show why modest differences remain hard to resolve. Trust: inconclusive about a general specialization benefit.",
            "Leading active characters and shared membership give audiences content context. Character types and character archetypes are separate definitions; no validated archetypes or purchasing preferences are claimed.",
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
    with st.expander("The separate competitive-growth question"):
        growth_evidence()
    resource_links(contact=True)
    story_footer(6, "pages/1_Overall_Analysis.py", "Open the data explorers")


def story_start(number: int, title: str, deck: str) -> pd.DataFrame:
    setup_page(STORY_PAGES[number - 1][1], project_name="players-as-customers-pipeline")
    st.markdown(STORY_CSS, unsafe_allow_html=True)
    st.markdown('<div class="story-brand">players-as-customers-pipeline</div>', unsafe_allow_html=True)
    progress = t("The story · {p0} of 6", p0=number) + " · " + t(STORY_PAGES[number - 1][1])
    st.markdown(f'<div class="story-progress">{escape(progress)}</div><h1 class="story-heading">{escape(t(title))}</h1><p class="story-deck">{escape(t(deck))}</p>', unsafe_allow_html=True)
    try:
        players = load_dataset("players", include_all_tiers=number in (1, 2, 3, 4)).drop(columns="population_weight", errors="ignore")
    except DashboardDataError as error:
        render_load_error(error)
    data_source_caption(data_freshness([players]))
    if number in (1, 2, 3, 4):
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
