import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from app_core import data
from app_core.audience import (
    RANK_GROUPS,
    WINDOWS,
    audience_grid,
    build_reference,
    concentration_cells,
    load_reference,
    paired_profiles,
    prepare_audience,
)
from app_core.audience_charts import concentration_chart
from app_core.data import DashboardDataError
from app_core.experience import experience_focus_cells


@pytest.fixture
def profiles():
    frame = pd.DataFrame(
        {
            "as_of_date": ["2026-10-19"] * 40,
            "tier": ["IRON", "GOLD", "EMERALD", "GRANDMASTER"] * 10,
            "lifetime_mastery_points": np.repeat(np.arange(1, 11) * 100, 4),
            "recent_playstyle": ["generalist"] * 40,
            "lifetime_playstyle": ["specialist", "multispecialist", "versatile", "generalist"] * 10,
            "active_pool_lifetime_mastery_points": [50] * 40,
            "active_pool_lifetime_top1_share": np.linspace(0.1, 1, 40),
            "active_pool_lifetime_hhi": [0.3] * 40,
            "lifetime_top1_share": [0.2] * 40,
            "lifetime_hhi": [0.1] * 40,
            "days_tracked": [0, 33] * 20,
            "recent_mastery_points": [0] * 40,
            "main_role": [None] * 40,
            "population_weight": [999, 1, 1, 1] * 10,
        }
    )
    return frame


def test_cohort_keeps_apex_missing_type_and_zero_gain_but_excludes_undefined(profiles):
    invalid = profiles.head(4).copy()
    invalid.loc[0, "recent_playstyle"] = None
    invalid.loc[1, "active_pool_lifetime_mastery_points"] = 0
    invalid.loc[2, "lifetime_mastery_points"] = -1
    invalid.loc[3, "active_pool_lifetime_top1_share"] = np.inf
    combined = pd.concat([profiles, invalid], ignore_index=True)
    paired = paired_profiles(combined)
    assert len(paired) == 40
    assert paired.rank_group.eq("Diamond+").sum() == 10
    assert paired.main_role.isna().all()
    assert paired.recent_mastery_points.eq(0).all()
    assert "population_weight" not in paired


def test_fixed_numeric_cuts_keep_ties_and_survive_subsetting_and_row_order(profiles):
    reference = build_reference(profiles, "test-source")
    banded = prepare_audience(profiles, reference)
    assert reference["right_closed_score_cuts"] == [280, 460, 640, 820]
    assert banded.groupby("lifetime_mastery_points").activity_band.nunique().eq(1).all()
    shuffled = prepare_audience(profiles.sample(frac=1, random_state=42), reference).sort_index()
    pd.testing.assert_series_equal(banded.activity_band, shuffled.activity_band)
    assert banded.loc[banded.rank_group.eq("Diamond+"), "activity_band"].tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    with pytest.raises(DashboardDataError, match="does not match"):
        prepare_audience(profiles.head(5), reference)


def test_exact_cut_is_upper_inclusive(profiles):
    reference = build_reference(profiles, "test-source")
    reference["right_closed_score_cuts"] = [200, 400, 600, 800]
    banded = prepare_audience(profiles, reference)
    assert banded.loc[banded.lifetime_mastery_points.eq(200), "activity_band"].eq(1).all()
    assert banded.loc[banded.lifetime_mastery_points.eq(300), "activity_band"].eq(2).all()


def test_medians_are_unweighted_and_counts_reconcile(profiles):
    banded = prepare_audience(profiles, build_reference(profiles, "test-source"))
    summary = concentration_cells(banded)
    for window in WINDOWS:
        cells = summary.loc[summary.window.eq(window)]
        assert cells.n.sum() == 40
        row = cells.loc[cells.activity_band.eq(1) & cells.rank_group.eq("Iron-Silver")].iloc[0]
        values = banded.loc[banded.activity_band.eq(1) & banded.rank_group.eq("Iron-Silver"), f"{window}_top1_share"]
        assert row["median"] == pytest.approx(values.median())
        assert row.q1 == pytest.approx(values.quantile(0.25))
        assert row.q3 == pytest.approx(values.quantile(0.75))
    historical = experience_focus_cells(banded.rename(columns={"activity_band": "mastery_band"}))
    assert historical.members.sum() == 40
    assert historical.loc[historical.tier_group.eq("Diamond+"), "members"].sum() == 10


