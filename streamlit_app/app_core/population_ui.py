"""Analyst controls for the frozen population reference."""

from __future__ import annotations

import pandas as pd

from app_core.i18n import st
from app_core.population import WEIGHT, eligible_weighted_rows, load_reference, population_weights


def population_controls(players: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    reference = load_reference()
    weighted, diagnostics = population_weights(players, reference)
    options = ["Frozen population estimate", "Collected sample"]
    selected = st.session_state.get("population_estimate_mode", options[0])

    def remember() -> None:
        st.session_state["population_estimate_mode"] = st.session_state["_population_estimate_mode"]

    mode = st.radio(
        "Analysis denominator",
        options,
        index=options.index(selected),
        horizontal=True,
        key="_population_estimate_mode",
        on_change=remember,
        help="Use the frozen tier shares to estimate the represented ranked population, or give every collected player equal weight.",
    )
    st.session_state["population_estimate_mode"] = mode
    use_weights = mode == options[0]
    info = reference.iloc[0]
    st.caption(
        f"Reference version: {info['reference_version']} · Recorded: {info['recorded_on']} · "
        f"Review after: {info['review_after']} · Source: {info['source']}"
    )
    st.caption(
        "The reference's observation date, region and queue were not supplied. Applying it to this dataset is an explicit assumption. Weighting adjusts tier composition; selection differences within tiers can remain."
    )
    if pd.Timestamp.now(tz="America/Sao_Paulo").date() >= pd.Timestamp(info["review_after"]).date():
        st.warning(
            "The frozen population reference is due for manual review. Estimates continue to use the displayed version."
        )
    if use_weights:
        missing = sorted(diagnostics.loc[~diagnostics["represented"], "tier"].unique())
        if missing:
            st.warning(
                "Some reference tiers have no sampled players in at least one scope. Estimates cover represented tiers only; missing tiers: "
                + ", ".join(missing)
            )
        unknown = int(weighted[WEIGHT].isna().sum())
        if unknown:
            st.warning(f"{unknown:,} rows have no supported tier and are excluded from weighted estimates.")
        st.caption(
            "Tier weights are calculated before filters, separately by region and queue where available. Region and queue mixes retain their sample proportions. Player counts and support thresholds remain observed counts."
        )
    with st.expander("Population reference and weighting diagnostics"):
        st.caption(
            "Covered population share is the sum of reference shares for tiers with sampled players. Supported target shares are normalized within that coverage. Weights are relative weights, not estimated population counts."
        )
        st.dataframe(diagnostics, hide_index=True, width="stretch")
        st.download_button(
            "Download weighting diagnostics",
            diagnostics.to_csv(index=False),
            "population_weighting_diagnostics.csv",
            "text/csv",
        )
        st.download_button(
            "Download frozen reference", reference.to_csv(index=False), "rank_population_reference.csv", "text/csv"
        )
    return (
        (eligible_weighted_rows(weighted) if use_weights else players.drop(columns=[WEIGHT], errors="ignore").copy()),
        diagnostics,
        use_weights,
    )
