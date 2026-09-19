{{ config(materialized='table', file_format='delta') }}

with source as (

    select
        puuid as player_id,
        champion_key,
        snapshot_date,
        champion_points,
        c.name as champion_name,
        last_play_time

    from {{ ref('fct_masteries_history') }}
    left join {{ ref('dim_champions') }} c
        on fct_masteries_history.champion_key = c.key
),

deltas as (

    select
        {{ dbt_utils.generate_surrogate_key([
            'player_id',
            'champion_key'
        ]) }} as champion_delta_id,

        player_id,
        champion_key,
        champion_name,
        lag(snapshot_date) over (
            partition by player_id, champion_key order by snapshot_date
        ) as previous_snapshot_date,
        snapshot_date,
        datediff(DAY, previous_snapshot_date, snapshot_date) as days_period,
        champion_points - lag(champion_points) over (
            partition by player_id, champion_key
            order by snapshot_date
        ) as points_delta

    from source

)

select *
from deltas
where points_delta != 0 and days_period > 0