{{ config(materialized='table', file_format='delta') }}

select * except(valid_to)
from {{ ref('dim_players_periods') }}
where valid_to is null