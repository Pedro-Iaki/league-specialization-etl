{{ config(materialized='table', file_format='delta') }}

{% set window_days = var('recent_form_window_days', 7) %}

with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('fct_players_rank_history') }}

),

windowed as (

    select r.*
    from {{ ref('fct_players_rank_history') }} r
    cross join as_of
    where r.snapshot_date > date_sub(as_of.as_of_date, {{ window_days }})
      and not r.is_counter_reset

),

aggregated as (

    select
        player_id,
        queue,
        count(*) as periods_in_window,
        count(case when games_delta > 0 then 1 end) as periods_with_games,
        min(previous_snapshot_date) as window_start_date,
        max(snapshot_date) as window_end_date,
        datediff(max(snapshot_date), min(previous_snapshot_date)) as days_covered,
        sum(wins_delta) as wins,
        sum(losses_delta) as losses,
        sum(games_delta) as games,
        sum(lp_delta) as lp_delta
    from windowed
    group by player_id, queue

)

select
    {{ dbt_utils.generate_surrogate_key(['a.player_id', 'a.queue']) }} as player_form_id,
    a.player_id,
    a.queue,
    ao.as_of_date,
    {{ window_days }} as window_days,
    a.periods_in_window,
    a.periods_with_games,
    a.window_start_date,
    a.window_end_date,
    a.days_covered,
    a.wins,
    a.losses,
    a.games,
    a.lp_delta,
    {{ dbt_utils.safe_divide('a.wins', 'a.games') }} as win_rate,
    {{ dbt_utils.safe_divide('a.lp_delta', 'a.games') }} as lp_per_game,
    {{ dbt_utils.safe_divide('a.lp_delta', 'a.days_covered') }} as lp_per_day,
    {{ dbt_utils.safe_divide('a.games', 'a.days_covered') }} as games_per_day
from aggregated a
cross join as_of ao
