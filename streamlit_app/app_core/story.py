"""The recruiter-facing story; analytical controls live in the separate explorers."""
from __future__ import annotations

from html import escape

import pandas as pd

from app_core.data import DashboardDataError, data_freshness, load_dataset, load_manifest
from app_core.i18n import st, t
from app_core.ui import data_source_caption, render_load_error, setup_page

REPOSITORY = "https://github.com/Pedro-Iaki/league-specialization-etl"
STORY_PAGES = [
    ("story/01_pipeline.py", "The audience question"),
    ("story/02_audience.py", "Activity and engagement"),
    ("story/03_tiers.py", "Rank and activity"),
    ("story/04_characters.py", "Character interests"),
    ("story/05_transactions.py", "Audiences and customers"),
    ("story/06_findings.py", "Engineering and evidence"),
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


def story_start(number: int, title: str, deck: str) -> pd.DataFrame:
    setup_page(STORY_PAGES[number - 1][1], project_name="players-as-customers-pipeline")
    st.markdown(STORY_CSS, unsafe_allow_html=True)
    st.markdown('<div class="story-brand">players-as-customers-pipeline</div>', unsafe_allow_html=True)
    progress = t("The story · {p0} of 6", p0=number) + " · " + t(STORY_PAGES[number - 1][1])
    st.markdown(f'<div class="story-progress">{escape(progress)}</div><h1 class="story-heading">{escape(t(title))}</h1><p class="story-deck">{escape(t(deck))}</p>', unsafe_allow_html=True)
    try:
        players = load_dataset("players", include_all_tiers=True).drop(columns="population_weight", errors="ignore")
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
