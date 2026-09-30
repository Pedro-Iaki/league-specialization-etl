{{ config(materialized='table', file_format='delta') }}

{% set recent_champion_count = var('role_profile_recent_champion_count', 15) %}

with recent_champions as (

    select
        puuid as player_id,
        champion_key,
        last_play_time
    from {{ ref('fct_masteries_current') }}
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
        r.player_id,
        explode(c.expected_positions) as role
    from recent_champions r
    inner join {{ ref('dim_champions') }} c
        on r.champion_key = c.key

),

role_counts as (

    select
        player_id,
        role,
        count(*) as role_count
    from champion_roles
    where role is not null
    group by player_id, role

),

role_totals as (

    select
        player_id,
        sum(case when role = 'Top' then role_count else 0 end) as top_count,
        sum(case when role = 'Jungle' then role_count else 0 end) as jungle_count,
        sum(case when role = 'Middle' then role_count else 0 end) as middle_count,
        sum(case when role = 'Bottom' then role_count else 0 end) as bottom_count,
        sum(case when role = 'Support' then role_count else 0 end) as support_count,
        sum(role_count) as total_role_count
    from role_counts
    group by player_id

),

player_roles as (

    select
        p.puuid as player_id,
        coalesce(s.champions_sample, array()) as champions_sample,
        coalesce(s.champions_sampled_count, 0) as champions_sampled_count,
        coalesce(r.top_count, 0) as top_count,
        coalesce(r.jungle_count, 0) as jungle_count,
        coalesce(r.middle_count, 0) as middle_count,
        coalesce(r.bottom_count, 0) as bottom_count,
        coalesce(r.support_count, 0) as support_count,
        coalesce(r.total_role_count, 0) as total_role_count
    from {{ ref('dim_players_current') }} p
    left join sampled s on p.puuid = s.player_id
    left join role_totals r on p.puuid = r.player_id

),

with_max as (

    select
        *,
        greatest(top_count, jungle_count, middle_count, bottom_count, support_count)
            as max_role_count
    from player_roles

)

select
    player_id,
    champions_sample,
    champions_sampled_count,
    filter(
        array(
            case when max_role_count > 0 and top_count = max_role_count then 'Top' end,
            case when max_role_count > 0 and jungle_count = max_role_count then 'Jungle' end,
            case when max_role_count > 0 and middle_count = max_role_count then 'Middle' end,
            case when max_role_count > 0 and bottom_count = max_role_count then 'Bottom' end,
            case when max_role_count > 0 and support_count = max_role_count then 'Support' end
        ),
        role -> role is not null
    ) as primary_roles,
    {{ dbt_utils.safe_divide('top_count', 'total_role_count') }} as top_pct,
    {{ dbt_utils.safe_divide('jungle_count', 'total_role_count') }} as jungle_pct,
    {{ dbt_utils.safe_divide('middle_count', 'total_role_count') }} as middle_pct,
    {{ dbt_utils.safe_divide('bottom_count', 'total_role_count') }} as bottom_pct,
    {{ dbt_utils.safe_divide('support_count', 'total_role_count') }} as support_pct
from with_max
