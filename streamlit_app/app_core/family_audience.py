"""Audience summaries for the adopted families; no discovery or new classifications."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app_core.audience_segments import MINIMUM_EFFECTIVE_PLAYERS, MINIMUM_PLAYERS, segment_counts
from app_core.family_affinity import DEFINITION_PATH, STATE_LABELS, load_family_definition
from app_core.population import effective_sample_size, weighted_quantile


def family_catalogue() -> dict[str, dict]:
    definition = load_family_definition()
    payload = json.loads(DEFINITION_PATH.read_text(encoding='utf-8'))
    families = {family['family_key']: family for family in payload['families']}
    return {key: families[key] for key in definition.family_order}


def primary_categories(frame: pd.DataFrame, family_ids: list[str], top_ids: list[str] | None = None) -> pd.DataFrame:
    """Exclusive categories retain ties/missing states and the whole selected denominator.

    Reaggregate Other before suppression; never sum overlapping affinities or
    already masked estimates. The caller chooses a stable full-base top list.
    """
    selected = frame
    levels = [*family_ids, *STATE_LABELS.values()]
    if top_ids is not None:
        selected = frame.assign(family_category=frame.family_category.where(
            ~frame.family_category.isin(set(family_ids) - set(top_ids)), 'Other families'))
        levels = [*top_ids, 'Other families', *STATE_LABELS.values()]
    return segment_counts(selected, ['family_category'], levels={'family_category': levels})


def known_mix(frame: pd.DataFrame, column: str, levels: list[str]) -> tuple[pd.DataFrame, float]:
    """A known-trait composition with availability against the whole supplied audience."""
    known = frame.loc[frame[column].isin(levels)]
    total = frame.population_weight.sum()
    coverage = float(known.population_weight.sum() / total) if total else np.nan
    return segment_counts(known, [column], levels={column: levels}), coverage


def supported_median(frame: pd.DataFrame, column: str) -> float:
    valid = frame.loc[np.isfinite(pd.to_numeric(frame[column], errors='coerce')) & frame[column].ge(0)]
    if len(valid) < MINIMUM_PLAYERS or effective_sample_size(valid.population_weight) < MINIMUM_EFFECTIVE_PLAYERS:
        return np.nan
    return float(weighted_quantile(valid[column], valid.population_weight))


def breadth_summary(frame: pd.DataFrame) -> dict[str, float]:
    """Positive coordinates overlap; pool breadth is not within-family membership."""
    scored = frame.loc[frame.family_state.isin(['primary', 'shared_top'])].copy()
    scored['positive_families'] = [np.count_nonzero(np.asarray(vector) > 0) for vector in scored.family_affinity]
    return {'scored_characters': supported_median(scored, 'scored_pool_champion_count'),
            'positive_families': supported_median(scored, 'positive_families')}
