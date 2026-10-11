{{ config(tags=['business_sample']) }}

with players as (
    select * from {{ source('raw', 'business_sample_players') }}
),
events as (
    select * from {{ ref('fct_transactions') }}
),
expected as (
    select player_id, scenario_id, count(*) as purchases,
        sum(case when currency_kind = 'fiat' then amount_usd else 0 end) as cash_usd,
        sum(case when currency_kind = 'fiat' then 1 else 0 end) as cash_count,
        sum(case when currency_kind = 'fiat' and cast(occurred_at as date)
            between p.purchase_window_start and p.purchase_window_end then amount_usd else 0 end) as recent_usd,
        count(case when currency_kind = 'fiat' and cast(occurred_at as date)
            between p.purchase_window_start and p.purchase_window_end then 1 end) as recent_cash_count,
        count(case when currency_kind = 'fiat' and amount_spent < original_price and cast(occurred_at as date)
            between p.purchase_window_start and p.purchase_window_end then 1 end) as recent_discount_count,
        avg(case when currency_kind = 'fiat' and amount_spent < original_price and cast(occurred_at as date)
            between p.purchase_window_start and p.purchase_window_end
            then 1.0 - amount_spent / nullif(original_price, 0) end) as recent_discount_mean
    from events inner join players p using (player_id, scenario_id)
    group by player_id, scenario_id
),
summary as (
    select count(*) as players, count(distinct player_id) as unique_players,
        count(distinct scenario_id) as scenarios,
        max(cast(get_json_object(scenario_metadata, '$.player_count') as bigint)) as expected_players,
        max(cast(get_json_object(scenario_metadata, '$.transaction_count') as bigint)) as expected_events
    from players
)
select 'incomplete_sample' as issue from summary
where players = 0 or players <> unique_players or scenarios <> 1 or players <> expected_players
   or expected_events <> (select count(*) from events)
union all
select 'player_reconciliation' from {{ ref('mart_player_spending') }} g
full outer join expected e using (player_id, scenario_id)
where g.player_id is null or e.player_id is null or g.purchase_count_alltime <> e.purchases
   or g.cash_spent_usd_alltime <> e.cash_usd or g.cash_purchase_count_alltime <> e.cash_count
   or g.cash_spent_usd_60d <> e.recent_usd or g.cash_spent_usd_60d > g.cash_spent_usd_alltime
   or g.be_champion_purchase_count_alltime < 1 or g.first_purchase_at > g.last_purchase_at
   or g.cash_discounted_purchase_count_60d <> e.recent_discount_count
   or not (g.cash_discount_share_60d <=> e.recent_discount_count / nullif(e.recent_cash_count, 0))
   or not (g.cash_discount_mean_60d <=> e.recent_discount_mean)
union all
select 'invalid_money_or_join' from events e
left join players p using (player_id, scenario_id)
where p.player_id is null or e.currency_kind is null or e.category is null
   or e.amount_spent < 0 or e.amount_spent > e.original_price
   or (e.currency_kind = 'game' and e.amount_usd is not null)
   or (e.currency_kind = 'fiat' and (e.amount_usd is null or e.amount_usd < 0))
   or (e.currency_id = 'USD' and e.amount_usd <> e.amount_spent)
