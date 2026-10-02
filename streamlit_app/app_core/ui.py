from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from app_core.config import PLAYSTYLE_LABELS
from app_core.data import configured_data_mode

GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,600&display=swap');

:root {
  --ink: #e8eef6;
  --muted: #9aabc0;
  --gold: #d8a52d;
  --blue: #4ea5d9;
  --panel: #0e1b2b;
  --line: rgba(154, 171, 192, 0.16);
}

.stApp {
  background:
    radial-gradient(circle at 85% -10%, rgba(78, 165, 217, 0.14), transparent 31rem),
    radial-gradient(circle at 15% 0%, rgba(216, 165, 45, 0.09), transparent 28rem),
    #07111f;
}

html, body, [class*="css"] {
  font-family: "Manrope", system-ui, sans-serif;
  color: var(--ink);
}

h1, h2, h3 {
  font-family: "Source Serif 4", Georgia, serif;
  letter-spacing: -0.02em;
}

[data-testid="stSidebar"] {
  background: rgba(8, 20, 34, 0.96);
  border-right: 1px solid var(--line);
}

[data-testid="stMetric"] {
  background: linear-gradient(145deg, rgba(17, 34, 54, 0.96), rgba(11, 25, 41, 0.96));
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 1rem 1.05rem;
  min-height: 116px;
}

[data-testid="stMetricLabel"] { color: var(--muted); }
[data-testid="stMetricValue"] { color: var(--ink); }

.st-key-association_metric,
.st-key-primary_metric,
.st-key-active_metric,
.st-key-historical_metric,
.st-key-ranked_share_metric,
.st-key-mastery_mean_metric,
.st-key-mastery_median_metric { position: relative; }
.st-key-association_metric [data-testid="stMetric"],
.st-key-primary_metric [data-testid="stMetric"],
.st-key-active_metric [data-testid="stMetric"],
.st-key-historical_metric [data-testid="stMetric"],
.st-key-ranked_share_metric [data-testid="stMetric"],
.st-key-mastery_mean_metric [data-testid="stMetric"],
.st-key-mastery_median_metric [data-testid="stMetric"] { padding-right: 2.8rem; }
.st-key-association_metric .st-key-cycle_specialization,
.st-key-primary_metric .st-key-toggle_primary_pct,
.st-key-active_metric .st-key-toggle_active_pct,
.st-key-historical_metric .st-key-toggle_historical_pct,
.st-key-ranked_share_metric .st-key-cycle_ranked_share,
.st-key-mastery_mean_metric .st-key-toggle_mastery_mean_comparison,
.st-key-mastery_median_metric .st-key-toggle_mastery_median_comparison {
  position: absolute;
  top: 0.7rem;
  right: 0.7rem;
  z-index: 1;
}
.st-key-association_metric .st-key-cycle_specialization button,
.st-key-primary_metric .st-key-toggle_primary_pct button,
.st-key-active_metric .st-key-toggle_active_pct button,
.st-key-historical_metric .st-key-toggle_historical_pct button,
.st-key-ranked_share_metric .st-key-cycle_ranked_share button,
.st-key-mastery_mean_metric .st-key-toggle_mastery_mean_comparison button,
.st-key-mastery_median_metric .st-key-toggle_mastery_median_comparison button {
  min-height: 1.9rem;
  height: 1.9rem;
  width: 1.9rem;
  padding: 0;
  border-radius: 999px;
  font-size: 1.2rem;
  line-height: 1;
}

.block-container {
  max-width: 1320px;
  padding-top: 2rem;
  padding-bottom: 4rem;
}

.hero {
  border: 1px solid var(--line);
  border-radius: 22px;
  padding: clamp(1.5rem, 4vw, 3.5rem);
  margin-bottom: 1.8rem;
  background:
    linear-gradient(120deg, rgba(15, 33, 53, 0.98), rgba(8, 22, 38, 0.92)),
    #0e1b2b;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.22);
  position: relative;
  overflow: hidden;
}

.hero::after {
  content: "";
  position: absolute;
  width: 260px;
  height: 260px;
  right: -90px;
  top: -110px;
  border: 1px solid rgba(216, 165, 45, 0.3);
  transform: rotate(35deg);
}

.eyebrow {
  color: var(--gold);
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  margin-bottom: 0.8rem;
}

.hero h1 {
  font-size: clamp(2.15rem, 5vw, 4.5rem);
  line-height: 0.98;
  margin: 0;
  max-width: 860px;
}

.hero p {
  color: #b9c7d8;
  font-size: 1.05rem;
  line-height: 1.75;
  max-width: 830px;
  margin: 1.2rem 0 0;
}

