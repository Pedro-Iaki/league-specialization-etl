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
        else array_distinct(array_union(coalesce(client_positions, array()), coalesce(external_positions, array())))
    end as expected_positions,
    patch
from {{ source('raw', 'champions') }}