def test_grid_includes_full_concentration_and_preserves_empty_observed_bins(profiles):
    profiles.loc[0, "active_pool_lifetime_top1_share"] = 0
    profiles.loc[1, "active_pool_lifetime_top1_share"] = 1
    banded = prepare_audience(profiles, build_reference(profiles, "test-source"))
    for window in WINDOWS:
        grid = audience_grid(banded, window)
        assert len(grid) == 200
        assert grid.profiles.sum() == 40
        assert grid.profiles.eq(0).any()
        assert grid.focus_bin.between(0, 9).all()
        assert grid.groupby("rank_group").profiles.sum().to_dict() == {r: 10 for r in RANK_GROUPS}
    active = audience_grid(banded, "active_pool_lifetime")
    assert (
        active.loc[
            active.rank_group.eq("Gold-Platinum") & active.activity_band.eq(1) & active.focus_bin.eq(9), "profiles"
        ].item()
        == 1
    )


def test_orientation_preserves_median_quartiles_support_and_scale(profiles):
    banded = prepare_audience(profiles, build_reference(profiles, "test-source"))
    cells = concentration_cells(banded)
    cells = cells.loc[cells.window.eq("active_pool_lifetime")].copy()
    cells["n"] = 10
    cells.loc[cells.activity_band.eq(3) & cells.rank_group.eq("Emerald"), "n"] = 1
    normal = concentration_chart(cells, bands_on_x=False, quartiles=True)
    inverted = concentration_chart(cells, bands_on_x=True, quartiles=True)
    assert normal.layout.yaxis.range == inverted.layout.yaxis.range == (0, 1)
    for band, trace in enumerate(normal.data):
        for rank in range(4):
            other = inverted.data[rank]
            if rank == 2 and band == 2:
                assert pd.isna(trace.y[rank]) and pd.isna(other.y[band])
                assert trace.connectgaps is False
            else:
                assert trace.y[rank] == other.y[band]
                assert trace.error_y.array[rank] == other.error_y.array[band]
                assert trace.error_y.arrayminus[rank] == other.error_y.arrayminus[band]
            assert trace.customdata[rank][:4] == other.customdata[band][:4]


def test_reference_rejects_changed_source_and_invalid_contract(tmp_path, monkeypatch, profiles):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    snapshot = tmp_path / data.DATASET_FILES["players"]
    snapshot.write_bytes(b"test-snapshot-v1")
    reference = build_reference(profiles, hashlib.sha256(snapshot.read_bytes()).hexdigest())
    (tmp_path / "audience_reference.json").write_text(json.dumps(reference))
    assert load_reference() == reference
    snapshot.write_bytes(b"test-snapshot-v2")
    with pytest.raises(DashboardDataError, match="different player snapshot"):
        load_reference()
    reference["right_closed_score_cuts"] = [1, 1, 2, 3]
    with pytest.raises(DashboardDataError, match="increasing"):
        prepare_audience(profiles, reference)


def test_bundled_reference_reproduces_approved_cohort_and_bands():
    reference = load_reference()
    frame = data.load_dataset("players", include_all_tiers=True)
    banded = prepare_audience(frame, reference)
    assert len(banded) == reference["cohort_n"]
    assert banded.tier.eq("GRANDMASTER").sum() == 1
    assert banded.groupby("activity_band").size().tolist() == [3945, 3944, 3944, 3944, 3945]
    assert banded.groupby("lifetime_mastery_points").activity_band.nunique().eq(1).all()
    active = concentration_cells(banded).query("window=='active_pool_lifetime'")
    assert active.n.min() == 313 and active.n.max() == 2425
    assert audience_grid(banded, "lifetime").profiles.sum() == len(banded)
