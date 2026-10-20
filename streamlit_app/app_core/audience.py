"""Paired audience comparisons with frozen, value-based activity bands."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from app_core import data
from app_core.config import PLAYSTYLE_ORDER
from app_core.data import DashboardDataError
from app_core.experience import TIER_GROUP_MAP as RANK_MAP, TIER_GROUPS as RANK_GROUPS

DEFINITION_VERSION = "active-pool-lifetime-v1"
WINDOWS = {"active_pool_lifetime": "Among active characters", "lifetime": "Whole history"}
REQUIRED_PROFILE_COLUMNS = {
    "as_of_date",
    "tier",
    "lifetime_mastery_points",
    "recent_playstyle",
    "lifetime_playstyle",
    "active_pool_lifetime_mastery_points",
    "active_pool_lifetime_top1_share",
    "active_pool_lifetime_hhi",
    "lifetime_top1_share",
    "lifetime_hhi",
    "days_tracked",
    "recent_mastery_points",
}


def paired_profiles(players: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_PROFILE_COLUMNS.difference(players.columns)
    if missing:
        raise DashboardDataError(f"Audience comparison is missing profile fields: {sorted(missing)}")
    valid = (
        players.recent_playstyle.isin(PLAYSTYLE_ORDER)
        & players.lifetime_playstyle.isin(PLAYSTYLE_ORDER)
        & players.tier.isin(RANK_MAP)
        & np.isfinite(players.lifetime_mastery_points)
        & players.lifetime_mastery_points.gt(0)
        & players.active_pool_lifetime_mastery_points.gt(0)
    )
    for window in WINDOWS:
        for metric in ("top1_share", "hhi"):
            values = players[f"{window}_{metric}"]
            valid &= np.isfinite(values) & values.between(0, 1 + 1e-12)
    frame = players.loc[valid].drop(columns="population_weight", errors="ignore").copy()
    frame["rank_group"] = frame.tier.map(RANK_MAP)
    return frame


def build_reference(players: pd.DataFrame, source_hash: str) -> dict:
    """Manual snapshot operation; never called while filtering a dashboard page."""
    paired = paired_profiles(players)
    if paired.empty:
        raise ValueError("No profiles support the paired concentration comparison")
    # Scores are integers. Exact interpolation avoids flooring 639.999999999 to 639.
    scores = sorted(paired.lifetime_mastery_points.astype("int64").tolist())
    cuts = []
    for quintile in range(1, 5):
        index, remainder = divmod(quintile * (len(scores) - 1), 5)
        following = min(index + 1, len(scores) - 1)
        cuts.append((scores[index] * (5 - remainder) + scores[following] * remainder) // 5)
    if len(set(cuts)) != 4:
        raise ValueError("This cohort cannot support five distinct value-based activity bands")
    as_of = pd.to_datetime(paired.as_of_date).max().strftime("%Y-%m-%d")
    return {
        "definition_version": DEFINITION_VERSION,
        "cohort_id": f"audience-paired-{as_of.replace('-', '')}-v1",
        "band_version": f"paired-quintiles-{as_of.replace('-', '')}-v1",
        "source_profile_sha256": source_hash,
        "source_profile_count": len(players),
        "cohort_n": len(paired),
        "as_of_date": as_of,
        "right_closed_score_cuts": cuts,
        "chart_focus_bin_edges": [round(i / 10, 1) for i in range(11)],
        "tie_policy": "Equal scores stay in the same band; upper score cuts are inclusive.",
        "population_weighting": "None; one vote per profile.",
    }


def load_reference() -> dict:
    try:
        reference = json.loads((data.DATA_DIR / "audience_reference.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DashboardDataError("The snapshot has no readable frozen audience reference") from error
    actual = hashlib.sha256(data.snapshot_paths()["players"].read_bytes()).hexdigest()
    if reference.get("source_profile_sha256") != actual:
        raise DashboardDataError("The audience reference belongs to a different player snapshot")
    return reference


def prepare_audience(players: pd.DataFrame, reference: dict) -> pd.DataFrame:
    if reference.get("definition_version") != DEFINITION_VERSION:
        raise DashboardDataError("Unsupported audience definition version")
    cuts = reference.get("right_closed_score_cuts", [])
    if len(cuts) != 4 or not np.isfinite(cuts).all() or not np.all(np.diff(cuts) > 0):
        raise DashboardDataError("The audience reference needs four increasing activity-score cuts")
    if reference.get("chart_focus_bin_edges") != [round(i / 10, 1) for i in range(11)]:
        raise DashboardDataError("Unsupported audience concentration display bins")
    frame = paired_profiles(players)
    if len(players) != reference.get("source_profile_count") or len(frame) != reference.get("cohort_n"):
        raise DashboardDataError("The profile cohort does not match the frozen audience reference")
    frame["activity_band"] = pd.cut(
        frame.lifetime_mastery_points,
        [-np.inf, *cuts, np.inf],
        labels=range(1, 6),
        right=True,
    ).astype(int)
    return frame


def concentration_cells(banded: pd.DataFrame) -> pd.DataFrame:
    """Medians and quartiles are unweighted distribution summaries, not confidence intervals."""
    index = pd.MultiIndex.from_product([range(1, 6), RANK_GROUPS], names=["activity_band", "rank_group"])
    results = []
    for window in WINDOWS:
        cells = (
            banded.groupby(["activity_band", "rank_group"], observed=True)
            .agg(
                n=(f"{window}_top1_share", "size"),
                median=(f"{window}_top1_share", "median"),
                q1=(f"{window}_top1_share", lambda x: x.quantile(0.25)),
                q3=(f"{window}_top1_share", lambda x: x.quantile(0.75)),
                median_hhi=(f"{window}_hhi", "median"),
            )
            .reindex(index)
            .reset_index()
        )
        cells["n"] = cells.n.fillna(0).astype(int)
        cells["window"] = window
        results.append(cells)
    return pd.concat(results, ignore_index=True)


def audience_grid(banded: pd.DataFrame, window: str) -> pd.DataFrame:
    if window not in WINDOWS:
        raise ValueError("Unknown concentration window")
    frame = banded.copy()
    frame["focus_bin"] = np.minimum((frame[f"{window}_top1_share"].clip(upper=1) * 10).astype(int), 9)
    index = pd.MultiIndex.from_product(
        [range(1, 6), RANK_GROUPS, range(10)], names=["activity_band", "rank_group", "focus_bin"]
    )
    counts = frame.groupby(["activity_band", "rank_group", "focus_bin"], observed=True).size()
    result = counts.reindex(index, fill_value=0).rename("profiles").reset_index()
    result["n"] = result.groupby(["activity_band", "rank_group"]).profiles.transform("sum")
    return result


def maturity_summary(banded: pd.DataFrame) -> pd.DataFrame:
    frame = banded.assign(maturity=np.where(banded.days_tracked.ge(30), "Mature history", "Short history"))
    return (
        frame.groupby("maturity", sort=False)
        .agg(
            n=("maturity", "size"),
            active_median=("active_pool_lifetime_top1_share", "median"),
            history_median=("lifetime_top1_share", "median"),
        )
        .reset_index()
    )