.section-kicker {
  color: var(--gold);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  margin-top: 1rem;
}

.section-copy {
  color: var(--muted);
  max-width: 850px;
  margin-top: -0.45rem;
  margin-bottom: 0.9rem;
}

.insight {
  border-left: 3px solid var(--gold);
  background: rgba(216, 165, 45, 0.07);
  border-radius: 0 12px 12px 0;
  padding: 0.9rem 1rem;
  color: #c9d4e2;
  margin: 0.75rem 0 1.1rem;
}

.source-pill {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0.28rem 0.65rem;
  color: var(--muted);
  font-size: 0.74rem;
  margin: 0.15rem 0.3rem 0.15rem 0;
}

.flow {
  display: grid;
  grid-template-columns: repeat(6, minmax(100px, 1fr));
  gap: 0.65rem;
  align-items: center;
  margin: 1.2rem 0 2rem;
}

.flow-step {
  background: rgba(14, 27, 43, 0.95);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.9rem 0.75rem;
  text-align: center;
  min-height: 78px;
}

.flow-step strong { color: var(--gold); display: block; margin-bottom: 0.22rem; }
.flow-step span { color: var(--muted); font-size: 0.78rem; }

@media (max-width: 850px) {
  .flow { grid-template-columns: repeat(2, 1fr); }
  .block-container { padding-left: 1rem; padding-right: 1rem; }
}
</style>
"""


def setup_page(title: str, icon: str = "◈") -> None:
    st.set_page_config(
        page_title=f"{title} · League Specialization",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def hero(eyebrow: str, title: str, copy: str) -> None:
    st.markdown(
        f"""
        <section class="hero">
          <div class="eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p>{copy}</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def section(kicker: str, title: str, copy: str | None = None) -> None:
    st.markdown(f'<div class="section-kicker">{kicker}</div>', unsafe_allow_html=True)
    st.subheader(title)
    if copy:
        st.markdown(f'<div class="section-copy">{copy}</div>', unsafe_allow_html=True)


def insight(copy: str) -> None:
    st.markdown(f'<div class="insight">{copy}</div>', unsafe_allow_html=True)


def source_pills(*models: str) -> None:
    pills = "".join(f'<span class="source-pill">{model}</span>' for model in models)
    st.markdown(pills, unsafe_allow_html=True)


def data_source_caption(freshness: str) -> None:
    mode = configured_data_mode()
    label = "versioned Parquet snapshot" if mode == "snapshot" else "live Databricks SQL"
    st.sidebar.caption(f"Data source: {label}\n\nLatest profile date: {freshness}")


def support_warning(message: str, key: str) -> bool:
    """Place a per-section low-support override beside its warning."""
    state_key = f"show_omitted_{key}"
    shown = st.session_state.get(state_key, False)

    def flip() -> None:
        st.session_state[state_key] = not st.session_state.get(state_key, False)

    notice, action = st.columns([5, 1], gap="small", vertical_alignment="center")
    detail = message.removeprefix("Insufficient data: ").strip()
    notice.warning(message if not shown else f"Showing low-support results: {detail}")
    action.button(
        "Hide omitted" if shown else "Show omitted",
        key=f"toggle_omitted_{key}",
        help="Low-support results keep their counts so you can assess them.",
        on_click=flip,
        width="stretch",
    )
    return shown


def format_compact(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    absolute = abs(float(value))
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def format_percent(value: float | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.{digits}%}"


def format_signed(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.{digits}f}"


def playstyle_name(value: str | None) -> str:
    if not value or pd.isna(value):
        return "Insufficient activity"
    return PLAYSTYLE_LABELS.get(str(value), str(value).title())


def render_load_error(error: Exception) -> None:
    st.error("The dashboard data could not be loaded.")
    st.code(str(error), language=None)
    st.info(
        "Snapshot mode is the default. Generate the local extracts with "
        "`python scripts/export_data.py` from the `streamlit_app` directory."
    )
    st.stop()


def architecture_flow() -> None:
    st.markdown(
        """
        <div class="flow">
          <div class="flow-step"><strong>Riot API</strong><span>rank & mastery snapshots</span></div>
          <div class="flow-step"><strong>Extraction</strong><span>rate limits, retries, state</span></div>
          <div class="flow-step"><strong>Bronze</strong><span>raw Delta records</span></div>
          <div class="flow-step"><strong>Silver</strong><span>history & dimensions</span></div>
          <div class="flow-step"><strong>Gold</strong><span>analytical marts</span></div>
          <div class="flow-step"><strong>Streamlit</strong><span>public-safe data product</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
