{% macro playstyle_score(archetype, top1_share, favoured_share, hhi, normalized_entropy, favoured_count) -%}
    {% set weights = var('playstyle_feature_weights') %}
    {% set profile = var('playstyle_profiles')[archetype] %}
    {% set max_count = var('favoured_champion_max_count', 10) %}
    (
        {{ weights['top1_share'] }}
            * (1 - abs({{ top1_share }} - {{ profile['top1_share'] }}))
        + {{ weights['favoured_share'] }}
            * (1 - abs({{ favoured_share }} - {{ profile['favoured_share'] }}))
        + {{ weights['hhi'] }}
            * (1 - abs({{ hhi }} - {{ profile['hhi'] }}))
        + {{ weights['normalized_entropy'] }}
            * (1 - abs({{ normalized_entropy }} - {{ profile['normalized_entropy'] }}))
        + {{ weights['favoured_count'] }}
            * (1 - abs(
                least(greatest((cast({{ favoured_count }} as double) - 1) / {{ max_count - 1 }}.0, 0), 1)
                - {{ profile['favoured_count'] }}
            ))
    )
{%- endmacro %}
