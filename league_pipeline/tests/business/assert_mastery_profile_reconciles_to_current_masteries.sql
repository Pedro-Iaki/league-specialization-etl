-- Lifetime mastery headline metrics must reconcile to the positive current
-- mastery records used to construct the player profile.

with mastery as (

    select
        m.puuid as player_id,
        m.champion_key,
        c.name as champion_name,
        m.champion_points,
        row_number() over (
            partition by m.puuid
            order by m.champion_points desc, m.champion_key
        ) as points_rank
    from {{ ref('fct_masteries_current') }} m
    left join {{ ref('dim_champions') }} c on m.champion_key = c.key
    where m.champion_points > 0

),

aggregated as (

    select
        player_id,
        count(*) as champions_with_mastery,
        sum(champion_points) as total_mastery_points,
        max(case when points_rank = 1 then champion_key end) as top_champion_key,
        max(case when points_rank = 1 then champion_name end) as top_champion_name,
        max(case when points_rank = 1 then champion_points end) as top_champion_points
    from mastery
    group by player_id

),

expected as (

    select
        p.puuid as player_id,
        coalesce(m.champions_with_mastery, 0) as champions_with_mastery,
        coalesce(m.total_mastery_points, 0) as total_mastery_points,
        m.top_champion_key,
        m.top_champion_name,
        {{ dbt_utils.safe_divide(
            'm.top_champion_points',
            'm.total_mastery_points'
        ) }} as mastery_top1_share
    from {{ ref('dim_players_current') }} p
    left join aggregated m on p.puuid = m.player_id

),

actual as (

    select
        player_id,
        champions_with_mastery,
        total_mastery_points,
        top_champion_key,
        top_champion_name,
        mastery_top1_share
    from {{ ref('fct_players_mastery_profile') }}

)

select coalesce(e.player_id, a.player_id) as player_id
from expected e
full outer join actual a on e.player_id = a.player_id
where e.player_id is null
   or a.player_id is null
   or e.champions_with_mastery <> a.champions_with_mastery
   or e.total_mastery_points <> a.total_mastery_points
   or not (e.top_champion_key <=> a.top_champion_key)
   or not (e.top_champion_name <=> a.top_champion_name)
   or not (e.mastery_top1_share <=> a.mastery_top1_share)
