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

latest_rank_period as (

    select
        r.player_id,
        r.queue,
        r.period_bucket_days as window_days,
        r.period_in_days as days_covered,
        r.games_delta as games,
        case when {{ lp_growth_eligible('r.lp_delta', 'r.games_delta') }} then r.lp_delta end as lp_delta,
        {{ dbt_utils.safe_divide('r.wins_delta', 'r.games_delta') }} as win_rate,
        case when {{ lp_growth_eligible('r.lp_delta', 'r.games_delta') }} then
            {{ dbt_utils.safe_divide('r.lp_delta', 'r.games_delta') }} end as lp_per_game,
        case when {{ lp_growth_eligible('r.lp_delta', 'r.games_delta') }} then
            {{ dbt_utils.safe_divide('r.lp_delta', 'r.period_in_days') }} end as lp_per_day,
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

    f.window_days as latest_rank_period_window_days,
    f.games as latest_rank_period_games,
    f.lp_delta as latest_rank_period_lp_delta,
    f.win_rate as latest_rank_period_win_rate,
    f.lp_per_game as latest_rank_period_lp_per_game,
    f.lp_per_day as latest_rank_period_lp_per_day,
    f.games_per_day as latest_rank_period_games_per_day,
    f.days_covered as latest_rank_period_days_covered,

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

    pool.recent_champion_count,
    pool.recent_mastery_points,
    pool.primary_champion_key as recent_primary_champion_key,
    pool.primary_champion_name as recent_primary_champion_name,
    pool.recent_playstyle as recent_playstyle,
    pool.recent_top1_share as recent_top1_share,
    pool.recent_favoured_champion_count as recent_favoured_champion_count,
    pool.recent_favoured_champions_share as recent_favoured_champions_share,
    pool.recent_hhi as recent_hhi,
    pool.recent_normalized_entropy as recent_normalized_entropy,
    pool.recent_champion_names,

    m.lifetime_champion_count,
    m.lifetime_mastery_points,
    m.lifetime_primary_champion_key,
    m.lifetime_primary_champion_name,
    m.lifetime_top1_share as lifetime_top1_share,
    m.lifetime_favoured_champion_count as lifetime_favoured_champion_count,
    m.lifetime_favoured_champions_share as lifetime_favoured_champions_share,
    m.lifetime_hhi as lifetime_hhi,
    m.lifetime_normalized_entropy as lifetime_normalized_entropy,
    m.lifetime_playstyle as lifetime_playstyle,
    m.tracked_mastery_points_per_day as tracked_mastery_points_per_day,
    m.days_since_last_play,
    m.days_tracked
from {{ ref('dim_players_current') }} p
left join {{ ref('dim_players_recent_pool') }} pool
    on p.puuid = pool.player_id
left join {{ ref('fct_players_lifetime_mastery_profile') }} m
    on p.puuid = m.player_id
left join latest_rank_period f
    on p.puuid = f.player_id
    and p.queue = f.queue
left join naive_roles n on p.puuid = n.player_id
