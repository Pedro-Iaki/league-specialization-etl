{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='mastery_history_id',
    on_schema_change='append_new_columns'
) }}

{% set late_arrival_lookback_days = var('late_arrival_lookback_days') %}

with source as (

    select
        m.puuid,
        m.championId as champion_key,
        to_date(m.date, 'yyMMdd') as snapshot_date,
        m.championPoints as champion_points,
        timestamp_millis(m.lastPlayTime) as last_play_time,
        m._ingested_at,
        m.patch
    from {{ ref('bronze_masteries') }} m
    inner join {{ ref('dim_champions') }} c
        on m.championId = c.key
    where exists (
        select 1
        from {{ ref('dim_players_history') }} p
        where m.puuid = p.puuid
    )

    {% if is_incremental() %}
    and to_date(m.date, 'yyMMdd') >= (
        select date_sub(max(snapshot_date), {{ late_arrival_lookback_days }})
        from {{ this }}
    )
    {% endif %}

    qualify row_number() over (
        partition by
            m.puuid,
            champion_key,
            to_date(m.date, 'yyMMdd')
        order by m._ingested_at desc
    ) = 1

)

select
    {{ dbt_utils.generate_surrogate_key(['puuid', 'champion_key', 'snapshot_date']) }} as mastery_history_id,
    puuid,
    champion_key,
    champion_points,
    last_play_time,
    snapshot_date,
    patch
from source
