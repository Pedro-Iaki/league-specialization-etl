{{ config(materialized='table', file_format='delta', tags=['business_sample']) }}

select
    t.transaction_id,
    t.player_id,
    t.product_id,
    t.region_at_purchase,
    t.currency_id,
    c.currency_kind,
    p.category,
    t.original_price,
    t.amount_spent,
    t.amount_usd,
    t.occurred_at,
    t.scenario_id,
    case when t.amount_spent < t.original_price then
        1.0 - t.amount_spent / nullif(t.original_price, 0)
    end as discount_fraction
from {{ ref('bronze_transactions') }} t
left join {{ ref('sample_products') }} p on t.product_id = p.product_id
left join {{ ref('sample_currencies') }} c on t.currency_id = c.currency_id
