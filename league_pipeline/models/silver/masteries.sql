{{ config(
    materialized='table',
    file_format='delta',
    on_schema_change='append_new_columns'
) }}

with latest_masteries_snapshot as (
    select *, to_date(date, 'yyMMdd') as fetch_date
    from {{ source('bronze', 'masteries') }}
    qualify row_number() over (
        partition by (puuid, championId)
        order by fetch_date desc, _ingested_at desc
    ) = 1
),

select
    {{ dbt_utils.generate_surrogate_key(['puuid', 'championId']) }} as mastery_id,
    puuid,
    championId as champion_key,
    championPoints as champion_points,
    timestamp_millis(lastPlayTime) as last_play_time,
from latest_masteries_snapshot