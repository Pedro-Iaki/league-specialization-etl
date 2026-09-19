{{ config(materialized='table', file_format='delta') }}

-- One row per champion in dim_champions.
--
-- 1. explode each player's champions_sample so a player shows up once for
--    every champion in their recent sample (that is the "playerbase" test)
-- 2. average that player's lane shares across every player in the champion's
--    playerbase (each player counts equally)
-- 3. left join from dim_champions so champions nobody has sampled still get
--    a row (player_count = 0, null avgs)

with player_champions as (

    select
        player_id,
        explode(champions_sample) as champion_key,
        top_pct,
        jungle_pct,
        middle_pct,
        bottom_pct,
        support_pct
    from {{ ref('dim_players_naive_role_distribution') }}
    where champions_sample is not null

),

champion_avgs as (

    select
        champion_key,
        count(distinct player_id) as player_count,
        -- avg() skips nulls, so players whose sampled champions had no
        -- position data (null pcts) don't drag the averages toward zero
        avg(top_pct)              as avg_top_pct,
        avg(jungle_pct)           as avg_jungle_pct,
        avg(middle_pct)           as avg_middle_pct,
        avg(bottom_pct)           as avg_bottom_pct,
        avg(support_pct)          as avg_support_pct
    from player_champions
    group by champion_key

)

select
    c.key                                       as champion_key,
    c.name                                      as champion_name,
    coalesce(a.player_count, 0)                 as player_count,
    a.avg_top_pct,
    a.avg_jungle_pct,
    a.avg_middle_pct,
    a.avg_bottom_pct,
    a.avg_support_pct
from {{ ref('dim_champions') }} c
left join champion_avgs a
    on c.key = a.champion_key