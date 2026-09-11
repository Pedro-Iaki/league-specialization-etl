{{ config(materialized='view') }}

select
    *,
    lead(valid_from) over (
        partition by puuid, champion_key order by valid_from
    ) as valid_to
from {{ ref('fct_masteries_history') }}