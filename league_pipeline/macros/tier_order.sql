{% macro tier_order(tier_column) %}
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
