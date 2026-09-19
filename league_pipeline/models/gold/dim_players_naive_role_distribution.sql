{{ config(materialized='table', file_format='delta') }}

{% set recent_champion_count = var('role_profile_recent_champion_count', 15) %}

-- One row per player in dim_players_current.
--
-- 1. take each player's N most recently played champions (fct_masteries_current)
-- 2. look up each champion's expected_positions (dim_champions) and explode
--    them, so a flex champion contributes 1 to every lane it can be played in
-- 3. count champions per lane per player
-- 4. pivot into one column per lane and turn counts into shares of all lane
--    slots (so the five pct columns sum to 1 per player)
-- 5. primary_roles = every lane tied for the highest count (array)

with recent_champions as (

    select
        puuid as player_id,
        champion_key,
        last_play_time
    from {{ ref('fct_masteries_current') }}
    -- ignore never-played rows (null / epoch-ish last_play_time)
    where last_play_time is not null
      and last_play_time > timestamp '2009-01-01'
    qualify row_number() over (
        partition by player_id
        order by last_play_time desc, champion_points desc, champion_key
    ) <= {{ recent_champion_count }}

),

sampled as (

    select
        player_id,
        collect_list(champion_key) as champions_sample,
        count(*) as champions_sampled_count
    from recent_champions
    group by player_id

),

champion_roles as (

    select
        rc.player_id,
        rc.champion_key,
        explode(c.expected_positions) as roles
    from recent_champions rc
    inner join {{ ref('dim_champions') }} c
        on rc.champion_key = c.key

),

role_counts as (

    select
        player_id,
        roles,
        count(*) as role_count
    from champion_roles
    where roles is not null
    group by player_id, roles

),

role_pivot as (

    select
        player_id,
        sum(case when roles = 'Top'     then role_count else 0 end) as top_count,
        sum(case when roles = 'Jungle'  then role_count else 0 end) as jungle_count,
        sum(case when roles = 'Middle'  then role_count else 0 end) as middle_count,
        sum(case when roles = 'Bottom'  then role_count else 0 end) as bottom_count,
        sum(case when roles = 'Support' then role_count else 0 end) as support_count,
        sum(role_count) as total_role_count
    from role_counts
    group by player_id

),

player_counts as (

    -- player-centered: start from dim_players_current so players with no
    -- usable mastery data still get a row (zero counts, null pcts)
    select
        p.puuid as player_id,
        coalesce(s.champions_sample, array()) as champions_sample,
        coalesce(s.champions_sampled_count, 0) as champions_sampled_count,
        coalesce(r.top_count, 0)         as top_count,
        coalesce(r.jungle_count, 0)      as jungle_count,
        coalesce(r.middle_count, 0)      as middle_count,
        coalesce(r.bottom_count, 0)      as bottom_count,
        coalesce(r.support_count, 0)     as support_count,
        coalesce(r.total_role_count, 0)  as total_role_count
    from {{ ref('dim_players_current') }} p
    left join sampled s
        on p.puuid = s.player_id
    left join role_pivot r
        on p.puuid = r.player_id

),

with_max as (

    select
        *,
        greatest(top_count, jungle_count, middle_count, bottom_count, support_count) as max_role_count
    from player_counts

)

select
    player_id,
    coalesce(champions_sample, array()) as champions_sample,
    champions_sampled_count,

    -- every lane tied for the highest count; empty array if no lane data
    filter(
        array(
            case when max_role_count > 0 and top_count     = max_role_count then 'Top'     end,
            case when max_role_count > 0 and jungle_count  = max_role_count then 'Jungle'  end,
            case when max_role_count > 0 and middle_count  = max_role_count then 'Middle'  end,
            case when max_role_count > 0 and bottom_count  = max_role_count then 'Bottom'  end,
            case when max_role_count > 0 and support_count = max_role_count then 'Support' end
        ),
        role -> role is not null
    ) as primary_roles,

    {{ dbt_utils.safe_divide('top_count',     'total_role_count') }} as top_pct,
    {{ dbt_utils.safe_divide('jungle_count',  'total_role_count') }} as jungle_pct,
    {{ dbt_utils.safe_divide('middle_count',  'total_role_count') }} as middle_pct,
    {{ dbt_utils.safe_divide('bottom_count',  'total_role_count') }} as bottom_pct,
    {{ dbt_utils.safe_divide('support_count', 'total_role_count') }} as support_pct

from with_max