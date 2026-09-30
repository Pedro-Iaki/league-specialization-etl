-- Recent form must be a faithful aggregation of non-reset rank periods inside
-- the configured trailing window.

{% set window_days = var('recent_form_window_days', 7) %}

with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('fct_players_rank_history') }}

),

expected as (

    select
        r.player_id,
        r.queue,
        max(ao.as_of_date) as as_of_date,
        {{ window_days }} as window_days,
        count(*) as periods_in_window,
        count(case when r.games_delta > 0 then 1 end) as periods_with_games,
        min(r.previous_snapshot_date) as window_start_date,
        max(r.snapshot_date) as window_end_date,
        datediff(max(r.snapshot_date), min(r.previous_snapshot_date)) as days_covered,
        sum(r.wins_delta) as wins,
        sum(r.losses_delta) as losses,
        sum(r.games_delta) as games,
        sum(r.lp_delta) as lp_delta,
        {{ dbt_utils.safe_divide('sum(r.wins_delta)', 'sum(r.games_delta)') }} as win_rate,
        {{ dbt_utils.safe_divide('sum(r.lp_delta)', 'sum(r.games_delta)') }} as lp_per_game,
        {{ dbt_utils.safe_divide(
            'sum(r.lp_delta)',
            'datediff(max(r.snapshot_date), min(r.previous_snapshot_date))'
        ) }} as lp_per_day,
        {{ dbt_utils.safe_divide(
            'sum(r.games_delta)',
            'datediff(max(r.snapshot_date), min(r.previous_snapshot_date))'
        ) }} as games_per_day
    from {{ ref('fct_players_rank_history') }} r
    cross join as_of ao
    where r.snapshot_date > date_sub(ao.as_of_date, {{ window_days }})
      and not r.is_counter_reset
    group by r.player_id, r.queue

),

actual as (

    select *
    from {{ ref('fct_players_rank_recent_form') }}

)

select
    coalesce(e.player_id, a.player_id) as player_id,
    coalesce(e.queue, a.queue) as queue
from expected e
full outer join actual a
    on e.player_id = a.player_id
    and e.queue = a.queue
where e.player_id is null
   or a.player_id is null
   or not (e.as_of_date <=> a.as_of_date)
   or e.window_days <> a.window_days
   or e.periods_in_window <> a.periods_in_window
   or e.periods_with_games <> a.periods_with_games
   or not (e.window_start_date <=> a.window_start_date)
   or not (e.window_end_date <=> a.window_end_date)
   or e.days_covered <> a.days_covered
   or e.wins <> a.wins
   or e.losses <> a.losses
   or e.games <> a.games
   or e.lp_delta <> a.lp_delta
   or not (e.win_rate <=> a.win_rate)
   or not (e.lp_per_game <=> a.lp_per_game)
   or not (e.lp_per_day <=> a.lp_per_day)
   or not (e.games_per_day <=> a.games_per_day)
