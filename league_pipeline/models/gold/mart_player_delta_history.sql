{{ config(materialized='table', file_format='delta') }}

{% set short_window = var('trajectory_short_window_days', 14) %}
{% set long_window = var('trajectory_long_window_days', 28) %}

{% set w_short %}(
        partition by player_id, queue
        order by cast(snapshot_date as timestamp)
        range between interval {{ short_window }} days preceding and current row
    ){% endset %}

{% set w_long %}(
        partition by player_id, queue
        order by cast(snapshot_date as timestamp)
        range between interval {{ long_window }} days preceding and current row
    ){% endset %}

-- Grain: one row per (player_id, queue, snapshot_date) that has an earlier
-- snapshot to compare against.
--   * Rank columns cover the FULL history (fct_players_rank_history).
--   * Pool / role columns are as-of that snapshot, from fct_player_pool_history.
--     They are null for snapshots taken before that table started collecting,
--     and null for the newly added role_*/pool_* columns for snapshots frozen
--     before those columns existed. That history cannot be back-filled.
--
-- Rolling windows are time-based (RANGE ... INTERVAL), not row-based, so an
-- irregular or interrupted snapshot cadence does not silently stretch the
-- lookback. Counter-reset rows are nulled out before windowing so a soft reset
-- does not land a fake -400 LP inside a 28-day sum.
--
-- Safe to rebuild as a plain table: both sources keep their own history, and
-- pool history is joined on a unique (player_id, snapshot_date), so there is
-- no fan-out.

with base as (

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
        r.previous_league_points,
        r.previous_absolute_lp,
        r.previous_state_order,
        r.tier,
        r.division,
        r.league_points,
        r.absolute_lp,
        r.state_order,
        r.movement_type,
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
        p.pool_top1_share,
        p.pool_top3_share,
        p.pool_hhi,
        p.pool_entropy,
        p.pool_normalized_entropy,
        p.role_top_pct,
        p.role_jungle_pct,
        p.role_middle_pct,
        p.role_bottom_pct,
        p.role_support_pct,
        p.role_purity,
        p.main_role,
        p.main_role_weight

    from {{ ref('fct_players_rank_history') }} r
    left join {{ ref('fct_player_pool_history') }} p
        on r.player_id = p.player_id
        and r.snapshot_date = p.snapshot_date

),

cleaned as (

    select
        *,
        case when is_counter_reset then null else lp_delta end as lp_delta_clean,
        case when is_counter_reset then null else wins_delta end as wins_delta_clean,
        case when is_counter_reset then null else losses_delta end as losses_delta_clean
    from base

),

rolling as (

    select
        *,
        sum(lp_delta_clean) over {{ w_short }} as lp_delta_{{ short_window }}d,
        sum(wins_delta_clean + losses_delta_clean) over {{ w_short }} as games_{{ short_window }}d,
        sum(wins_delta_clean) over {{ w_short }} as wins_{{ short_window }}d,

        sum(lp_delta_clean) over {{ w_long }} as lp_delta_{{ long_window }}d,
        sum(wins_delta_clean + losses_delta_clean) over {{ w_long }} as games_{{ long_window }}d,
        sum(wins_delta_clean) over {{ w_long }} as wins_{{ long_window }}d,
        count(*) over {{ w_long }} as periods_{{ long_window }}d
    from cleaned

)

select
    * except(lp_delta_clean, wins_delta_clean, losses_delta_clean),
    {{ dbt_utils.safe_divide('wins_' ~ short_window ~ 'd', 'games_' ~ short_window ~ 'd') }} as win_rate_{{ short_window }}d,
    {{ dbt_utils.safe_divide('lp_delta_' ~ short_window ~ 'd', 'games_' ~ short_window ~ 'd') }} as lp_per_game_{{ short_window }}d,
    {{ dbt_utils.safe_divide('wins_' ~ long_window ~ 'd', 'games_' ~ long_window ~ 'd') }} as win_rate_{{ long_window }}d,
    {{ dbt_utils.safe_divide('lp_delta_' ~ long_window ~ 'd', 'games_' ~ long_window ~ 'd') }} as lp_per_game_{{ long_window }}d
from rolling
