{{ config(
    materialized='incremental',
    file_format='delta',
    incremental_strategy='merge',
    unique_key='tier_role_date_id',
    on_schema_change='append_new_columns',
    full_refresh=false
) }}

-- Grain: one row per (tier, role, as_of_date). Appended daily, so the table
-- accumulates into a time series of ladder-wide behaviour.
--
-- full_refresh=false stops `dbt run --full-refresh` from wiping accumulated
-- days. mart_player_profile is a current-snapshot table, so a past as_of_date
-- cannot be recomputed. Drop the table by hand if you deliberately want to
-- restart the series.
--
-- Players with no inferable role land in role = 'Unknown' rather than being
-- dropped, so summing player_count across roles reconciles to the tier
-- population.
--
-- Distributions are reported as percentiles rather than just means because
-- lp_per_game in particular is heavy-tailed and its mean is close to useless
-- on its own.

with profile as (

    select
        *,
        coalesce(main_role, 'Unknown') as role
    from {{ ref('mart_player_profile') }}
    where tier is not null

)

select
    {{ dbt_utils.generate_surrogate_key(['as_of_date', 'tier', 'role']) }} as tier_role_date_id,
    as_of_date,
    tier,
    tier_order,
    role,

    -- population
    count(*) as player_count,
    count(case when is_active then 1 end) as active_player_count,
    {{ dbt_utils.safe_divide('count(case when is_active then 1 end)', 'count(*)') }} as active_share,

    -- pool size and concentration
    avg(active_champion_count) as avg_pool_size,
    percentile(active_champion_count, 0.5) as median_pool_size,
    percentile(active_champion_count, 0.9) as p90_pool_size,
    avg(pool_top1_share) as avg_pool_top1_share,
    avg(pool_hhi) as avg_pool_hhi,
    avg(pool_normalized_entropy) as avg_pool_normalized_entropy,
    avg(mastery_hhi) as avg_mastery_hhi,
    avg(log_total_mastery) as avg_log_total_mastery,
    avg(mastery_points_per_day) as avg_mastery_points_per_day,
    percentile(days_since_last_play, 0.5) as median_days_since_last_play,

    -- role commitment
    avg(main_role_weight) as avg_main_role_weight,
    avg(role_purity) as avg_role_purity,
    count(case when is_flex then 1 end) as flex_player_count,
    {{ dbt_utils.safe_divide('count(case when is_flex then 1 end)', 'count(main_role_weight)') }} as flex_share,

    -- LP rate distribution (trailing form window)
    count(lp_per_game) as lp_per_game_player_count,
    avg(lp_per_game) as avg_lp_per_game,
    stddev(lp_per_game) as stddev_lp_per_game,
    percentile(lp_per_game, 0.1) as p10_lp_per_game,
    percentile(lp_per_game, 0.25) as p25_lp_per_game,
    percentile(lp_per_game, 0.5) as median_lp_per_game,
    percentile(lp_per_game, 0.75) as p75_lp_per_game,
    percentile(lp_per_game, 0.9) as p90_lp_per_game,
    avg(lp_per_day) as avg_lp_per_day,
    percentile(lp_per_day, 0.5) as median_lp_per_day,
    avg(games_per_day) as avg_games_per_day,

    -- win rate distribution (trailing window, then lifetime)
    count(win_rate_recent) as win_rate_recent_player_count,
    avg(win_rate_recent) as avg_win_rate_recent,
    stddev(win_rate_recent) as stddev_win_rate_recent,
    percentile(win_rate_recent, 0.1) as p10_win_rate_recent,
    percentile(win_rate_recent, 0.25) as p25_win_rate_recent,
    percentile(win_rate_recent, 0.5) as median_win_rate_recent,
    percentile(win_rate_recent, 0.75) as p75_win_rate_recent,
    percentile(win_rate_recent, 0.9) as p90_win_rate_recent,
    avg(win_rate) as avg_win_rate_lifetime,
    percentile(win_rate, 0.5) as median_win_rate_lifetime,

    -- ladder position
    avg(absolute_lp) as avg_absolute_lp,
    percentile(absolute_lp, 0.5) as median_absolute_lp,
    avg(total_games) as avg_total_games,
    percentile(total_games, 0.5) as median_total_games

from profile
group by as_of_date, tier, tier_order, role
