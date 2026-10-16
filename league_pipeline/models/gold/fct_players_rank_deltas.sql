{{ config(materialized='table', file_format='delta') }}

with ranked as (

    select
        puuid as player_id,
        region,
        queue,
        tier,
        division,
        league_points,
        wins,
        losses,
        snapshot_date,
        {{ rank_score('tier', 'division', 'league_points') }} as rank_score
    from {{ ref('dim_players_history') }}
    where league_points is not null

),

lagged as (

    select
        *,
        lag(snapshot_date) over player_history as previous_snapshot_date,
        lag(tier) over player_history as previous_tier,
        lag(division) over player_history as previous_division,
        lag(league_points) over player_history as previous_league_points,
        lag(rank_score) over player_history as previous_rank_score,
        wins - lag(wins) over player_history as wins_delta,
        losses - lag(losses) over player_history as losses_delta,
        rank_score - lag(rank_score) over player_history as lp_delta
    from ranked
    window player_history as (
        partition by player_id, queue
        order by snapshot_date
    )

),

periods as (

    select
        *,
        datediff(snapshot_date, previous_snapshot_date) as period_in_days
    from lagged

)

select
    {{ dbt_utils.generate_surrogate_key(['player_id', 'queue', 'snapshot_date']) }} as rank_delta_id,
    player_id,
    region,
    queue,
    previous_tier,
    previous_division,
    previous_league_points,
    previous_rank_score,
    tier,
    division,
    league_points,
    rank_score,
    previous_snapshot_date,
    snapshot_date,
    period_in_days,
    wins_delta,
    losses_delta,
    wins_delta + losses_delta as games_delta,
    lp_delta,
    wins_delta < 0 or losses_delta < 0 as is_counter_reset
from periods
where previous_snapshot_date is not null
  and period_in_days > 0
