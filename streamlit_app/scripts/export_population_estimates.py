"""Build an anonymous analyst bundle from the existing snapshot, without warehouse access."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app_core.config import PLAYSTYLE_ORDER, REPO_ROOT
from app_core.population import (
    WEIGHT,
    calibrate_population,
    category_summary,
    direct_standardized_means,
    effective_sample_size,
    load_reference,
    reference_fingerprint,
    weighted_mean,
    weighted_quantile,
)


def export_bundle(snapshot: Path, output_dir: Path) -> dict:
    players = pd.read_parquet(snapshot)
    forbidden = {"player_id", "puuid", "summoner_id", "account_id", "game_name", "tag_line", "riot_id"}
    if forbidden.intersection(players.columns):
        raise ValueError("Analyst bundle requires the anonymous dashboard snapshot")
    reference = load_reference()
    weighted, diagnostics = calibrate_population(players, reference)
    output_dir.mkdir(parents=True, exist_ok=True)
    weighted["reference_version"] = reference["reference_version"].iloc[0]
    exported_names = [
        "anonymous_weighted_profiles.parquet",
        "rank_population_reference.csv",
        "weighting_diagnostics.csv",
    ]
    weighted.to_parquet(output_dir / "anonymous_weighted_profiles.parquet", index=False)
    reference.to_csv(output_dir / "rank_population_reference.csv", index=False)
    diagnostics.to_csv(output_dir / "weighting_diagnostics.csv", index=False)
    for column in ("tier", "main_role", "recent_playstyle", "lifetime_playstyle", "recent_primary_champion_name"):
        frame = weighted.copy()
        frame[column] = frame[column].fillna("Unclassified")
        category_summary(frame, column).to_csv(output_dir / f"{column}_estimates.csv", index=False)
        exported_names.append(f"{column}_estimates.csv")
    metrics = []
    for column in (
        "lifetime_mastery_points",
        "rank_score",
        "recent_hhi",
        "recent_top1_share",
        "latest_rank_period_lp_per_game",
        "latest_rank_period_win_rate",
    ):
        values = pd.to_numeric(weighted[column], errors="coerce")
        valid = values.notna() & weighted[WEIGHT].notna()
        metrics.append(
            {
                "metric": column,
                "observed_players": int(valid.sum()),
                "effective_players": effective_sample_size(weighted.loc[valid, WEIGHT]),
                "sample_mean": values[valid].mean(),
                "estimated_mean": weighted_mean(values, weighted[WEIGHT]),
                "sample_median": values[valid].median(),
                "estimated_median": weighted_quantile(values, weighted[WEIGHT]),
            }
        )
    pd.DataFrame(metrics).to_csv(output_dir / "metric_estimates.csv", index=False)
    standardization_metrics = [entry["metric"] for entry in metrics]
    standardized_tables, tier_tables = [], []
    for cohort_name, cohort in {
        "all_profiles": players,
        "recent_classified": players.loc[players["recent_playstyle"].isin(PLAYSTYLE_ORDER)],
        "lifetime_classified": players.loc[players["lifetime_playstyle"].isin(PLAYSTYLE_ORDER)],
    }.items():
        standardized, tiers = direct_standardized_means(cohort, standardization_metrics, reference)
        standardized_tables.append(standardized.assign(cohort=cohort_name))
        tier_tables.append(tiers.assign(cohort=cohort_name))
    pd.concat(standardized_tables, ignore_index=True).to_csv(output_dir / "standardized_means.csv", index=False)
    pd.concat(tier_tables, ignore_index=True).to_csv(output_dir / "standardization_tiers.csv", index=False)
    exported_names.extend(["standardized_means.csv", "standardization_tiers.csv"])
    exported_names.extend(["metric_estimates.csv", "manifest.json", "ANALYST_HANDOFF.md"])
    metadata = {
        "reference_version": str(reference["reference_version"].iloc[0]),
        "reference_recorded_on": str(reference["recorded_on"].iloc[0]),
        "reference_observation_date": None,
        "reference_scope": str(reference["reference_scope"].iloc[0]),
        "reference_sha256": reference_fingerprint(reference),
        "source_snapshot": snapshot.name,
        "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "observed_players": len(weighted),
        "eligible_players": int(weighted[WEIGHT].notna().sum()),
        "effective_players": effective_sample_size(weighted[WEIGHT]),
        "covered_share_min": float(diagnostics["covered_population_share"].min()),
        "covered_share_max": float(diagnostics["covered_population_share"].max()),
        "calibration": "Current tier within each available region/queue before filters",
        "standardization": "Selected cohort tier means; separate region/queue estimates; minimum 5 valid players per tier",
        "standardization_minimum_coverage": 0.99,
        "regional_queue_mix": "Sample proportions; relative population sizes unknown",
        "export_files": sorted(exported_names),
    }
    if "as_of_date" in players:
        metadata["latest_profile_date"] = str(pd.to_datetime(players["as_of_date"]).max().date())
    (output_dir / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    report = f"""# Population estimates — analyst handoff

