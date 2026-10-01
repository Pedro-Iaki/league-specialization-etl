{{ config(materialized='table', file_format='delta') }}

with naive_roles as (

    select
        player_id,
        primary_roles,
        champions_sampled_count
    from {{ ref('dim_players_naive_role_distribution') }}

),

latest_period as (

    select max(period_bucket_start) as period_bucket_start
    from {{ ref('fct_players_rank_periods') }}

),

recent_form as (

    select
        r.player_id,
        r.queue,
        r.period_bucket_days as window_days,
        r.period_in_days as days_covered,
        r.games_delta as games,
        r.lp_delta,
        {{ dbt_utils.safe_divide('r.wins_delta', 'r.games_delta') }} as win_rate,
        {{ dbt_utils.safe_divide('r.lp_delta', 'r.games_delta') }} as lp_per_game,
        {{ dbt_utils.safe_divide('r.lp_delta', 'r.period_in_days') }} as lp_per_day,
        {{ dbt_utils.safe_divide('r.games_delta', 'r.period_in_days') }} as games_per_day
    from {{ ref('fct_players_rank_periods') }} r
    inner join latest_period l
        on r.period_bucket_start = l.period_bucket_start

)

select
    p.puuid as player_id,
    coalesce(pool.as_of_date, m.as_of_date, p.snapshot_date) as as_of_date,
    p.snapshot_date,
    p.region,
    p.queue,
    p.patch,
    p.tier,
    {{ tier_order('p.tier') }} as tier_order,
    p.division,
    p.league_points,
    {{ rank_score('p.tier', 'p.division', 'p.league_points') }} as rank_score,
    p.total_games,
    p.win_rate,

    f.window_days as form_window_days,
    f.games as games_recent,
    f.lp_delta as lp_delta_recent,
    f.win_rate as win_rate_recent,
    f.lp_per_game as lp_per_game_recent,
    f.lp_per_day as lp_per_day_recent,
    f.games_per_day as games_per_day_recent,
    f.days_covered as form_days_covered,

    pool.role_top_pct,
    pool.role_jungle_pct,
    pool.role_middle_pct,
    pool.role_bottom_pct,
    pool.role_support_pct,
    pool.role_purity,
    pool.main_role,
    pool.main_role_weight,
    n.primary_roles as metadata_primary_roles,
    n.champions_sampled_count as role_champions_sampled_count,

    pool.active_champion_count,
    pool.recent_total_points,
    pool.primary_champion_key as active_primary_champion_key,
    pool.primary_champion_name as active_primary_champion_name,
    pool.playstyle as active_playstyle,
    pool.pool_top1_share as active_top1_share,
    pool.pool_favoured_champion_count as active_favoured_champion_count,
    pool.pool_favoured_champions_share as active_favoured_champions_share,
    pool.pool_hhi as active_hhi,
    pool.pool_normalized_entropy as active_normalized_entropy,
    pool.active_champion_names,

    m.champions_with_mastery,
    m.total_mastery_points,
    m.top_champion_key,
    m.top_champion_name,
    m.mastery_top1_share as alltime_top1_share,
    m.mastery_favoured_champion_count as alltime_favoured_champion_count,
    m.mastery_favoured_champions_share as alltime_favoured_champions_share,
    m.mastery_hhi as alltime_hhi,
    m.mastery_normalized_entropy as alltime_normalized_entropy,
    m.mastery_playstyle as alltime_playstyle,
    m.mastery_points_per_day as alltime_points_per_day,
    m.days_since_last_play,
    m.days_tracked
from {{ ref('dim_players_current') }} p
left join {{ ref('dim_players_active_pool') }} pool
    on p.puuid = pool.player_id
left join {{ ref('fct_players_mastery_profile') }} m
    on p.puuid = m.player_id
left join recent_form f
    on p.puuid = f.player_id
    and p.queue = f.queue
left join naive_roles n on p.puuid = n.player_id
