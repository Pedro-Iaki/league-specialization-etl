{{ config(materialized='table', file_format='delta') }}

-- Renamed from fct_players_champion_last_delta.
--
-- The old name was wrong and dangerous: this model is one row per
-- (player, champion, snapshot) over the FULL history, not a latest-row table
-- like fct_players_rank_last_delta. fct_players_champion_activity depends on
-- that full history (it sums deltas over a 60-day window), so anyone who
-- trusted the name and filtered it down to one row per champion would have
-- silently broken the activity flags.
--
-- Two fixes beyond the rename:
--   * the surrogate key now includes snapshot_date. It was (player_id,
--     champion_key), which is NOT unique at this grain - the `unique` test in
--     schema.yml was pointed at a model name that didn't exist, so it never
--     ran and never caught it.
--   * previous_snapshot_date is resolved in its own CTE before being used by
--     datediff, instead of being referenced as a lateral alias in the same
--     SELECT as the window function that defines it. fct_players_rank_history
--     already did it this way; this brings the two into line.

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
