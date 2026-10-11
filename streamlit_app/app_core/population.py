"""Frozen tier post-stratification shared by plots and analyst exports.

Weights belong to the unfiltered calibration cohort. Keep them when taking
subsets; recalibrating a champion, role or classified subset changes the estimand.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from app_core.config import REPO_ROOT

REFERENCE_PATH = REPO_ROOT / "league_pipeline" / "seeds" / "rank_population_reference.csv"
ALL_TIERS = [
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
    "GRANDMASTER",
    "CHALLENGER",
]
WEIGHT = "population_weight"


def load_reference(path: Path = REFERENCE_PATH) -> pd.DataFrame:
    return validate_reference(pd.read_csv(path))


def validate_reference(reference: pd.DataFrame) -> pd.DataFrame:
    """Validate file-loaded and explicitly supplied references with the same contract."""
    reference = reference.copy()
    required = {
        "tier",
        "population_share",
        "reference_version",
        "recorded_on",
        "review_after",
        "source",
        "reference_scope",
    }
    if not required.issubset(reference):
        raise ValueError("Population reference is missing required columns")
    shares = pd.to_numeric(reference["population_share"], errors="coerce")
    if (
        reference["tier"].duplicated().any()
        or set(reference["tier"]) != set(ALL_TIERS)
        or not np.isfinite(shares).all()
        or not shares.gt(0).all()
        or not np.isclose(shares.sum(), 1.0, rtol=0, atol=1e-8)
    ):
        raise ValueError("Population reference must contain all ten tiers with positive shares summing to 1")
    for column in required - {"tier", "population_share"}:
        if reference[column].isna().any() or reference[column].nunique() != 1:
            raise ValueError(f"Population reference requires one nonmissing {column}")
    if pd.Timestamp(reference["review_after"].iloc[0]) <= pd.Timestamp(reference["recorded_on"].iloc[0]):
        raise ValueError("Population reference review date must follow its recorded date")
    reference["population_share"] = shares
    return reference.set_index("tier").loc[ALL_TIERS].reset_index()


def reference_fingerprint(reference: pd.DataFrame) -> str:
    """Hash the canonical reference content, including shares and provenance."""
    canonical = validate_reference(reference).sort_index(axis=1).to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calibrate_population(
    players: pd.DataFrame,
    reference: pd.DataFrame | None = None,
    *,
    tier_column: str = "tier",
    scope_columns: tuple[str, ...] = ("region", "queue"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach mean-one weights within each represented scope and return ten-tier diagnostics.

    Unsupported tiers have no invented observations. Results are conditional on
    represented tiers; coverage is reported against the full frozen reference.
    Unknown tiers get NaN weights, never an implicit weight of one.
    """
    reference = load_reference() if reference is None else validate_reference(reference)
    frame = players.copy()
    scopes = [column for column in scope_columns if column in frame]
    # Use positional arrays so duplicate dataframe indices cannot misassign weights.
    frame[WEIGHT] = np.nan
    reports = []
    grouped = frame.groupby(scopes, dropna=False, observed=True).indices if scopes else {(): np.arange(len(frame))}
    for scope, positions in grouped.items():
        cohort = frame.iloc[positions]
        counts = cohort[tier_column].value_counts().reindex(reference["tier"], fill_value=0)
        report = reference.copy()
        report["sample_players"] = counts.to_numpy()
        represented = report["sample_players"].gt(0)
        covered = float(report.loc[represented, "population_share"].sum())
        eligible = int(report["sample_players"].sum())
        report["sample_share"] = report["sample_players"] / eligible if eligible else 0.0
        report["covered_population_share"] = covered
        report["target_share_supported"] = report["population_share"] / covered if covered else np.nan
        report["target_share_supported"] = report["target_share_supported"].where(represented)
        report[WEIGHT] = (report["target_share_supported"] / report["sample_share"].replace(0, np.nan)).where(
            represented
        )
        report["represented"] = represented
        scope_values = scope if isinstance(scope, tuple) else (scope,)
        for column, value in zip(scopes, scope_values, strict=True):
            report[column] = value
        mapping = report.set_index("tier")[WEIGHT]
        frame.iloc[positions, frame.columns.get_loc(WEIGHT)] = cohort[tier_column].map(mapping).to_numpy()
        reports.append(report)
    diagnostics = (
        pd.concat(reports, ignore_index=True)
        if reports
        else reference.assign(
            sample_players=0,
            sample_share=0.0,
            covered_population_share=0.0,
            target_share_supported=np.nan,
            population_weight=np.nan,
            represented=False,
        )
    )
    return frame, diagnostics


def row_weights(frame: pd.DataFrame) -> pd.Series:
    """Absent weights mean sample mode; invalid explicit weights exclude the row."""
    if WEIGHT not in frame:
        return pd.Series(1.0, index=frame.index)
    values = pd.to_numeric(frame[WEIGHT], errors="coerce")
    return values.where(np.isfinite(values) & values.gt(0))


