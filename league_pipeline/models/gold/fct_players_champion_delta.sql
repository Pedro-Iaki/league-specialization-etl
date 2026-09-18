{{ config(materialized='table', file_format='delta') }}

with deduped as (

    select
        puuid,
        champion_key,
        snapshot_date,
        champion_points,
        last_play_time

    from {{ ref('fct_masteries_history') }}

    qualify row_number() over (
        partition by puuid, champion_key, snapshot_date
        order by last_play_time desc, champion_points desc
    ) = 1

),

deltas as (

    select
        {{ dbt_utils.generate_surrogate_key([
            'puuid',
            'champion_key',
            'snapshot_date'
        ]) }} as champion_delta_id,

        puuid,
        champion_key,
        snapshot_date,

        champion_points - lag(champion_points) over (
            partition by puuid, champion_key
            order by snapshot_date
        ) as points_delta

    from deduped

)

select *
from deltas
where points_delta != 0