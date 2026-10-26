"""Streamlit request/replay boundaries and the independently bundled story package."""

import json
from pathlib import Path
from unittest.mock import patch

from app_core.snapshot_hash import sha256_file
from app_core.story_app import ASSETS, SNAPSHOTS
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_invalid_query_returns_error_without_replacing_data():
    request = {"id": "invalid-query", "definition": {"schema_version": 1, "a": {"unrecognized": []}}}
    with patch("app_core.story_app.story_component", return_value=request):
        app = AppTest.from_file(str(APP), default_timeout=45).run()
    assert not app.exception
    assert "Unknown audience filter" in app.session_state["story_response"]["error"]
    assert "data" not in app.session_state["story_response"]


def test_requests_are_session_local_and_replays_do_not_recompute():
    request = {"id": "custom", "definition": {"schema_version": 1, "a": {"archetype_kind": ["Blend"]}}}
    with patch("app_core.story_app.story_component", return_value=request):
        app = AppTest.from_file(str(APP), default_timeout=45).run()
        assert not app.exception
        assert app.session_state["story_response"]["data"]["a"]["profiles"] > 0
        with patch("app_core.story_query.AudienceEngine.compare", side_effect=AssertionError("replayed")):
            app.run()
            assert not app.exception
    with patch("app_core.story_app.story_component", return_value=None):
        other = AppTest.from_file(str(APP), default_timeout=45).run()
    assert not other.exception
    assert "story_response" not in other.session_state


def test_published_evidence_matches_models_and_contains_no_profile_rows():
    manifest = json.loads((ASSETS / "evidence-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        path = ASSETS / name if name == "public-evidence.json" else ASSETS.parent / "definitions" / name
        assert sha256_file(path, normalize_newlines=True) == expected
    evidence = json.loads((ASSETS / "public-evidence.json").read_text())
    assert len(evidence["families"]) == 25 and len(evidence["components"]) == 8
    assert len(evidence["runs"]) == 2
    assert "players" not in evidence and "business_players" not in evidence
    snapshot = json.loads((SNAPSHOTS / "manifest.json").read_text())
    assert set(snapshot["datasets"]) == {"players", "business_players"}
    for item in snapshot["datasets"].values():
        assert sha256_file(SNAPSHOTS / item["file"]) == item["sha256"]
