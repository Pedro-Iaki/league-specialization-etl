{{ config(tags=['population_weighting'], severity='warn') }}

-- Missing tiers can be intentional: warn rather than invalidate conditional estimates.
select region, queue, min(covered_population_share) as covered_population_share
from {{ ref('mart_player_population_weights') }}
group by region, queue
having min(covered_population_share) < {{ var('population_min_coverage', 0.99) }}