Reference: **{metadata["reference_version"]}**. Recorded on {metadata["reference_recorded_on"]}; review after {reference["review_after"].iloc[0]}. Source: {reference["source"].iloc[0]}. Scope: {metadata["reference_scope"]}. The reference records no separate observation date.

This bundle uses {metadata["observed_players"]:,} anonymous player profiles ({metadata["eligible_players"]:,} eligible for weighting). Effective sample size is {metadata["effective_players"]:,.1f}. Reference coverage across scopes ranges from {metadata["covered_share_min"]:.2%} to {metadata["covered_share_max"]:.2%}. Missing tiers are not imputed; results describe represented tiers only.

Open **Population Estimates** in the Streamlit dashboard to compare sample and weighted estimates, filter the cohort and download tables. Supported calculations in **Population**, **Specialization and rank**, **Champion Explorer** and **Cross-champion** also offer population views; check each calculation's estimator and support. The guided story, commercial summaries and raw experience comparison remain sample-based.

## Bundle contents

- `anonymous_weighted_profiles.parquet`: anonymous profiles with `population_weight` and `reference_version`.
- `rank_population_reference.csv`: the exact frozen tier shares.
- `weighting_diagnostics.csv`: scope/tier counts, raw and supported target shares, coverage and relative weights.
- `*_estimates.csv`: sample versus weighted category shares and player metrics.
- `standardized_means.csv` and `standardization_tiers.csv`: common-tier mean comparisons for all profiles and recent/lifetime classified cohorts, with metric-specific support and coverage.
- `manifest.json`: input snapshot hash, canonical reference hash, reference version, coverage and explicit bundle file list for reproducibility.

## Use the weights

For a mean: `sum(population_weight * value) / sum(population_weight)` over nonmissing values with valid weights. For a share: sum the weights of matching players and divide by the weights of eligible players. Keep the original weights when applying filters. Weighted mass is not a population count. Current tier is the calibration variable; recent outcomes remain conditional on observed players.

Tier composition is adjusted under the supplied frozen estimate. Within-tier selection bias remains possible. Region and queue proportions remain those of the sample. This reference is an assumed distribution for each scope, not a verified regional estimate. Effective sample size reports weight dispersion, not reference uncertainty; no confidence intervals are claimed.

For a comparison at a common tier mix, use the separate direct-standardization files: `sum(reference_share * tier_mean) / sum(reference_share)` over tiers with at least five valid metric observations. Coverage below 99% is flagged. This answers a different question from a conditional subgroup estimate using original weights. Do not force subgroup composition to the full ladder when estimating subgroup prevalence. Division shares are unavailable; neither method corrects division bias, missing profiles or selection into ranked observation.

## Manual reference maintenance

Edit `league_pipeline/seeds/rank_population_reference.csv`, keep all ten positive shares summing to 1, and update version, recorded/review dates and provenance together. The dashboard flags review after {reference["review_after"].iloc[0]}; it does not fetch external data or silently replace the reference. New ranks require updating supported tier lists and reviewing chart/model coverage. Regenerate this bundle after a seed or snapshot change.

Population weights are computed in Python from the local reference CSV. No warehouse weight mart is needed. Recreate the bundle after a profile snapshot or reference change; the bundle freezes the input snapshot and its exact reference, including only the files listed in its manifest.
"""
    (output_dir / "ANALYST_HANDOFF.md").write_text(report, encoding="utf-8")
    with ZipFile(output_dir / "population_estimates.zip", "w", ZIP_DEFLATED) as archive:
        for name in sorted(exported_names):
            path = output_dir / name
            archive.write(path, path.name)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=APP_ROOT / "data" / "player_profiles.parquet")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data" / "population_estimates")
    args = parser.parse_args()
    result = export_bundle(args.snapshot, args.output_dir)
    print(json.dumps(result, indent=2))
    print(f"Analyst bundle: {args.output_dir.resolve() / 'population_estimates.zip'}")
