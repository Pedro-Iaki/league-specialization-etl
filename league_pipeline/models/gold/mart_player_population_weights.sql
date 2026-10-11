{{ config(materialized='view', tags=['population_weighting']) }}

-- One weight per player and queue. Calculate before any analyst filters.
-- Normalize within each region/queue; their relative population sizes are unknown.
with counts as (
    select region, queue, tier, count(*) as sample_players
    from {{ ref('mart_player_profile') }}
    group by region, queue, tier
), represented as (
    select
        c.*,
        r.population_share,
        r.reference_version,
        r.recorded_on,
        r.review_after,
        sum(case when r.population_share is not null then c.sample_players else 0 end)
            over (partition by c.region, c.queue) as eligible_sample_players,
        coalesce(sum(r.population_share) over (partition by c.region, c.queue), 0.0) as covered_population_share
    from counts c
    left join {{ ref('rank_population_reference') }} r on c.tier = r.tier
)
select
    p.player_id,
    p.region,
    p.queue,
    p.tier,
    p.as_of_date as profile_as_of_date,
    p.snapshot_date as profile_snapshot_date,
    r.sample_players as tier_sample_players,
    r.eligible_sample_players as scope_sample_players,
    case when r.population_share is not null then
        r.sample_players * 1.0 / nullif(r.eligible_sample_players, 0)
    end as sample_tier_share,
    r.population_share as estimated_population_share,
    r.covered_population_share,
    r.population_share / nullif(r.covered_population_share, 0) as supported_target_share,
    r.reference_version,
    r.recorded_on as reference_recorded_on,
    r.review_after as reference_review_after,
    r.population_share / nullif(r.covered_population_share, 0)
        * r.eligible_sample_players / r.sample_players as population_weight
from {{ ref('mart_player_profile') }} p
left join represented r
    on p.region <=> r.region and p.queue <=> r.queue and p.tier <=> r.tier
