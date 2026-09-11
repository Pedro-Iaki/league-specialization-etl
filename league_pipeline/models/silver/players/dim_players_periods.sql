{{ config(materialized='view') }}

select
    *,
    lead(snapshot_date) over (
        partition by puuid order by snapshot_date
    ) as valid_to
from {{ ref('dim_players_history') }}