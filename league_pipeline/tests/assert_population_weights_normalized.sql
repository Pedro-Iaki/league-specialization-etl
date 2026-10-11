{{ config(tags=['population_weighting']) }}

-- Relative weights must average one within each represented scope.
select region, queue
from {{ ref('mart_player_population_weights') }}
where population_weight is not null
group by region, queue
having abs(avg(population_weight) - 1.0) > 0.00000001
    or min(population_weight) <= 0
    or min(covered_population_share) <= 0
    or max(covered_population_share) > 1.00000001
