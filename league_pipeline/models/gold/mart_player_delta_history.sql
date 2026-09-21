{{ config(materialized='table', file_format='delta') }}

-- Replaces fct_player_delta_history.
--
-- One row per (player_id, queue, snapshot_date) with an earlier snapshot to
-- compare against.
--   * Rank columns cover the FULL history (fct_players_rank_history).
--   * Pool / role columns are as-of that snapshot, from fct_player_pool_history.
--     They are null for snapshots before that table started collecting; that
--     history cannot be back-filled.
--
-- Safe to rebuild as a plain table: both sources keep their own history, and
-- pool history is joined on a unique (player_id, snapshot_date), so there is no
-- fan-out.

select
    r.rank_delta_id,
    r.player_id,
    r.region,
    r.queue,
    r.snapshot_date,
    r.previous_snapshot_date,
    r.period_in_days,

    -- rank movement
    r.previous_tier,
    r.previous_division,
    r.tier,
    r.division,
    r.league_points,
    r.absolute_lp,
    r.wins_delta,
    r.losses_delta,
    r.lp_delta,
    r.lp_velocity,
    r.has_movement,
    r.is_counter_reset,
    {{ dbt_utils.safe_divide('r.wins_delta', '(r.wins_delta + r.losses_delta)') }} as win_rate,

    -- as-of pool (null before fct_player_pool_history started collecting)
    p.total_days_tracked,
    p.recent_total_points,
    p.active_champion_ids,
    p.active_champion_count,
    p.recent_champion_ids,
    p.recent_champion_count,
    p.main_role,
    p.main_role_weight

from {{ ref('fct_players_rank_history') }} r
left join {{ ref('fct_player_pool_history') }} p
    on r.player_id = p.player_id
    and r.snapshot_date = p.snapshot_date