"""Language catalogs and an explicit rendering adapter; data and widget values stay canonical.

English message strings are stable catalog keys. Their displayed English and Portuguese
copy lives in locales/en.json and locales/pt.json. Numeric/schema values are never translated.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as _st
from streamlit.delta_generator import DeltaGenerator

LOCALE_DIR = Path(__file__).resolve().parents[1] / "locales"
LANGUAGE_KEY = "dashboard_language"
_SLOT = re.compile(r"\{p\d+\}")


def current_language() -> str:
    value = _st.session_state.get(LANGUAGE_KEY, "EN")
    return value if value in {"EN", "PT"} else "EN"


@functools.lru_cache(maxsize=8)
def _catalog(language: str, version: int) -> tuple[dict[str, str], list[tuple[re.Pattern, str, str]]]:
    values = json.loads((LOCALE_DIR / f"{language.lower()}.json").read_text(encoding="utf-8"))
    patterns = []
    for key, value in values.items():
        slots = _SLOT.findall(key)
        if not slots:
            continue
        pieces = _SLOT.split(key)
        # Specific sentences precede shorter, more generic templates.
        expression = re.escape(pieces[0])
        for slot, piece in zip(slots, pieces[1:], strict=True):
            expression += f"(?P<{slot[1:-1]}>.*?)" + re.escape(piece)
        patterns.append((re.compile("^" + expression + "$", re.DOTALL), value, key))
    patterns.sort(key=lambda item: len(item[0].pattern), reverse=True)
    return values, patterns


@functools.lru_cache(maxsize=8192)
def _translate(message: str, language: str, version: int) -> str:
    values, patterns = _catalog(language, version)
    if message in values:
        return values[message]
    for separator in (", ", " / ", " × ", "="):
        pieces = message.split(separator)
        if len(pieces) > 1 and all(piece in values for piece in pieces):
            return separator.join(_translate(piece, language, version) for piece in pieces)
    for pattern, template, key in patterns:
        match = pattern.fullmatch(message)
        if match:
            result = template
            for slot, value in match.groupdict().items():
                # A placeholder may itself contain a display label, e.g. a role.
                technical_version = any(f"{term} {{{slot}}}" in key for term in ("generator", "patch:"))
                translated = _translate(value, language, version) if value != message and not technical_version else value
                result = result.replace("{" + slot + "}", translated)
            return result
    if language == "PT" and re.fullmatch(r"\$?[+−-]?\d[\d,.]*(?:%|K|M)?", message):
        number = message.removeprefix("$").translate(str.maketrans({".": ",", ",": "."}))
        return values.get("$", "$") + number if message.startswith("$") else number
    if language != "EN":
        english_version = (LOCALE_DIR / "en.json").stat().st_mtime_ns
        return _translate(message, "EN", english_version)
    return message


def t(message: Any, **parameters: Any) -> Any:
    """Translate a catalog key, with optional named substitutions; unknown copy falls back."""
    if not isinstance(message, str):
        return message
    language = current_language()
    version = (LOCALE_DIR / f"{language.lower()}.json").stat().st_mtime_ns
    translated = _translate(message, language, version)
    for name, value in parameters.items():
        translated = translated.replace("{" + name + "}", str(t(str(value))))
    return translated


def language_selector() -> None:
    """Render once in the app shell, above the active page; selection survives navigation."""
    def select() -> None:
        language = _st.session_state.get("_dashboard_language_choice") or current_language()
        _st.session_state[LANGUAGE_KEY] = language
        if _st.session_state.get("_dashboard_language_choice") is None:
            _st.session_state["_dashboard_language_choice"] = language

    if "_dashboard_language_choice" not in _st.session_state:
        _st.session_state["_dashboard_language_choice"] = current_language()
    with _st.columns([5, 1])[1]:
        _st.segmented_control(
            t("Language"), ["EN", "PT"],
            key="_dashboard_language_choice", on_change=select,
        )


def localize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy only presentation data; numeric types, canonical source frames and keys remain intact."""
    result = frame.copy()
    for column in result:
        if pd.api.types.infer_dtype(result[column], skipna=True) in {"string", "unicode", "mixed", "mixed-integer"} \
                or isinstance(result[column].dtype, pd.CategoricalDtype):
            result[column] = result[column].map(lambda value: t(value) if isinstance(value, str) else value)
    result.columns = [t(column) for column in result.columns]
    if isinstance(result.index, pd.CategoricalIndex) or result.index.dtype == object:
        result.index = result.index.map(t)
    result.index.names = [t(name) for name in result.index.names]
    return result


