from __future__ import annotations

from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from app_core.analysis import (
    mastery_normalized_composition,
    playstyle_composition,
    playstyle_mastery_bands,
    ranked_share_by_dimensions,
    role_playstyle_skew,
)
from app_core.metrics import recent_lifetime_comparison
from app_core.population import (
    WEIGHT,
    calibrate_population,
    category_summary,
    effective_sample_size,
    load_reference,
    reference_fingerprint,
    row_weights,
    weighted_mean,
)
from streamlit.testing.v1 import AppTest


def profiles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tier": ["BRONZE"] * 4 + ["DIAMOND"] * 4,
            "region": "BR1",
            "queue": "RANKED_SOLO_5x5",
            "main_role": "Top",
            "lifetime_playstyle": ["specialist"] * 4 + ["generalist"] * 4,
            "recent_playstyle": "specialist",
            "lifetime_hhi": 0.5,
            "lifetime_top1_share": 0.5,
            "lifetime_normalized_entropy": 0.5,
            "lifetime_primary_champion_name": "Ahri",
        }
    )


def test_supplied_reference_is_exact_and_invalid_reference_is_rejected(tmp_path):
    reference = load_reference()
    assert len(reference) == 10
    assert reference["population_share"].sum() == pytest.approx(1)
    assert reference.set_index("tier").loc[["BRONZE", "SILVER"], "population_share"].sum() == pytest.approx(0.3797)
    reference.loc[0, "population_share"] = 0.5
    path = tmp_path / "bad.csv"
    reference.to_csv(path, index=False)
    with pytest.raises(ValueError, match="summing to 1"):
        load_reference(path)
    with pytest.raises(ValueError, match="summing to 1"):
        calibrate_population(profiles(), reference)


def test_reference_fingerprint_tracks_content_and_ignores_row_column_order():
    reference = load_reference()
    fingerprint = reference_fingerprint(reference)
    reordered = reference.iloc[::-1].loc[:, list(reversed(reference.columns))]
    assert reference_fingerprint(reordered) == fingerprint
    changed = reference.copy()
    changed.loc[0, "population_share"] += 0.001
    changed.loc[1, "population_share"] -= 0.001
    assert reference_fingerprint(changed) != fingerprint


def test_equal_tier_sample_recovers_supported_target_shares_and_coverage():
    weighted, diagnostics = calibrate_population(profiles())
    expected = 0.166 / (0.166 + 0.0368)
    summary = category_summary(weighted, "tier").set_index("tier")
    assert summary.loc["BRONZE", "estimated_share"] == pytest.approx(expected)
    assert summary.loc["BRONZE", "sample_share"] == 0.5
    assert diagnostics["covered_population_share"].eq(0.2028).all()
    assert diagnostics.loc[diagnostics["tier"].eq("CHALLENGER"), WEIGHT].isna().all()
    assert weighted[WEIGHT].mean() == pytest.approx(1)
    assert effective_sample_size(weighted[WEIGHT]) < len(weighted)


def test_calibration_precedes_filters_and_within_tier_shares_do_not_change():
    raw = profiles()
    weighted, _ = calibrate_population(raw)
    selected = weighted.iloc[[0, 4, 5, 6, 7]]
    assert selected.loc[0, WEIGHT] == weighted.loc[0, WEIGHT]
    expected = 0.166 / (0.166 + 4 * 0.0368)
    summary = category_summary(selected, "tier").set_index("tier")
    assert summary.loc["BRONZE", "estimated_share"] == pytest.approx(expected)
    unweighted = playstyle_composition(raw, "Lifetime").sort_values(["tier", "playstyle"])
    estimate = playstyle_composition(weighted, "Lifetime").sort_values(["tier", "playstyle"])
    assert np.allclose(unweighted["share"], estimate["share"])
    roles = playstyle_composition(weighted, "Lifetime", "main_role").set_index("playstyle")
    assert roles.loc["specialist", "share"] == pytest.approx(0.166 / 0.2028)


