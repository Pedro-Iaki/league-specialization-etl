from pathlib import Path
import sys

import pytest

# set python path to include src/extract directory so we can import run_pipeline
# assumes this file's parent always contains the run_pipeline script
EXTRACT_DIR = Path(__file__).resolve().parents[1]
if str(EXTRACT_DIR) not in sys.path:
    sys.path.insert(0, str(EXTRACT_DIR))

import run_pipeline as pl


class EnvFactory:
    """Build temporary .env files for run_pipeline input tests."""

    BASE_VALID = {
        "RIOT_API_KEY": "test-api-key",
        "VERSION": "vtest",
        "PLAYERS_FETCH_DEPTH": "1",
        "FULL_VERIFICATION_POST": "false",
        "REGION": "na1",
        "QUEUE": "RANKED_SOLO_5x5",
        "TIERS": "GOLD",
        "DIVISIONS": "I",
    }

    @classmethod
    def create(
        cls,
        tmp_path: Path,
        name: str,
        overrides: dict[str, str] | None = None,
        remove: set[str] | None = None,
        duplicates: list[tuple[str, str]] | None = None,
    ) -> Path:
        data = dict(cls.BASE_VALID)
        if remove:
            for key in remove:
                data.pop(key, None)
        if overrides:
            data.update(overrides)

        lines = [f"{key}={value}" for key, value in data.items()]
        if duplicates:
            for key, value in duplicates:
                lines.append(f"{key}={value}")

        env_path = tmp_path / f"{name}.env"
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return env_path


def _clear_pipeline_env(monkeypatch: pytest.MonkeyPatch):
    keys = [
        "RIOT_API_KEY",
        "VERSION",
        "PLAYERS_FETCH_DEPTH",
        "FULL_VERIFICATION_POST",
        "REGION",
        "QUEUE",
        "TIERS",
        "DIVISIONS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def pipeline_stub(monkeypatch: pytest.MonkeyPatch):
    """Stub side-effectful runtime parts so tests focus on env/config handling."""

    class DummyClient:
        def __init__(self, api_key: str):
            self.api_key = api_key

    captured: dict[str, object] = {}

    def fake_extraction_loop(config_manifest: dict, api_client) -> bool:
        captured["config_manifest"] = config_manifest
        captured["api_key"] = api_client.api_key
        return True

    monkeypatch.setattr(pl.db, "cleanup_stale_runs", lambda: None)
    monkeypatch.setattr(pl.db, "is_active", lambda: True)
    monkeypatch.setattr(pl.client, "RiotAPIClient", DummyClient)
    monkeypatch.setattr(pl, "extraction_loop", fake_extraction_loop)
    return captured


@pytest.mark.parametrize(
    "case_name,overrides,remove,duplicates,expected",
    [
        ("valid_minimal", {}, set(), None, True),
        ("valid_defaults_for_tiers_divisions", {"TIERS": "DIAMOND,EMERALD", "DIVISIONS": "I,II"}, set(), None, True),
        ("missing_api_key", {}, {"RIOT_API_KEY"}, None, False),
        ("missing_version", {}, {"VERSION"}, None, False),
        ("missing_fetch_depth", {}, {"PLAYERS_FETCH_DEPTH"}, None, False),
        ("missing_region", {}, {"REGION"}, None, False),
        ("missing_queue", {}, {"QUEUE"}, None, False),
        ("extra_variable", {"EXTRA_VAR": "value"}, set(), None, True),
        ("wrong_type_fetch_depth_alpha", {"PLAYERS_FETCH_DEPTH": "abc"}, set(), None, False),
        ("wrong_type_fetch_depth_float", {"PLAYERS_FETCH_DEPTH": "1.25"}, set(), None, False),
        ("duplicate_variable_last_wins", {}, set(), [("PLAYERS_FETCH_DEPTH", "2")], True),
        ("extremely_large_fetch_depth", {"PLAYERS_FETCH_DEPTH": "9999999999999999999999999999999999999999"}, set(), None, False),
		("negative_fetch_depth", {"PLAYERS_FETCH_DEPTH": "-1"}, set(), None, False),
		("unexpected_tier_and_division_values", {"TIERS": "WOOD,GLASS", "DIVISIONS": "X,0"}, set(), None, False),
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
    _clear_pipeline_env(monkeypatch)
    env_path = EnvFactory.create(
        tmp_path=tmp_path,
        name=case_name,
        overrides=overrides,
        remove=remove,
        duplicates=duplicates,
    )

    result = pl.run_pipeline(config_path=env_path)
    assert result is expected

# test if on a valid configuration, the correct data reaches extraction_loop, including the API key and the config manifest
def test_valid_case_passes_manifest_to_extraction_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_stub: dict[str, object],
):
    _clear_pipeline_env(monkeypatch)
    env_path = EnvFactory.create(
        tmp_path=tmp_path,
        name="valid_capture",
        overrides={"PLAYERS_FETCH_DEPTH": "3", "TIERS": "GOLD,SILVER", "DIVISIONS": "I,II"},
    )

    result = pl.run_pipeline(config_path=env_path)
    assert result is True

    manifest = pipeline_stub["config_manifest"]
    assert isinstance(manifest, dict)
    assert manifest["players_fetch_depth"] == 3
    assert manifest["tiers"] == ["GOLD", "SILVER"]
    assert manifest["divisions"] == ["I", "II"]
    assert pipeline_stub["api_key"] == "test-api-key"