-- A player's per-champion recent gains must add back to the repeated player
-- total, and positive totals must allocate exactly one whole share.

with player_totals as (

    select
        player_id,
        count(distinct recent_total_points) as distinct_stated_totals,
        max(recent_total_points) as stated_total_points,
        sum(recent_champion_points) as calculated_total_points,
        sum(recent_share) as calculated_share,
        count(recent_share) as populated_share_count
    from {{ ref('fct_players_champion_activity') }}
    group by player_id

)

select *
from player_totals
where distinct_stated_totals <> 1
   or stated_total_points <> calculated_total_points
   or (
        stated_total_points > 0
        and (
            calculated_share is null
            or abs(calculated_share - 1.0) > 1e-9
        )
   )
   or (stated_total_points = 0 and populated_share_count > 0)
