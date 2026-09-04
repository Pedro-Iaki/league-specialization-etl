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
    ) as state_hash,
    _ingested_at
from {{ source('raw', 'players') }}

{% if is_incremental() %}
where _ingested_at > (select coalesce(max(_ingested_at), '1900-01-01') from {{ this }})
{% endif %}