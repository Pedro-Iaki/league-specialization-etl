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
        count(*) as lifetime_champion_count,
        sum(champion_points) as lifetime_mastery_points,
        max(case when points_rank = 1 then champion_key end) as lifetime_primary_champion_key,
        max(case when points_rank = 1 then champion_name end) as lifetime_primary_champion_name,
        max(case when points_rank = 1 then champion_points end) as top_champion_points
    from mastery
    group by player_id

),

expected as (

    select
        p.puuid as player_id,
        coalesce(m.lifetime_champion_count, 0) as lifetime_champion_count,
        coalesce(m.lifetime_mastery_points, 0) as lifetime_mastery_points,
        m.lifetime_primary_champion_key,
        m.lifetime_primary_champion_name,
        {{ dbt_utils.safe_divide(
            'm.top_champion_points',
            'm.lifetime_mastery_points'
        ) }} as lifetime_top1_share
    from {{ ref('dim_players_current') }} p
    left join aggregated m on p.puuid = m.player_id

),

actual as (

    select
        player_id,
        lifetime_champion_count,
        lifetime_mastery_points,
        lifetime_primary_champion_key,
        lifetime_primary_champion_name,
        lifetime_top1_share
    from {{ ref('fct_players_lifetime_mastery_profile') }}

)

select coalesce(e.player_id, a.player_id) as player_id
from expected e
full outer join actual a on e.player_id = a.player_id
where e.player_id is null
   or a.player_id is null
   or e.lifetime_champion_count <> a.lifetime_champion_count
   or e.lifetime_mastery_points <> a.lifetime_mastery_points
   or not (e.lifetime_primary_champion_key <=> a.lifetime_primary_champion_key)
   or not (e.lifetime_primary_champion_name <=> a.lifetime_primary_champion_name)
   or not (e.lifetime_top1_share <=> a.lifetime_top1_share)