def population_weights(players: pd.DataFrame, reference: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Use mart weights when exported, validating the frozen cohort and reference.

    Older anonymous snapshots calculate the identical formula locally. Validation
    catches stale weights, a changed reference, and calibration after filtering.
    """
    reference = load_reference() if reference is None else validate_reference(reference)
    calculated, diagnostics = calibrate_population(players, reference)
    if WEIGHT not in players:
        return calculated, diagnostics
    supplied = row_weights(players)
    expected = row_weights(calculated)
    if not np.allclose(supplied, expected, equal_nan=True, rtol=1e-8, atol=1e-10):
        raise ValueError("Exported population weights do not match the full snapshot and frozen reference. Refresh the export.")
    if "reference_version" in players:
        versions = players.loc[supplied.notna(), "reference_version"]
        if versions.isna().any() or not versions.eq(reference["reference_version"].iloc[0]).all():
            raise ValueError("Exported population weights use a different reference version. Refresh the export.")
    calculated[WEIGHT] = supplied.to_numpy()
    return calculated, diagnostics


def apply_tier_weights(
    frame: pd.DataFrame, diagnostics: pd.DataFrame, tier_column: str = "tier",
) -> pd.DataFrame:
    """Transfer unfiltered cohort weights to subsets or tier-preserving aggregates.

    Legacy exports without scope columns are supported only for a single source
    scope. Never recalibrate a champion or role subset to the full reference.
    """
    scopes = [column for column in ("region", "queue") if column in diagnostics]
    missing = [column for column in scopes if column not in frame]
    for column in missing:
        if diagnostics[column].nunique(dropna=False) != 1:
            raise ValueError("Population estimates need region and queue in this export when multiple scopes are present.")
    keys = [column for column in scopes if column in frame] + [tier_column]
    mapping = diagnostics.rename(columns={"tier": tier_column})[keys + [WEIGHT]].drop_duplicates()
    if mapping.duplicated(keys).any():
        raise ValueError("Population weight mapping is ambiguous for this export.")
    result = frame.drop(columns=[WEIGHT], errors="ignore").merge(mapping, how="left", on=keys, validate="many_to_one")
    result.attrs.update(frame.attrs)
    return eligible_weighted_rows(result)


def weighted_summary(frame: pd.DataFrame, group: str, metrics: dict[str, str]) -> pd.DataFrame:
    """Pooled estimates with observed denominators and effective-size diagnostics."""
    valid = eligible_weighted_rows(frame)
    valid["_weight"] = row_weights(valid)
    columns = [group, "players", "effective_players"] + list(metrics)
    if valid.empty:
        return pd.DataFrame(columns=columns)
    return valid.groupby(group, observed=True).apply(
        lambda rows: pd.Series({
            "players": len(rows), "effective_players": effective_sample_size(rows["_weight"]),
            **{label: weighted_mean(rows[source], rows["_weight"]) for label, source in metrics.items()},
        }), include_groups=False,
    ).reset_index()


def eligible_weighted_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove unsupported rows before both estimates and observed support counts."""
    return frame.loc[row_weights(frame).notna()].copy()


def effective_sample_size(weights: pd.Series) -> float:
    valid = weights.dropna()
    return float(valid.sum() ** 2 / valid.pow(2).sum()) if len(valid) else 0.0


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    return float(np.average(values[valid], weights=weights[valid])) if valid.any() else np.nan


def weighted_quantile(values: pd.Series, weights: pd.Series, quantile: float = 0.5) -> float:
    valid = values.notna() & weights.notna() & weights.gt(0)
    if not valid.any():
        return np.nan
    ordered = pd.DataFrame({"value": values[valid], "weight": weights[valid]}).sort_values("value")
    if ordered["weight"].nunique() == 1:
        return float(ordered["value"].quantile(quantile))
    # Midpoint cumulative mass interpolation; invariant to uniform rescaling.
    centers = (ordered["weight"].cumsum() - ordered["weight"] / 2) / ordered["weight"].sum()
    return float(np.interp(quantile, centers, ordered["value"]))


def category_summary(frame: pd.DataFrame, group: str, categories: list[str] | None = None) -> pd.DataFrame:
    valid = frame.loc[frame[group].notna()].copy()
    if categories is not None:
        valid = valid.loc[valid[group].isin(categories)]
    valid["_weight"] = row_weights(valid)
    valid = valid.loc[valid["_weight"].notna()]
    summary = valid.groupby(group, observed=True).agg(
        players=("_weight", "size"),
        weighted_mass=("_weight", "sum"),
        weight_squares=("_weight", lambda w: w.pow(2).sum()),
    )
    if categories is not None:
        summary = summary.reindex(categories, fill_value=0)
    summary["sample_share"] = summary["players"] / summary["players"].sum() if len(valid) else np.nan
    summary["estimated_share"] = summary["weighted_mass"] / summary["weighted_mass"].sum() if len(valid) else np.nan
    summary["effective_players"] = summary["weighted_mass"].pow(2) / summary["weight_squares"].replace(0, np.nan)
    summary["difference_pp"] = (summary["estimated_share"] - summary["sample_share"]) * 100
    return summary.drop(columns="weight_squares").reset_index()
