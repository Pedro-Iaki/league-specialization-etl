{{ config(materialized='table', file_format='delta') }}

select *
from {{ ref('dim_players_history') }}
qualify row_number() over (
    partition by puuid, queue
    order by snapshot_date desc
) = 1
