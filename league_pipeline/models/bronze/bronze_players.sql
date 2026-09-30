{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key=['puuid', 'queueType', 'date'],
    alias='players',
    on_schema_change='append_new_columns'
) }}

with source_data as (
    select
        * except(_ingested_at),
        _ingested_at
    from {{ source('raw', 'players') }}
)

select *
from source_data
qualify row_number() over (
    partition by puuid, queueType, date
    order by _ingested_at desc
) = 1
