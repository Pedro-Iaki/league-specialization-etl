{% macro tier_order(tier_column) %}
    -- Ordinal for a ranked tier: 1 (IRON) through 10 (CHALLENGER).
    -- No ELSE branch, so an unrecognised tier resolves to null and shows up as
    -- a gap rather than silently sorting to the bottom of the ladder. Mirrors
    -- the ordering baked into absolute_lp().
    case {{ tier_column }}
        when 'IRON' then 1
        when 'BRONZE' then 2
        when 'SILVER' then 3
        when 'GOLD' then 4
        when 'PLATINUM' then 5
        when 'EMERALD' then 6
        when 'DIAMOND' then 7
        when 'MASTER' then 8
        when 'GRANDMASTER' then 9
        when 'CHALLENGER' then 10
    end
{% endmacro %}


{% macro rank_state_order(tier_column, division_column) %}
    -- Dense ordinal for a (tier, division) ladder rung:
    --   IRON IV = 0, IRON I = 3, BRONZE IV = 4 ... DIAMOND I = 27,
    --   MASTER = 31, GRANDMASTER = 35, CHALLENGER = 39.
    -- Division IV is the bottom rung of a tier and I the top, so the division
    -- term is subtracted. Master/GM/Challenger report division I from the API,
    -- which puts each of them on the top rung of its own tier band and keeps
    -- them correctly ordered relative to one another.
    --
    -- Unlike absolute_lp() this ignores league_points, so a difference of 1
    -- always means "one division up/down" - which is what transition
    -- probabilities need.
    (
        {{ tier_order(tier_column) }} * {{ var('divisions_per_tier', 4) }}
        - coalesce({{ division_column }}, 1)
    )
{% endmacro %}
