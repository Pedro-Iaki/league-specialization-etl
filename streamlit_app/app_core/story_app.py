"""Streamlit host for the approved story component and local aggregate queries."""

import json

import streamlit as st
import streamlit.components.v1 as components

from app_core.config import APP_ROOT
from app_core.snapshot_hash import sha256_file
from app_core.story_localization import host_text, load_catalogs
from app_core.story_query import AudienceEngine

ASSETS = APP_ROOT / "story_component"
SNAPSHOTS = APP_ROOT / "data/story"
story_component = components.declare_component("audience_story", path=str(ASSETS))


def render_story():
    """Keep component transport/session state separate from analytical ownership."""
    st.markdown(
        """<style>
        [data-testid="stHeader"], [data-testid="stSidebar"] {display:none}
        .stMainBlockContainer {padding:0 .5rem;max-width:none}
        [data-testid="stAppViewContainer"] {background:#0a1320}
        </style>""",
        unsafe_allow_html=True,
    )
    try:
        revision = snapshot_revision()
        engine = load_engine(revision)
        bootstrap = load_bootstrap(revision, engine)
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.error(host_text("host.snapshot_error", detail=error))
        st.info(host_text("host.snapshot_help"))
        return
    request = story_component(
        bootstrap=bootstrap,
        response=st.session_state.get("story_response"),
        key="audience_story",
        default=None,
    )
    if request is None:
        return
    if not isinstance(request, dict) or not isinstance(request.get("id"), str):
        st.error(host_text("host.invalid_request"))
        return
    if st.session_state.get("story_response", {}).get("id") == request["id"]:
        return
    response = {"id": request["id"]}
    try:
        if set(request) != {"id", "definition"} or len(json.dumps(request)) > 16384:
            raise ValueError("Invalid audience request size or fields.")
        response["data"] = engine.compare(request["definition"])
        json.dumps(response, allow_nan=False)
    except (ValueError, TypeError, KeyError) as error:
        response = {"id": request["id"], "error": str(error)}
    st.session_state["story_response"] = response
    st.rerun()


def snapshot_revision():
    """Invalidate caches when a manually replaced input changes."""
    paths = [
        SNAPSHOTS / name
        for name in [
            "manifest.json",
            "player_profiles.parquet",
            "business_players.parquet",
            "audience_segments_reference.json",
            "player-pool-archetypes-v1.json",
        ]
    ]
    paths += [ASSETS / "public-evidence.json", ASSETS / "evidence-manifest.json"]
    paths += [APP_ROOT / "app_core" / name for name in ["story_query.py", "story_examples.py"]]
    paths += sorted((ASSETS / "locales").glob("*.json"))
    paths += sorted((APP_ROOT / "definitions").glob("*.json"))
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths)


@st.cache_resource(show_spinner=host_text("host.validating"))
def load_engine(revision):
    return AudienceEngine(SNAPSHOTS)


@st.cache_data(show_spinner=False)
def load_bootstrap(revision, _engine):
    """Send summaries and sanitized public evidence, never source rows."""
    manifest = json.loads((ASSETS / "evidence-manifest.json").read_text(encoding="utf8"))
    for name, expected in manifest["files"].items():
        path = ASSETS / name if name == "public-evidence.json" else APP_ROOT / "definitions" / name
        if sha256_file(path, normalize_newlines=True) != expected:
            raise ValueError(f"Story evidence differs from its publication manifest: {name}")
    bootstrap = _engine.bootstrap()
    bootstrap["localization"] = load_catalogs()
    scenario = _engine.manifest["datasets"]["business_players"]["scenario"]
    bootstrap["dates"] = {
        "observed": _engine.reference["as_of_date"],
        "reference": _engine.reference["rank_reference"][0]["recorded_on"],
        "cashStart": scenario["purchase_window_start"],
        "cashEnd": scenario["purchase_window_end"],
    }
    bootstrap["methods"] = json.loads((ASSETS / "public-evidence.json").read_text(encoding="utf8"))
    json.dumps(bootstrap, allow_nan=False)
    return bootstrap
