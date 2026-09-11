{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='mastery_history_id',
    on_schema_change='append_new_columns'
) }}

{% set late_arrival_lookback_days = var('late_arrival_lookback_days') %}
{% set dedup_days_range = var('dedup_days_range') %}
{% set mastery_freshness_days = var('mastery_freshness_days') %}

with source as (

    select
        puuid,
        championId as champion_key,
        to_date(date, 'yyMMdd') as snapshot_date,
        championPoints as champion_points,
        timestamp_millis(lastPlayTime) as last_play_time,
        _ingested_at,
        floor(datediff(DAY, '2009-01-01', snapshot_date) / {{ dedup_days_range }}) as _weekly_bucket
    from {{ ref('bronze_masteries') }} m
    where exists (
        select 1
        from {{ ref('dim_players_history') }} p
        where m.puuid = p.puuid
    )

    {% if is_incremental() %}
    and to_date(date, 'yyMMdd') >= (
        select date_sub(max(snapshot_date), {{ late_arrival_lookback_days }})
        from {{ this }}
    )
    {% endif %}

    qualify row_number() over (
        partition by
            puuid,
            champion_key,
            _weekly_bucket
        order by _ingested_at desc
    ) = 1

)

select
    {{ dbt_utils.generate_surrogate_key(['puuid', 'champion_key', '_weekly_bucket']) }} as mastery_history_id,
    puuid,
    champion_key,
    champion_points,
    last_play_time,
    snapshot_date
from source