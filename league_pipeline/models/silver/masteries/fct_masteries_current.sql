{{ config(materialized='table', file_format='delta') }}

select * except(valid_to)
from {{ ref('fct_masteries_periods') }}
where valid_to is null