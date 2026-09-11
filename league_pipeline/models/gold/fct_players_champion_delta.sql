{{ config(materialized='table', file_format='delta') }}

select
    {{ dbt_utils.generate_surrogate_key(['puuid', 'champion_key', 'snapshot_date']) }} as champion_delta_id,
    puuid,
    champion_key,
    snapshot_date,
    champion_points - lag(champion_points) over (
        partition by puuid, champion_key
        order by snapshot_date
    ) as points_delta
from {{ref('fct_masteries_history')}}
qualify points_delta != 0
