{{ config(materialized='table', file_format='delta') }}

with source as (

    select
        puuid,
        champion_key,
        snapshot_date,
        champion_points,
        last_play_time

    from {{ ref('fct_masteries_current') }}
),

deltas as (

    select
        {{ dbt_utils.generate_surrogate_key([
            'puuid',
            'champion_key'
        ]) }} as champion_delta_id,

        puuid as player_id,
        champion_key,
        lag(snapshot_date) over (
            partition by puuid, champion_key order by snapshot_date
        ) as previous_snapshot_date,
        snapshot_date,
        datediff(DAY, previous_snapshot_date, snapshot_date) as days_period,
        champion_points - lag(champion_points) over (
            partition by puuid, champion_key
            order by snapshot_date
        ) as points_delta

    from source

)

select *
from deltas
where points_delta != 0