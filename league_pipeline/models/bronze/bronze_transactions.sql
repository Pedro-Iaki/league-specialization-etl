{{ config(materialized='table', file_format='delta', alias='transactions', tags=['business_sample']) }}

-- Known synthetic endpoint contract. Invalid duplicate events fail the grain test.
select
    cast(transaction_id as string) as transaction_id,
    cast(player_id as string) as player_id,
    cast(product_id as string) as product_id,
    cast(region_at_purchase as string) as region_at_purchase,
    cast(currency_id as string) as currency_id,
    cast(original_price as decimal(18,2)) as original_price,
    cast(amount_spent as decimal(18,2)) as amount_spent,
    cast(amount_usd as decimal(18,2)) as amount_usd,
    cast(occurred_at as timestamp) as occurred_at,
    cast(scenario_id as string) as scenario_id
from {{ source('raw', 'transactions') }}
