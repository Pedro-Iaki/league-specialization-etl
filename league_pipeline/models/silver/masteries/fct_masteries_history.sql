{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='mastery_history_id',
    on_schema_change='append_new_columns'
) }}

with source as (

    select
        puuid,
        championId as champion_key,
        to_date(date, 'yyMMdd') as snapshot_date,
        championPoints as champion_points,
        timestamp_millis(lastPlayTime) as last_play_time,
        _ingested_at
    from {{ ref('bronze_masteries') }}

    {% if is_incremental() %}
    where _ingested_at > (select max(valid_from) from {{ this }})
    {% endif %}

),

{% set dedup_days_range = 7 %}

deduped as (

    select *
    from source
    qualify row_number() over (
        partition by
            puuid,
            champion_key,
            floor(datediff(DAY, '2009-01-01', snapshot_date) / {{ dedup_days_range }})
        order by _ingested_at desc
    ) = 1

)

select
    {{ dbt_utils.generate_surrogate_key(['puuid', 'champion_key', 'snapshot_date']) }} as mastery_history_id,
    puuid,
    champion_key,
    champion_points,
    last_play_time,
    snapshot_date as valid_from
from deduped