def test_region_queue_scopes_duplicate_indices_and_unknown_tiers():
    second = profiles().iloc[[0, 4, 5, 6, 7]].copy()
    second["region"] = "EUW1"
    frame = pd.concat(
        [profiles(), second, pd.DataFrame({"tier": ["UNRANKED"], "region": ["BR1"], "queue": ["RANKED_SOLO_5x5"]})]
    )
    weighted, report = calibrate_population(frame)
    assert weighted.iloc[-1][WEIGHT] != weighted.iloc[-1][WEIGHT]
    assert row_weights(weighted).iloc[-1] != row_weights(weighted).iloc[-1]
    for region in ("BR1", "EUW1"):
        subset = weighted.loc[weighted["region"].eq(region)]
        summary = category_summary(subset, "tier").set_index("tier")
        assert summary.loc["BRONZE", "estimated_share"] == pytest.approx(0.166 / 0.2028)
    assert len(report) == 20


def test_weighted_transition_uses_weights_but_support_remains_raw_counts():
    weighted, _ = calibrate_population(profiles())
    matrix = recent_lifetime_comparison(weighted)
    assert matrix.loc["specialist", "specialist"] == pytest.approx(0.166 / 0.2028)
    counts = recent_lifetime_comparison(weighted, normalize=False)
    assert counts.loc["specialist", "specialist"] == 4
    skew = role_playstyle_skew(weighted, "Lifetime")
    assert skew.loc["Top", "specialist"] == pytest.approx(0)


def test_unsupported_rows_are_excluded_from_bands_transitions_and_support():
    raw = profiles()
    raw["lifetime_mastery_points"] = np.arange(1, len(raw) + 1) * 100_000
    unknown = raw.iloc[[0]].copy()
    unknown["tier"] = "UNRANKED"
    unknown["lifetime_mastery_points"] = 99_000_000
    weighted, _ = calibrate_population(pd.concat([raw, unknown], ignore_index=True))
    assert recent_lifetime_comparison(weighted, normalize=False).to_numpy().sum() == 8
    assert playstyle_composition(weighted, "Lifetime", "main_role")["players"].sum() == 8
    assert playstyle_mastery_bands(weighted, "Lifetime", 0)["players"].sum() == 8
    assert mastery_normalized_composition(weighted, "Lifetime", "main_role")["players"].sum() == 8
    assert role_playstyle_skew(weighted, "Lifetime").attrs["support_counts"].to_numpy().sum() == 8
    weighted["starting_tier"] = weighted["tier"]
    weighted["current_main_role"] = "Top"
    weighted["favoured_champions"] = [["Ahri"]] * len(weighted)
    weighted["median_ranked_mastery_share"] = 0.5
    assert ranked_share_by_dimensions(weighted, "Role", "Champion")["player_count"].sum() == 8




def test_bundle_exports_only_named_artifacts_and_fingerprints_reference(tmp_path):
    from app_core.config import DATA_DIR
    from scripts.export_population_estimates import export_bundle

    snapshot = tmp_path / "snapshot.parquet"
    pd.read_parquet(DATA_DIR / "player_profiles.parquet").head(12).to_parquet(snapshot, index=False)
    destination = tmp_path / "bundle"
    destination.mkdir()
    (destination / "unrelated_notes.txt").write_text("Must not be bundled", encoding="utf-8")
    metadata = export_bundle(snapshot, destination)
    assert metadata["reference_sha256"] == reference_fingerprint(load_reference())
    with ZipFile(destination / "population_estimates.zip") as archive:
        assert sorted(archive.namelist()) == metadata["export_files"]
        assert "unrelated_notes.txt" not in archive.namelist()


def test_weighted_ranked_activity_handles_multi_champion_cells():
    weighted, _ = calibrate_population(profiles())
    weighted["starting_tier"] = weighted["tier"]
    weighted["current_main_role"] = "Top"
    weighted["favoured_champions"] = [["Ahri", "Lux"]] * len(weighted)
    weighted["median_ranked_mastery_share"] = [1.0] * 4 + [0.0] * 4
    result = ranked_share_by_dimensions(weighted, "Role", "Champion")
    assert len(result) == 2
    assert np.allclose(result["mean_share"], 0.166 / 0.2028)
    assert result["player_count"].eq(8).all()
    assert weighted_mean(pd.Series([1.0, np.nan]), pd.Series([1.0, 100.0])) == 1


def test_analyst_page_renders_weighted_and_sample_modes():
    from app_core.config import APP_ROOT

    app = AppTest.from_file(str(APP_ROOT / "pages/4_Population_Estimates.py"), default_timeout=60).run()
    assert not app.exception
    assert len(app.get("download_button")) == 7
    next(widget for widget in app.radio if widget.label == "Analysis denominator").set_value("Collected sample").run()
    assert not app.exception
    assert app.session_state["population_estimate_mode"] == "Collected sample"
