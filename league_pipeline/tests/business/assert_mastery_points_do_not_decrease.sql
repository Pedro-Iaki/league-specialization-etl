{{ config(severity='warn') }}

-- Champion mastery is cumulative. Treat decreases as a warning because Riot
-- may occasionally correct upstream values, but make the anomaly visible.

with history as (

    select
        puuid,
        champion_key,
        snapshot_date,
        champion_points,
        lag(champion_points) over (
            partition by puuid, champion_key
            order by snapshot_date
        ) as previous_champion_points
    from {{ ref('fct_masteries_history') }}

)

select
    puuid,
    champion_key,
    snapshot_date,
    previous_champion_points,
    champion_points
from history
where champion_points < previous_champion_points
