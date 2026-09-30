-- The active-pool dimension must reproduce the population, primary champion,
-- count, and names selected by the champion-activity business rule.

with active_champions as (

    select
        player_id,
        champion_key,
        champion_name,
        case
            when recent_total_points > 0 then recent_champion_points
            else 1
        end as pool_points
    from {{ ref('fct_players_champion_activity') }}
    where is_active

),

summaries as (

    select
        player_id,
        count(*) as active_champion_count,
        sort_array(collect_list(champion_name)) as active_champion_names
    from active_champions
    group by player_id

),

primaries as (

    select player_id, champion_key, champion_name
    from active_champions
    qualify row_number() over (
        partition by player_id
        order by pool_points desc, champion_key
    ) = 1

),

expected as (

    select
        p.puuid as player_id,
        coalesce(s.active_champion_count, 0) > 0 as is_active,
        coalesce(s.active_champion_count, 0) as active_champion_count,
        coalesce(s.active_champion_names, cast(array() as array<string>)) as active_champion_names,
        x.champion_key as primary_champion_key,
        x.champion_name as primary_champion_name
    from {{ ref('dim_players_current') }} p
    left join summaries s on p.puuid = s.player_id
    left join primaries x on p.puuid = x.player_id

),

actual as (

    select
        player_id,
        is_active,
        active_champion_count,
        active_champion_names,
        primary_champion_key,
        primary_champion_name
    from {{ ref('dim_players_active_pool') }}

)

select coalesce(e.player_id, a.player_id) as player_id
from expected e
full outer join actual a on e.player_id = a.player_id
where e.player_id is null
   or a.player_id is null
   or e.is_active <> a.is_active
   or e.active_champion_count <> a.active_champion_count
   or not (e.active_champion_names <=> a.active_champion_names)
   or not (e.primary_champion_key <=> a.primary_champion_key)
   or not (e.primary_champion_name <=> a.primary_champion_name)
