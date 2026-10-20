"""The recruiter-facing story; analytical controls live in the separate explorers."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app_core.charts import style_figure
from app_core.config import BLUE, GOLD, MIN_SUPPORT_PLAYERS, PLAYSTYLE_COLORS, PLAYSTYLE_ORDER
from app_core.data import DashboardDataError, data_freshness, load_dataset, load_manifest, load_optional_dataset
from app_core.experience import (
    ASSUMED_MATCH_MINUTES, ASSUMED_POINTS_PER_MATCH, TIER_GROUP_MAP, experience_bands,
    experience_display, experience_focus_cells, experience_overall, experience_ranges, role_focus_cells,
)
from app_core.i18n import focus_label, st, story_text, t, terminology_selector
from app_core.story_analysis import (
    CASE_GROUPS, coverage_counts, champion_case_comparison, detectable_gap, growth_uncertainty,
)
from app_core.story_charts import (
    BAND_COLORS, audience_band_chart, audience_composition_chart, audience_role_chart,
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
    players = story_start(3, story_text("Character focus separates audiences.", "Playstyles separate audiences."),
        story_text(
            "How do audiences differ in the breadth of their character interests, across competitive rank and accumulated activity? Compare the complete focus mix, then see how its rank profile changes across activity bands.",
            "How does playstyle composition differ across tiers and lifetime mastery? Compare all four playstyles, then see how their tier profiles change across mastery bands.",
        ))
    banded = experience_bands(players)
    eligible = banded.loc[banded["tier"].isin(TIER_GROUP_MAP)]
    cells = experience_focus_cells(banded)
    overall = experience_overall(cells)
    supported = experience_display(cells, MIN_SUPPORT_PLAYERS)
    ranges = experience_ranges(banded)
    story_prose(t("Collected sample · {p0} classified profiles · Lifetime context · Equal weight per profile",
                  p0=f"{len(eligible):,}"), css="story-meta")
    story_prose(story_text(
        "Character focus describes how activity is concentrated among preferred characters. The four profiles range from focus on one character, through a few characters and a broader mix, to wide variety. They are modeled patterns, not fixed character-count cutoffs or measures of loyalty over time.",
        "Specialists, multi-specialists, versatile players and generalists describe progressively broader mastery distributions. These are modeled playstyles, not fixed champion-count cutoffs or measures of loyalty over time.",
    ))

    story_section("01 · Overall sample", "Start with the complete audience mix")
    story_prose(story_text(
        "Each bar shows all four focus groups within a rank group. Its segments sum to 100%; the count beside it is the full denominator. These shares describe the collected sample.",
        "Each bar shows all four playstyles within a tier group. Its segments sum to 100%; the count beside it is the full denominator. These shares describe the collected sample.",
    ))
    if overall["n"].ge(MIN_SUPPORT_PLAYERS).any():
        legend = "".join(f'<span><span class="story-focus-swatch" style="background:{PLAYSTYLE_COLORS[style]}"></span>{escape(focus_label(style))}</span>' for style in PLAYSTYLE_ORDER)
        st.markdown(f'<div class="story-focus-legend">{legend}</div>', unsafe_allow_html=True)
        st.plotly_chart(audience_composition_chart(overall), key="story-audience-overall", width="stretch",
                       config={"displayModeBar": False})
    else:
        st.info("This snapshot has too few classified profiles for the overall comparison. Counts remain available below.")

    story_section(story_text("02 · Within activity bands", "02 · Within mastery bands"),
                  story_text("Compare how each focus group changes across ranks", "Compare each playstyle across tiers"))
    story_prose(story_text(
        "Five approximately equal-sized activity-score bands run from lowest to highest accumulated activity. Each panel follows one focus group across ranks; its five lines compare the bands. Vertical scales differ between panels so the smaller groups remain readable.",
        "Five approximately equal-sized mastery bands run from lowest to highest lifetime mastery. Each panel follows one playstyle across tiers; its five lines compare the bands. Vertical scales differ between panels so the smaller groups remain readable.",
    ))
    with st.container(key="story-band-key"):
        for band, column in enumerate(st.columns(5, gap="small"), 1):
            with column:
                label = story_text("Activity band {p0}", "Mastery band {p0}", p0=band)
                color = BAND_COLORS[band - 1]
                dash = ["none", "7 4", "2 4", "7 4 2 4", "12 4"][band - 1]
                st.markdown(f'<div class="story-band-title"><svg class="story-band-swatch" viewBox="0 0 24 8" aria-hidden="true"><line x1="0" y1="4" x2="24" y2="4" stroke="{color}" stroke-width="3" stroke-dasharray="{dash}"/></svg>{escape(label)}</div>', unsafe_allow_html=True)
                row = ranges.loc[band]
                if pd.notna(row["low"]):
                    story_prose(t("≈ {p0}–{p1} hour-equivalents", p0=f"{row.hours_low:,.0f}", p1=f"{row.hours_high:,.0f}"), css="story-band-range")
                    story_prose(story_text("{p0}–{p1} activity score", "{p0}–{p1} mastery points",
                                          p0=f"{row.low:,.0f}", p1=f"{row.high:,.0f}"), css="story-band-range")
                else:
                    story_prose("No profiles", css="story-band-range")
    story_prose(t("Hour-equivalents assume {p0} points per match and {p1} minutes per match: score / 1,200. They provide a rough sense of scale; actual hours, account age and time to reach a rank are unobserved.",
                  p0=ASSUMED_POINTS_PER_MATCH, p1=ASSUMED_MATCH_MINUTES), css="story-meta")
    if supported["share"].notna().any():
        intervals = st.toggle("Show 95% uncertainty intervals", key="story_focus_intervals")
        with st.container(key="story-focus"):
            for style, column in zip(PLAYSTYLE_ORDER, st.columns(4, gap="medium"), strict=True):
                with column:
                    story_prose(focus_label(style), css="story-band-title")
                    st.plotly_chart(audience_band_chart(supported.loc[supported["playstyle"].eq(style)], intervals=intervals),
                                    key=f"story-audience-{style}", width="stretch", config={"displayModeBar": False})
        story_prose("Hover for group counts, denominators and 95% Wilson intervals. Connected ranks help compare shapes; they do not track people moving between ranks. Missing estimates break the lines.", css="story-meta")
    else:
        st.info("This snapshot has too few classified profiles for the banded comparison. Counts remain available below.")

    story_section("03 · Audience implications", "Read the whole composition")
    last = supported.loc[supported["mastery_band"].eq(5)].set_index(["tier_group", "playstyle"])
    ends = [last.loc[(rank, style), "share"] for style in ["specialist", "generalist"] for rank in ["Iron-Silver", "Diamond+"]]
    if all(pd.notna(value) for value in ends):
        story_prose(story_text(
            "In the highest activity band, focus on one character represents {p0} in Iron–Silver and {p1} in Diamond+. Wide character variety represents {p2} and {p3}, respectively. A single focus group would hide that second comparison.",
            "In the highest mastery band, specialists represent {p0} in Iron–Silver and {p1} in Diamond+. Generalists represent {p2} and {p3}, respectively. A single playstyle would hide that second comparison.",
            **{f"p{i}": f"{value:.1%}" for i, value in enumerate(ends)},
        ))
    story_prose("These audience descriptions can guide questions about character-specific content, broader discovery and different onboarding needs. Engagement or purchase outcomes would be needed to establish whether those distinctions are useful to the business.")
    story_prose(story_text(
        "The charts describe focus composition within rank groups. They do not estimate the chance of reaching a rank, or show that focusing on fewer characters makes people climb faster. Different game modes and growing interests are possible explanations to investigate; mode histories are not measured here.",
        "The charts describe playstyle composition within tiers. They do not estimate the chance of reaching a tier, or show that specialization makes players climb faster. Different game modes and growing interests are possible explanations to investigate; mode histories are not measured here.",
    ), css="story-prose story-note")

    with st.expander("Does inferred role add context?"):
        roles = role_focus_cells(banded)
        unknown = int(roles.loc[roles["main_role"].eq("Unknown role"), "members"].sum())
        st.markdown(story_text(
            "Role is inferred from recently played characters, rather than directly observed lane usage. This is recent context alongside Lifetime focus; it is not another Lifetime measurement. Each row shows the focus mix within that role, without holding rank or activity constant.",
            "Role is inferred from recently played champions, rather than directly observed lane usage. This is recent context alongside Lifetime playstyle; it is not another Lifetime measurement. Each row shows the playstyle mix within that role, without holding tier or mastery constant.",
        ))
        st.caption(t("Unknown role: {p0} profiles. They remain a separate row instead of disappearing from the audience.", p0=f"{unknown:,}"))
        if roles["n"].ge(MIN_SUPPORT_PLAYERS).any():
            st.plotly_chart(audience_role_chart(roles), key="story-audience-roles", width="stretch", config={"displayModeBar": False})
            st.caption("Percentages are within each role; colors use the same 0–100% scale.")
        st.dataframe(focus_table(roles), hide_index=True, width="stretch")

    with st.container(key="story-methods"):
        with st.expander("How this comparison is calculated"):
            st.markdown(story_text(
                "Bands are formed across classified Lifetime profiles with a finite, nonnegative activity score, before splitting by rank. Stable source order breaks ties, so equal scores can cross a band boundary. The overall chart pools those same band counts.",
                "Bands are formed across classified Lifetime profiles with finite, nonnegative mastery, before splitting by tier. Stable source order breaks ties, so equal mastery scores can cross a band boundary. The overall chart pools those same band counts.",
            ))
            st.markdown(t("Shares use all classified profiles in each cell as the denominator. Cells with fewer than {p0} profiles keep their counts but do not show an estimate. A supported zero share remains zero. The four focus counts sum to the denominator, which repeats on their four table rows.", p0=MIN_SUPPORT_PLAYERS))
            st.markdown("The banded charts use 95% Wilson intervals for unweighted proportions. These are individual intervals, not simultaneous tests of every difference. No population weights or median-based normalization are applied.")
            st.markdown(story_text(
                "Diamond+ combines Diamond and Master. This comparison contains {p0} Master profiles; it makes no separate Master claim. The collected rank mix is not representative of the ranked population.",
                "Diamond+ combines Diamond and Master. This comparison contains {p0} Master profiles; it makes no separate Master claim. The collected tier mix is not representative of the ranked population.",
                p0=f"{int(eligible['tier'].eq('MASTER').sum()):,}",
            ))
            st.markdown("The hour conversion is an illustrative assumption, not a calibrated playtime model. Points earned per match and match duration can vary between people and game modes. Rescaling the score changes neither the bands nor the evidence about rank progression.")
            st.link_button("Metrics and methods", f"{REPOSITORY}/blob/main/docs/reference/metrics-and-methods.md")
            st.link_button("Understanding the analysis", f"{REPOSITORY}/blob/main/docs/wiki/understanding-the-analysis.md")
        with st.expander("Inspect the counts and intervals"):
            st.dataframe(focus_table(cells), hide_index=True, width="stretch")
    story_prose(story_text(
        "Audience profiles suggest questions to investigate. Measuring improvement requires observations over time.",
        "Playstyle profiles suggest questions to investigate. Measuring climbing requires observations over time.",
    ))
    story_footer(3, "pages/1_Overall_Analysis.py", "Population explorer")


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
        players = load_dataset("players").drop(columns="population_weight", errors="ignore")
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