def _strings(value):
    if isinstance(value, str):
        return t(value)
    if isinstance(value, dict):
        return {key: _strings(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strings(item) for item in value]
    return value


def localize_figure(figure: go.Figure) -> go.Figure:
    """Translate Plotly display properties without changing numbers or analysis inputs."""
    payload = figure.to_dict()
    for trace in payload["data"]:
        for key in ("name", "text", "hovertext", "hovertemplate", "texttemplate"):
            if key in trace:
                trace[key] = _strings(trace[key])
        for key in ("x", "y", "z", "customdata", "labels"):
            if key in trace and hasattr(trace[key], "tolist"):
                trace[key] = _strings(trace[key].tolist())
            elif key in trace and isinstance(trace[key], (list, tuple)):
                trace[key] = _strings(trace[key])
        for key in ("marker", "line"):
            if key in trace and "colorbar" in trace[key]:
                trace[key]["colorbar"] = _strings(trace[key]["colorbar"])
        if "colorbar" in trace:
            trace["colorbar"] = _strings(trace["colorbar"])
    payload["layout"] = _strings(payload.get("layout", {}))
    # category ordering must match translated display coordinates.
    localized = go.Figure(payload)
    localized.update_layout(separators=",." if current_language() == "PT" else ".,")
    return localized


_TEXT_METHODS = {
    "markdown", "caption", "title", "header", "subheader", "text", "info", "warning", "error", "success",
    "expander", "button", "toggle", "checkbox", "slider", "number_input", "selectbox", "multiselect", "radio",
    "segmented_control", "select_slider", "text_input", "text_area", "metric", "link_button", "popover",
}
_CHOICES = {"selectbox", "multiselect", "radio", "segmented_control", "select_slider"}
_WIDGETS = _CHOICES | {"button", "toggle", "checkbox", "slider", "number_input", "text_input", "text_area"}


class LocalizedStreamlit:
    """Scoped adapter for page/UI imports. It never patches the Streamlit module."""

    def __init__(self, target):
        self._target = target

    def __enter__(self):
        self._target.__enter__()
        return self

    def __exit__(self, *args):
        return self._target.__exit__(*args)

    def __getattr__(self, name):
        target = getattr(self._target, name)
        if isinstance(target, DeltaGenerator):
            return LocalizedStreamlit(target)
        if name not in _TEXT_METHODS | {"columns", "container", "empty", "tabs", "write", "dataframe", "table", "plotly_chart", "Page", "page_link", "set_page_config"}:
            return target

        def localized(*args, **kwargs):
            args = list(args)
            if name in _WIDGETS and "key" not in kwargs:
                caller = sys._getframe(1)
                identity = f"{caller.f_code.co_filename}:{caller.f_lineno}:{name}:{args[0] if args else kwargs.get('label', '')}"
                kwargs["key"] = "locale_widget_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
            if name in _TEXT_METHODS:
                if args:
                    args[0] = t(args[0])
                for key in ("label", "body", "help", "placeholder"):
                    if key in kwargs:
                        kwargs[key] = t(kwargs[key])
            if name == "metric":
                for index in (1, 2):
                    if len(args) > index:
                        args[index] = t(args[index])
                for key in ("value", "delta"):
                    if key in kwargs:
                        kwargs[key] = t(kwargs[key])
            if name in _CHOICES:
                original = kwargs.get("format_func", str)
                language = current_language()
                version = (LOCALE_DIR / f"{language.lower()}.json").stat().st_mtime_ns
                # Widget serializers may call this after the script has ended.
                # Bind the displayed language instead of reading session state there.
                kwargs["format_func"] = lambda value: _translate(str(original(value)), language, version)
            if name == "tabs":
                if args:
                    args[0] = [t(label) for label in args[0]]
                elif "tabs" in kwargs:
                    kwargs["tabs"] = [t(label) for label in kwargs["tabs"]]
            if name in {"Page", "page_link", "set_page_config"}:
                for key in ("title", "label", "page_title", "help"):
                    if key in kwargs:
                        kwargs[key] = t(kwargs[key])
            if name in {"dataframe", "table"}:
                if args and isinstance(args[0], pd.DataFrame):
                    args[0] = localize_frame(args[0])
                elif isinstance(kwargs.get("data"), pd.DataFrame):
                    kwargs["data"] = localize_frame(kwargs["data"])
            if name == "write":
                args = [localize_frame(item) if isinstance(item, pd.DataFrame) else t(item) for item in args]
            if name == "plotly_chart":
                if args and isinstance(args[0], go.Figure):
                    args[0] = localize_figure(args[0])
                elif isinstance(kwargs.get("figure_or_data"), go.Figure):
                    kwargs["figure_or_data"] = localize_figure(kwargs["figure_or_data"])
            result = target(*args, **kwargs)
            if isinstance(result, DeltaGenerator):
                return LocalizedStreamlit(result)
            if isinstance(result, list) and all(isinstance(item, DeltaGenerator) for item in result):
                return [LocalizedStreamlit(item) for item in result]
            return result

        return localized


st = LocalizedStreamlit(_st)
