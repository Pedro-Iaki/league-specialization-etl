{{ config(materialized='table', file_format='delta') }}

{% set period_days = var('rank_period_days', 7) %}
{% if period_days < 1 %}
    {{ exceptions.raise_compiler_error('rank_period_days must be positive') }}
{% endif %}

with snapshots as (

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
        {{ rank_score('tier', 'division', 'league_points') }} as rank_score,
        date_sub(
            snapshot_date,
            pmod(datediff(snapshot_date, date('1970-01-05')), {{ period_days }})
        ) as period_bucket_start
    from {{ ref('dim_players_history') }}
    where league_points is not null

),

endpoints as (

    select *
    from snapshots
    where date_add(period_bucket_start, {{ period_days }}) <= current_date()
    qualify row_number() over (
        partition by player_id, queue, period_bucket_start
        order by snapshot_date desc
    ) = 1

),

paired as (

    select
        *,
        lag(period_bucket_start) over player_periods as previous_bucket_start,
        lag(snapshot_date) over player_periods as previous_snapshot_date,
        lag(tier) over player_periods as previous_tier,
        lag(division) over player_periods as previous_division,
        lag(league_points) over player_periods as previous_league_points,
        lag(rank_score) over player_periods as previous_rank_score,
        lag(wins) over player_periods as previous_wins,
        lag(losses) over player_periods as previous_losses
    from endpoints
    window player_periods as (
        partition by player_id, queue
        order by period_bucket_start
    )

)

select
    {{ dbt_utils.generate_surrogate_key([
        'p.player_id', 'p.queue', 'p.period_bucket_start'
    ]) }} as rank_period_id,
    p.player_id,
    p.region,
    p.queue,
    p.previous_tier,
    p.previous_division,
    p.previous_league_points,
    p.previous_rank_score,
    p.tier,
    p.division,
    p.league_points,
    p.rank_score,
    p.previous_snapshot_date,
    p.snapshot_date,
    p.period_bucket_start,
    date_add(p.period_bucket_start, {{ period_days - 1 }}) as period_bucket_end,
    {{ period_days }} as period_bucket_days,
    datediff(p.snapshot_date, p.previous_snapshot_date) as period_in_days,
    p.wins - p.previous_wins as wins_delta,
    p.losses - p.previous_losses as losses_delta,
    p.wins - p.previous_wins + p.losses - p.previous_losses as games_delta,
    p.rank_score - p.previous_rank_score as lp_delta
from paired p
where datediff(p.period_bucket_start, p.previous_bucket_start) = {{ period_days }}
  and datediff(p.snapshot_date, p.previous_snapshot_date)
      between {{ [1, period_days - 1] | max }} and {{ period_days + 1 }}
  and not exists (
      select 1
      from {{ ref('fct_players_rank_history') }} h
      where h.player_id = p.player_id
        and h.queue = p.queue
        and h.snapshot_date > p.previous_snapshot_date
        and h.snapshot_date <= p.snapshot_date
        and h.is_counter_reset
  )
