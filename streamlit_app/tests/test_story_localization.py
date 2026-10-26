"""Published story languages preserve the display and analytical boundary."""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from app_core.story_localization import CATALOG_DIR, load_catalogs, validate_catalogs


def test_published_catalogs_are_complete():
    catalog = load_catalogs()
    assert len(catalog["messages"]["en"]) > 400
    assert all(isinstance(value, str) and value.strip() for value in catalog["messages"]["pt-BR"].values())
    assert {item["id"] for item in catalog["locales"] if item["status"] == "ready"} == {"en", "pt-BR"}
    assert catalog["defaultLocale"] == "pt-BR"


@pytest.mark.parametrize(
    "failure", ["missing_key", "extra_key", "missing_parameter", "malformed", "markup", "premature_publication"]
)
def test_catalog_contract_rejects_incomplete_or_unsafe_publication(failure):
    catalog = load_catalogs()
    values = copy.deepcopy(catalog["messages"])
    manifest = {k: v for k, v in catalog.items() if k != "messages"}
    if failure == "missing_key":
        values["pt-BR"].pop("common.audience")
    elif failure == "extra_key":
        values["pt-BR"]["not_a_message"] = None
    elif failure == "missing_parameter":
        values["pt-BR"]["common.audience"] = "Test missing parameter"
    elif failure == "malformed":
        values["pt-BR"]["chrome.language"] = "Test {broken"
    elif failure == "markup":
        values["pt-BR"]["chrome.language"] = "<script>bad</script>"
    else:
        manifest["locales"][1]["status"] = "ready"
        values["pt-BR"]["common.audience"] = None
    with pytest.raises(ValueError):
        validate_catalogs(manifest, values)


def test_all_published_evidence_has_display_messages():
    catalog = load_catalogs()["messages"]["en"]
    evidence = json.loads((CATALOG_DIR.parent / "public-evidence.json").read_text(encoding="utf8"))
    for run in evidence["runs"]:
        assert catalog[f"evidence.run.{run['date']}.note"] == run["note"]
    for i, text in enumerate(evidence["lineage"]["nodes"]):
        assert catalog[f"evidence.lineage.node{i}"] == text
    assert catalog["evidence.lineage.note"] == evidence["lineage"]["note"]


def test_javascript_catalog_and_formatting_runtime():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is optional development tooling, not a dashboard dependency")
    script = Path(__file__).with_name("story_i18n_runtime.cjs")
    subprocess.run([node, str(script)], check=True, capture_output=True, text=True)


def test_default_can_change_after_translation_is_published():
    catalog = load_catalogs()
    catalog["defaultLocale"] = "pt-BR"
    catalog["locales"][1]["status"] = "ready"
    validate_catalogs(catalog, catalog["messages"])


def test_literal_message_references_exist():
    catalog = load_catalogs()["messages"]["en"]
    web = CATALOG_DIR.parent
    sources = [web / name for name in ["i18n.js", "story.js", "presentation.js", "index.html"]]
    for source in sources:
        text = source.read_text(encoding="utf8")
        for key in re.findall(r"\b(?:t|tx)\(['\"]([\w.]+)['\"]\s*[,)]", text):
            assert key in catalog, (source.name, key)
        for key in re.findall(r'data-i18n(?:-aria)?="([\w.]+)"', text):
            assert key in catalog, (source.name, key)
