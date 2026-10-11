{{ config(tags=['population_weighting']) }}

-- Mean-one weights alone do not guarantee the correct tier distribution.
with tiers as (
    select region, queue, tier,
        sum(population_weight) as tier_mass,
        max(supported_target_share) as target_share
    from {{ ref('mart_player_population_weights') }}
    where population_weight > 0
    group by region, queue, tier
)
select region, queue, tier
from (
    select *, sum(tier_mass) over (partition by region, queue) as scope_mass
    from tiers
) calibrated
where abs(tier_mass / scope_mass - target_share) > 0.00000001
