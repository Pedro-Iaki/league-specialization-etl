{% macro rank_score(tier_column, division_column, league_points_column) %}
    (
        case {{ tier_column }}
            when 'IRON' then 0
            when 'BRONZE' then 1
            when 'SILVER' then 2
            when 'GOLD' then 3
            when 'PLATINUM' then 4
            when 'EMERALD' then 5
            when 'DIAMOND' then 6
            when 'MASTER' then 7
            when 'GRANDMASTER' then 7
            when 'CHALLENGER' then 7
        end * {{ var('divisions_per_tier', 4) }} * {{ var('lp_per_division', 100) }}
    )
    + case
        when {{ tier_column }} in ('MASTER', 'GRANDMASTER', 'CHALLENGER') then 0
        else ({{ var('divisions_per_tier', 4) }} - {{ division_column }}) * {{ var('lp_per_division', 100) }}
    end
    + coalesce({{ league_points_column }}, 0)
{% endmacro %}
