{{ config(materialized='table', file_format='delta') }}

{% set window_days = var('recent_form_window_days', 28) %}

-- One row per (player_id, queue) with at least one usable rank period inside
-- the trailing {{ window_days }}-day window. Aggregates the whole window rather
-- than reading a single snapshot.
--
-- WHY THIS EXISTS: fct_players_rank_last_delta drops snapshots where nothing
-- moved, so any average taken over it is conditioned on "players whose most
-- recent observation happened to contain games". That is a survivorship filter,
-- and it was silently flowing into avg_lp_velocity on the old champion mart -
-- champions played by streaky, bursty players looked systematically different
-- from champions played by steady ones for reasons that had nothing to do with
-- the champion. Summing a fixed window fixes the denominator.
--
-- Column names are explicit about units, because lp_velocity upstream is LP per
-- GAME despite reading like a rate over time.

with as_of as (

    select max(snapshot_date) as as_of_date
    from {{ ref('fct_players_rank_history') }}

),

windowed as (

    select r.*
    from {{ ref('fct_players_rank_history') }} r
    cross join as_of ao
    where r.snapshot_date > date_sub(ao.as_of_date, {{ window_days }})
      -- a season/split reset makes lp_delta meaningless for that period
      and not r.is_counter_reset

),

aggregated as (

    select
        player_id,
        queue,
        max(region) as region,
        count(*) as periods_in_window,
        sum(case when has_movement then 1 else 0 end) as periods_with_games,
        min(previous_snapshot_date) as window_start_date,
        max(snapshot_date) as window_end_date,
        datediff(max(snapshot_date), min(previous_snapshot_date)) as days_covered,
        sum(wins_delta) as wins,
        sum(losses_delta) as losses,
        sum(wins_delta + losses_delta) as games,
        sum(lp_delta) as lp_delta,
        -- peak-to-trough spread of observed LP inside the window. A player who
        -- ends flat after swinging 400 LP is not the same as one who never
        -- moved, and lp_delta alone cannot tell them apart.
        max(absolute_lp) - min(absolute_lp) as lp_range
    from windowed
    group by player_id, queue

)

select
    {{ dbt_utils.generate_surrogate_key(['a.player_id', 'a.queue']) }} as player_form_id,
    a.player_id,
    a.queue,
    a.region,
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
    a.lp_range,
    {{ dbt_utils.safe_divide('a.wins', 'a.games') }} as win_rate,
    {{ dbt_utils.safe_divide('a.lp_delta', 'a.games') }} as lp_per_game,
    {{ dbt_utils.safe_divide('a.lp_delta', 'a.days_covered') }} as lp_per_day,
    {{ dbt_utils.safe_divide('a.games', 'a.days_covered') }} as games_per_day
from aggregated a
cross join as_of ao
