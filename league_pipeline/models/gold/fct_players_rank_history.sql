{{ config(materialized='table', file_format='delta') }}

-- One row per (player_id, queue, snapshot_date) that has an earlier snapshot to
-- compare against, i.e. the FULL history of rank movement.
--
-- Rebuilt from dim_players_history on every run, so late arrivals and logic
-- changes never leave gaps. fct_players_rank_last_delta (latest row only) and
-- mart_player_delta_history are both built on top of this.
--
-- Rows where nothing moved are KEPT (has_movement = false) so averages over
-- this table are not biased toward players who happened to move. Filter on
-- has_movement downstream if you only want periods with activity.

with source as (

    select
        puuid as player_id,
        region,
        queue,
        tier,
        division,
        league_points,
        wins,
        losses,
        snapshot_date
    from {{ ref('dim_players_history') }}
    where league_points is not null

),

with_absolute_lp as (

    select
        *,
        {{ absolute_lp('tier', 'division', 'league_points') }} as absolute_lp
    from source

),

deltas as (

    select
        *,
        lag(snapshot_date) over (
            partition by player_id, queue order by snapshot_date
        ) as previous_snapshot_date,
        lag(tier) over (
            partition by player_id, queue order by snapshot_date
        ) as previous_tier,
        lag(division) over (
            partition by player_id, queue order by snapshot_date
        ) as previous_division,
        wins - lag(wins) over (
            partition by player_id, queue order by snapshot_date
        ) as wins_delta,
        losses - lag(losses) over (
            partition by player_id, queue order by snapshot_date
        ) as losses_delta,
        absolute_lp - lag(absolute_lp) over (
            partition by player_id, queue order by snapshot_date
        ) as lp_delta
    from with_absolute_lp

),

with_period as (

    select
        *,
        datediff(DAY, previous_snapshot_date, snapshot_date) as period_in_days
    from deltas

)

select
    {{ dbt_utils.generate_surrogate_key(['player_id', 'queue', 'snapshot_date']) }} as rank_delta_id,
    player_id,
    region,
    queue,
    previous_tier,
    previous_division,
    tier,
    division,
    league_points,
    absolute_lp,
    previous_snapshot_date,
    snapshot_date,
    period_in_days,
    {{ dbt_utils.safe_divide('lp_delta', '(wins_delta + losses_delta)') }} as lp_velocity,
    wins_delta,
    losses_delta,
    lp_delta,
    ((wins_delta + losses_delta) != 0 or lp_delta != 0) as has_movement,
    -- wins/losses only ever go up within a season/split. A negative delta means
    -- the counters were reset, and lp_delta / lp_velocity on that row is junk.
    (wins_delta < 0 or losses_delta < 0) as is_counter_reset
from with_period
where previous_snapshot_date is not null
  and period_in_days > 0