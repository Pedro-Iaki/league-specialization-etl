{{ config(materialized='table', file_format='delta', tags=['business_sample']) }}

-- Frozen real context, generated spending. Game currencies never contribute USD cash.
with events as (
    select t.*, p.as_of_date, p.purchase_window_start, p.purchase_window_end
    from {{ ref('fct_transactions') }} t
    inner join {{ source('raw', 'business_sample_players') }} p
        on t.player_id = p.player_id and t.scenario_id = p.scenario_id
),
totals as (
    select
        player_id,
        scenario_id,
        min(occurred_at) as first_purchase_at,
        max(occurred_at) as last_purchase_at,
        count(*) as purchase_count_alltime,
        count(case when category = 'champion' and currency_id = 'L_BE' then 1 end)
            as be_champion_purchase_count_alltime,
        count(case when currency_kind = 'fiat' then 1 end) as cash_purchase_count_alltime,
        sum(case when currency_kind = 'fiat' then amount_usd else cast(0 as decimal(18,2)) end)
            as cash_spent_usd_alltime,
        count(distinct case when currency_kind = 'fiat' then date_trunc('month', occurred_at) end)
            as cash_active_months_alltime,
        count(case when currency_kind = 'fiat'
            and cast(occurred_at as date) between purchase_window_start and purchase_window_end then 1 end)
            as cash_purchase_count_60d,
        sum(case when currency_kind = 'fiat'
            and cast(occurred_at as date) between purchase_window_start and purchase_window_end
            then amount_usd else cast(0 as decimal(18,2)) end) as cash_spent_usd_60d,
        count(distinct case when currency_kind = 'fiat'
            and cast(occurred_at as date) between purchase_window_start and purchase_window_end
            then date_trunc('month', occurred_at) end) as cash_active_months_60d,
        max(case when currency_kind = 'fiat'
            and cast(occurred_at as date) between purchase_window_start and purchase_window_end then occurred_at end)
            as last_cash_purchase_at_60d,
        count(case when currency_kind = 'fiat' and discount_fraction is not null
            and cast(occurred_at as date) between purchase_window_start and purchase_window_end then 1 end)
            as cash_discounted_purchase_count_60d,
        avg(case when currency_kind = 'fiat'
            and cast(occurred_at as date) between purchase_window_start and purchase_window_end
            then discount_fraction end) as cash_discount_mean_60d,
        count(case when category in ('champion', 'cosmetic') then 1 end) as content_purchase_count_alltime,
        count(case when category = 'cosmetic' then 1 end) as cosmetic_purchase_count_alltime,
        count(discount_fraction) as discounted_purchase_count_alltime,
        avg(discount_fraction) as discount_mean_alltime
    from events
    group by player_id, scenario_id
),
cash_dates as (
    -- Multiple top-ups on one date form one occasion, rather than zero-length gaps.
    select distinct player_id, scenario_id, cast(occurred_at as date) as cash_date
    from events where currency_kind = 'fiat'
),
cash_gaps as (
    select player_id, scenario_id,
        datediff(cash_date, lag(cash_date) over (partition by player_id, scenario_id order by cash_date)) as gap_days
    from cash_dates
),
consistency as (
    select player_id, scenario_id,
        case when count(gap_days) >= 2 then
            1.0 / (1.0 + stddev_pop(gap_days) / nullif(avg(gap_days), 0))
        end as payment_consistency_alltime
    from cash_gaps group by player_id, scenario_id
)
select
    p.player_id,
    p.scenario_id,
    p.as_of_date,
    p.snapshot_date,
    p.purchase_window_start,
    p.purchase_window_end,
    p.region,
    p.queue,
    p.tier,
    p.main_role,
    p.active_playstyle,
    p.active_primary_champion_key,
    p.active_primary_champion_name,
    p.active_normalized_entropy,
    p.active_top1_share,
    p.alltime_top1_share,
    p.total_mastery_points,
    p.champions_with_mastery,
    p.games_per_day_recent,
    p.ranked_mastery_share,
    p.simulated_owned_champions,
    p.simulated_customer_type,
    t.first_purchase_at,
    t.last_purchase_at,
    coalesce(t.purchase_count_alltime, 0) as purchase_count_alltime,
    coalesce(t.be_champion_purchase_count_alltime, 0) as be_champion_purchase_count_alltime,
    coalesce(t.cash_purchase_count_alltime, 0) as cash_purchase_count_alltime,
    coalesce(t.cash_spent_usd_alltime, 0) as cash_spent_usd_alltime,
    coalesce(t.cash_active_months_alltime, 0) as cash_active_months_alltime,
    -- Inclusive calendar months since the first generated purchase, matching cash-active months.
    coalesce(t.cash_active_months_alltime, 0) / nullif(
        (year(p.as_of_date) - year(t.first_purchase_at)) * 12
        + month(p.as_of_date) - month(t.first_purchase_at) + 1, 0) as payment_frequency_alltime,
    t.cash_spent_usd_alltime / nullif(t.cash_active_months_alltime, 0) as payment_intensity_alltime,
    c.payment_consistency_alltime,
    coalesce(t.cash_purchase_count_60d, 0) as cash_purchase_count_60d,
    coalesce(t.cash_spent_usd_60d, 0) as cash_spent_usd_60d,
    coalesce(t.cash_active_months_60d, 0) as cash_active_months_60d,
    t.last_cash_purchase_at_60d,
    datediff(p.as_of_date, cast(t.last_cash_purchase_at_60d as date)) as days_since_last_cash_purchase_60d,
    coalesce(t.cash_discounted_purchase_count_60d, 0) as cash_discounted_purchase_count_60d,
    t.cash_discounted_purchase_count_60d / nullif(t.cash_purchase_count_60d, 0) as cash_discount_share_60d,
    t.cash_discount_mean_60d,
    coalesce(t.content_purchase_count_alltime, 0) as content_purchase_count_alltime,
    coalesce(t.cosmetic_purchase_count_alltime, 0) as cosmetic_purchase_count_alltime,
    t.cosmetic_purchase_count_alltime / nullif(t.content_purchase_count_alltime, 0) as cosmetic_bias_alltime,
    coalesce(t.discounted_purchase_count_alltime, 0) as discounted_purchase_count_alltime,
    t.discounted_purchase_count_alltime / nullif(t.purchase_count_alltime, 0) as discount_share_alltime,
    t.discount_mean_alltime
from {{ source('raw', 'business_sample_players') }} p
left join totals t on p.player_id = t.player_id and p.scenario_id = t.scenario_id
left join consistency c on p.player_id = c.player_id and p.scenario_id = c.scenario_id
