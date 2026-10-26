"""Guided questions; canonical definitions also seed the custom builder."""

import json
from pathlib import Path

names = json.loads((Path(__file__).resolve().parents[1] / "definitions/player-pool-archetypes-v1.json").read_text())[
    "names"
]
EXAMPLES = [
    {
        "id": "participation",
        "title": "Competitive frequency",
        "first_page": 2,
        "question": "Among people with high accumulated play, how do less and more frequent competitors differ?",
        "field": "engagement_band",
        "options": [
            {"id": "low", "label": "Fewer than 100 competitive games", "value": ["E1", "E2"]},
            {"id": "middle", "label": "100-249 competitive games", "value": ["E3"]},
            {"id": "high", "label": "At least 250 competitive games", "value": ["E4", "E5"]},
        ],
        "defaults": ["low", "high"],
        "definition": {
            "schema_version": 1,
            "shared": {"activity_band": ["A5"]},
            "a": {"engagement_band": ["E1", "E2"]},
            "b": {"engagement_band": ["E4", "E5"]},
        },
    },
    {
        "id": "standing",
        "title": "Competitive standing",
        "first_page": 3,
        "question": "Among people with similar competitive frequency, how do lower- and higher-standing groups differ?",
        "field": "rank_group",
        "options": [
            {"id": "lowest", "label": "Lowest standing", "value": ["Lowest"]},
            {"id": "medium", "label": "Medium standing", "value": ["Medium"]},
            {"id": "upper", "label": "High or Highest standing", "value": ["High", "Highest"]},
        ],
        "defaults": ["lowest", "upper"],
        "definition": {
            "schema_version": 1,
            "shared": {"engagement_band": ["E3"]},
            "a": {"rank_group": ["Lowest"]},
            "b": {"rank_group": ["High", "Highest"]},
        },
    },
    {
        "id": "interests",
        "title": "Character interests",
        "first_page": 4,
        "question": "How do people with different primary character interests differ in activity, standing and mixtures?",
        "field": "archetype",
        "options": [
            {
                "id": f"A{i + 1}",
                "label": n + (" (ranged sustained attackers)" if i == 2 else ""),
                "value": {"mode": "primary", "ids": [f"A{i + 1}"]},
            }
            for i, n in enumerate(names)
        ],
        "defaults": ["A1", "A3"],
        "definition": {
            "schema_version": 1,
            "shared": {"primary_required": True},
            "a": {"archetype": {"mode": "primary", "ids": ["A1"]}},
            "b": {"archetype": {"mode": "primary", "ids": ["A3"]}},
        },
    },
    {
        "id": "mixtures",
        "title": "Single versus blended interests",
        "first_page": 4,
        "question": "Within the same primary interest, how do single-expression and blended profiles differ?",
        "field": "archetype_kind",
        "options": [
            {"id": "single", "label": "One expressed interest (Single)", "value": ["Single"]},
            {"id": "blend", "label": "Several expressed interests (Blend)", "value": ["Blend"]},
        ],
        "defaults": ["single", "blend"],
        "definition": {
            "schema_version": 1,
            "shared": {"archetype": {"mode": "primary", "ids": ["A4"]}},
            "a": {"archetype_kind": ["Single"]},
            "b": {"archetype_kind": ["Blend"]},
        },
    },
]
