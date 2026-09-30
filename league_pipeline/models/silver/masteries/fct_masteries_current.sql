{{ config(materialized='table', file_format='delta') }}

select *
from {{ ref('fct_masteries_history') }}
qualify row_number() over (
    partition by puuid, champion_key
    order by snapshot_date desc
) = 1
