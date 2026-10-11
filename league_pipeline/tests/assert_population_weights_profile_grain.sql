{{ config(tags=['population_weighting']) }}

-- Joining weights back to profiles must preserve exactly one row per profile.
with actual as (
    select player_id, region, queue, count(*) as rows_per_profile
    from {{ ref('mart_player_population_weights') }}
    group by player_id, region, queue
), expected as (
    select player_id, region, queue, count(*) as rows_per_profile
    from {{ ref('mart_player_profile') }}
    group by player_id, region, queue
)
select
    coalesce(e.player_id, a.player_id) as player_id,
    coalesce(e.region, a.region) as region,
    coalesce(e.queue, a.queue) as queue
from expected e
full outer join actual a
    on e.player_id <=> a.player_id and e.region <=> a.region and e.queue <=> a.queue
where coalesce(e.rows_per_profile, 0) != 1
   or coalesce(a.rows_per_profile, 0) != 1
