{% macro absolute_lp(tier_column, division_column, league_points_column) %}
    -- Collapses tier + division + league_points into one continuous LP scale
    -- so movement can be diffed across division/tier boundaries without the
    -- 0-100 reset on league_points corrupting the delta. Divisions run IV
    -- (lowest) to I (highest) within a tier; Master/GM/Challenger have no
    -- divisions and share one continuous band, since promotion between them
    -- reflects a leaderboard cutoff, not a fixed LP jump.
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
    + (
        case
            when {{ tier_column }} in ('MASTER', 'GRANDMASTER', 'CHALLENGER') then 0
            else ({{ var('divisions_per_tier', 4) }} - {{ division_column }}) * {{ var('lp_per_division', 100) }}
        end
    )
    + coalesce({{ league_points_column }}, 0)
{% endmacro %}