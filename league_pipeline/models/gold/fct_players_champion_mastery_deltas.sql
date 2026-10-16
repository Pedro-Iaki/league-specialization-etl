{{ config(materialized='table', file_format='delta') }}

with source as (

    select
        m.puuid as player_id,
        m.champion_key,
        c.name as champion_name,
        m.snapshot_date,
        m.champion_points,
        m.last_play_time
    from {{ ref('fct_masteries_history') }} m
    left join {{ ref('dim_champions') }} c
        on m.champion_key = c.key

),

lagged as (

    select
        *,
        lag(snapshot_date) over (
            partition by player_id, champion_key order by snapshot_date
        ) as previous_snapshot_date,
        lag(champion_points) over (
            partition by player_id, champion_key order by snapshot_date
        ) as previous_champion_points
    from source

),

deltas as (

    select
        *,
        champion_points - previous_champion_points as points_delta,
        datediff(snapshot_date, previous_snapshot_date) as days_period
    from lagged

)

select
    {{ dbt_utils.generate_surrogate_key(['player_id', 'champion_key', 'snapshot_date']) }} as champion_delta_id,
    player_id,
    champion_key,
    champion_name,
    previous_snapshot_date,
    snapshot_date,
    days_period,
    previous_champion_points,
    champion_points,
    points_delta,
    {{ dbt_utils.safe_divide('points_delta', 'days_period') }} as points_per_day,
    last_play_time
from deltas
where points_delta is not null
  and points_delta != 0
  and days_period > 0
