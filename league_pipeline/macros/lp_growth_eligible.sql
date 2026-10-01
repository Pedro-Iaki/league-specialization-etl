{% macro lp_growth_eligible(lp_delta, games_delta) %}
    (
        {{ games_delta }} > 0
        and abs({{ lp_delta }}) <= {{ var('max_abs_lp_per_game_for_growth', 50) }} * {{ games_delta }}
    )
{% endmacro %}
