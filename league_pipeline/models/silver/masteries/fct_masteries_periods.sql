{{ config(materialized='view') }}

select
    *,
    lead(snapshot_date) over (
        partition by puuid, champion_key order by snapshot_date
    ) as valid_to
from {{ ref('fct_masteries_history') }}