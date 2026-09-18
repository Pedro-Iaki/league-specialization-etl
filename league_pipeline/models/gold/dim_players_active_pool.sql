{{ config(materialized='table', file_format='delta') }}

with active_champions as (

    select
        player_id,
        champion_key
    from {{ ref('fct_players_champion_activity') }}
    where is_active

),

aggregated as (

    select
        player_id,
        sort_array(collect_list(cast(champion_key as string))) as active_champion_ids,
        count(*) as active_champion_count
    from active_champions
    group by player_id

)

select
    p.puuid as player_id,
    coalesce(a.active_champion_ids, array()) as active_champion_ids,
    coalesce(a.active_champion_count, 0) as active_champion_count
from {{ ref('dim_players_current') }} p
left join aggregated a
    on p.puuid = a.player_id