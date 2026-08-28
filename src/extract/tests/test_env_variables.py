from pathlib import Path

import pytest

import extract.tests.t_utilities as util

util.set_path_for_extract_modules()
import extract.run_pipeline as pl


@pytest.mark.parametrize(
    "case_name,overrides,remove,duplicates,expected",
    [
        ("valid_minimal", {}, set(), None, True),
        (
            "valid_defaults_for_tiers_divisions",
            {"TIERS": "DIAMOND,EMERALD", "DIVISIONS": "I,II"},
            set(),
            None,
            True,
        ),
        ("missing_api_key", {}, {"RIOT_API_KEY"}, None, False),
        ("missing_version", {}, {"VERSION"}, None, False),
        ("missing_fetch_depth", {}, {"PLAYERS_FETCH_DEPTH"}, None, False),
        ("missing_region", {}, {"REGION"}, None, False),
        ("missing_queue", {}, {"QUEUE"}, None, False),
        ("extra_variable", {"EXTRA_VAR": "value"}, set(), None, True),
        (
            "wrong_type_fetch_depth_alpha",
            {"PLAYERS_FETCH_DEPTH": "abc"},
            set(),
            None,
            False,
        ),
        (
            "wrong_type_fetch_depth_float",
            {"PLAYERS_FETCH_DEPTH": "1.25"},
            set(),
            None,
            False,
        ),
        (
            "duplicate_variable_last_wins",
            {},
            set(),
            [("PLAYERS_FETCH_DEPTH", "2")],
            True,
        ),
        (
            "extremely_large_fetch_depth",
            {"PLAYERS_FETCH_DEPTH": "9999999999999999999999999999999999999999"},
            set(),
            None,
            False,
        ),
        ("negative_fetch_depth", {"PLAYERS_FETCH_DEPTH": "-1"}, set(), None, False),
        (
            "unexpected_tier_and_division_values",
            {"TIERS": "WOOD,GLASS", "DIVISIONS": "X,0"},
            set(),
            None,
            False,
        ),
    ],
)
def test_run_pipeline_env_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_stub: dict[str, object],
    case_name: str,
    overrides: dict[str, str],
    remove: set[str],
    duplicates: list[tuple[str, str]] | None,
    expected: bool,
):
    util._clear_pipeline_env(monkeypatch)
    env_path = util.EnvFactory.create(
        tmp_path=tmp_path,
        name=case_name,
        overrides=overrides,
        remove=remove,
        duplicates=duplicates,
    )

    try:
        result = pl.run_pipeline(config_path=env_path)
        assert result is expected
    except Exception:  # noqa: BLE001
        assert expected is False


# test if on a valid configuration, the correct data reaches extraction_loop, including the API key and the config manifest
def test_valid_case_passes_manifest_to_extraction_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_stub: dict[str, object],
):
    util._clear_pipeline_env(monkeypatch)
    env_path = util.EnvFactory.create(
        tmp_path=tmp_path,
        name="valid_capture",
        overrides={
            "PLAYERS_FETCH_DEPTH": "3",
            "TIERS": "GOLD,SILVER",
            "DIVISIONS": "I,II",
        },
    )

    result = pl.run_pipeline(config_path=env_path)
    assert result is True

    manifest = pipeline_stub["config_manifest"]
    assert isinstance(manifest, dict)
    assert manifest["players_fetch_depth"] == 3
    assert manifest["tiers"] == ["GOLD", "SILVER"]
    assert manifest["divisions"] == ["I", "II"]
    assert pipeline_stub["api_key"] == "test-api-key"
