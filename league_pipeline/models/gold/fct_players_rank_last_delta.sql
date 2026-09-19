{{ config(materialized='table', file_format='delta') }}

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

)

select

    {{ dbt_utils.generate_surrogate_key(['player_id', 'queue', 'snapshot_date']) }} as rank_delta_id,
    player_id,
    region,
    queue,
    tier,
    division,
    league_points,
    absolute_lp,
    previous_snapshot_date,
    snapshot_date,
    floor(datediff(DAY, previous_snapshot_date, snapshot_date)) as period_in_days,
    {{ dbt_utils.safe_divide('lp_delta', 'period_in_days') }} as lp_velocity,
    wins_delta,
    losses_delta,
    lp_delta

from deltas
-- drop the first snapshot per player_id/queue (no prior baseline -> null deltas,
-- filtered out the same way NULL != 0 is falsy) and any snapshot where
-- nothing actually moved
qualify ((wins_delta + losses_delta) != 0 or lp_delta != 0) and snapshot_date = max(snapshot_date) over (partition by player_id, queue) and period_in_days > 0