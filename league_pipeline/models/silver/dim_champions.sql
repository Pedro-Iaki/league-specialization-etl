{{ config(materialized='table', file_format='delta') }}

select
    key,
    name,
    id,
    client_positions,
    external_positions,
    case
        when array_contains(client_positions, 'Bottom') then array('Bottom')
        when client_positions = array('Jungle')          then array('Jungle')
        else array_distinct(array_union(client_positions, external_positions))
    end as expected_positions,
    patch
from {{ source('raw', 'champions') }}