{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key=['puuid', 'state_hash'],
    on_schema_change='append_new_columns'
) }}

select
    * except(_source_file, _ingested_at),
    sha2(
        concat_ws('|',
            coalesce(region, ''), coalesce(queueType, ''),
            coalesce(tier, ''), coalesce(rank, ''),
            coalesce(patch, ''), coalesce(date, '')
        ), 256
    ) as state_hash
from {{ source('raw', 'players') }}