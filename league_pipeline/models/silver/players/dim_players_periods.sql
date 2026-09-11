{{ config(materialized='view') }}

select
    *,
    lead(valid_from) over (
        partition by puuid order by valid_from
    ) as valid_to
from {{ ref('dim_players_history') }}