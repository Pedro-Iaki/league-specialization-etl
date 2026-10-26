"""Validate and publish story display catalogs without changing analytical identifiers."""

import json
import re

from app_core.config import APP_ROOT

CATALOG_DIR = APP_ROOT / "story_component/locales"
PLACEHOLDERS = re.compile(r"\{(\w+)\}")


def host_text(key, **params):
    """Use the published default for startup; English remains the recovery fallback."""
    value = json.loads((CATALOG_DIR / "en.json").read_text(encoding="utf8"))[key]
    try:
        manifest = json.loads((CATALOG_DIR / "manifest.json").read_text(encoding="utf8"))
        locale = next(item for item in manifest["locales"] if item["id"] == manifest["defaultLocale"])
        if locale["status"] == "ready":
            value = json.loads((CATALOG_DIR / locale["file"]).read_text(encoding="utf8")).get(key) or value
    except (OSError, ValueError, KeyError, StopIteration):
        pass  # Recovery copy must remain readable when a locale publication is invalid.
    return value.format(**params)


def load_catalogs():
    manifest = json.loads((CATALOG_DIR / "manifest.json").read_text(encoding="utf8"))
    catalogs = {
        item["id"]: json.loads((CATALOG_DIR / item["file"]).read_text(encoding="utf8")) for item in manifest["locales"]
    }
    validate_catalogs(manifest, catalogs)
    return {**manifest, "messages": catalogs}


def validate_catalogs(manifest, catalogs):
    if manifest["fallbackLocale"] != "en" or not any(
        item["id"] == "en" and item["status"] == "ready" for item in manifest["locales"]
    ):
        raise ValueError("English must remain the published fallback catalog")
    if not any(item["id"] == manifest["defaultLocale"] and item["status"] == "ready" for item in manifest["locales"]):
        raise ValueError("The default locale must be published")
    base = catalogs[manifest["fallbackLocale"]]
    if not base or any(not isinstance(value, str) or not value.strip() for value in base.values()):
        raise ValueError("English source messages must be nonempty strings")
    for locale in manifest["locales"]:
        if locale["status"] not in {"draft", "ready"}:
            raise ValueError("Unknown locale publication status")
        messages = catalogs[locale["id"]]
        if set(messages) != set(base):
            raise ValueError(f"Catalog keys differ: {locale['id']}")
        for key, value in messages.items():
            if value is None and locale["status"] == "draft":
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Empty published message: {locale['id']}/{key}")
            if set(PLACEHOLDERS.findall(value)) != set(PLACEHOLDERS.findall(base[key])):
                raise ValueError(f"Message placeholders differ: {locale['id']}/{key}")
            if re.search(r"[{}]", PLACEHOLDERS.sub("", value)):
                raise ValueError(f"Malformed message placeholder: {locale['id']}/{key}")
            if re.search(r"<\s*/?\s*[A-Za-z][^>]*>", value):
                raise ValueError(f"Catalog messages must be plain text: {key}")
