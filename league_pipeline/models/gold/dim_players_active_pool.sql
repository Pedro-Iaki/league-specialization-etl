{{ config(materialized='table', file_format='delta') }}

with active_champions as (

    select
        player_id,
        champion_key,
        previous_snapshot_date,
        snapshot_date,
        last_played_at
    from {{ ref('fct_players_champion_activity') }}
    where is_active

),

aggregated as (

    select
        player_id,
        max(previous_snapshot_date) as previous_snapshot_date,
        max(snapshot_date) as snapshot_date,
        
        sort_array(collect_list(cast(champion_key as string))) as active_champion_ids,
        count(champion_key) as active_champion_count,
        
        sort_array(collect_list(
            case 
                when last_played_at <= 1
                then cast(champion_key as string) 
            end
        )) as recent_champion_ids,
        count(
            case 
                when last_played_at <= 1
                then champion_key 
            end
        ) as recent_champion_count
        
    from active_champions
    group by player_id

),

player_role_sums as (

    select
        ac.player_id,
        sum(cr.avg_top_pct)     as sum_top,
        sum(cr.avg_jungle_pct)  as sum_jungle,
        sum(cr.avg_middle_pct)  as sum_middle,
        sum(cr.avg_bottom_pct)  as sum_bottom,
        sum(cr.avg_support_pct) as sum_support
    from active_champions ac
    join {{ ref('dim_champion_role_weights') }} cr
        on ac.champion_key = cr.champion_key
    group by ac.player_id

),

main_role as (

    select
        player_id,
        role_name,
        role_weight
    from (
        select player_id, 'TOP' as role_name, sum_top as role_weight from player_role_sums
        union all
        select player_id, 'JUNGLE' as role_name, sum_jungle as role_weight from player_role_sums
        union all
        select player_id, 'MIDDLE' as role_name, sum_middle as role_weight from player_role_sums
        union all
        select player_id, 'BOTTOM' as role_name, sum_bottom as role_weight from player_role_sums
        union all
        select player_id, 'SUPPORT' as role_name, sum_support as role_weight from player_role_sums
    )

    qualify row_number() over (
        partition by player_id 
        order by role_weight desc, role_name asc
    ) = 1

)

select
    p.puuid as player_id,
    a.previous_snapshot_date,
    a.snapshot_date,
    coalesce(a.active_champion_ids, array()) as active_champion_ids,
    coalesce(a.active_champion_count, 0) as active_champion_count,
    coalesce(a.recent_champion_ids, array()) as recent_champion_ids,
    coalesce(a.recent_champion_count, 0) as recent_champion_count,
    m.role_name as main_role,
    m.role_weight as main_role_weight
from {{ ref('dim_players_current') }} p
left join aggregated a
    on p.puuid = a.player_id
left join main_role m
    on p.puuid = m.player_id