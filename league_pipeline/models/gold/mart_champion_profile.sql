{{ config(materialized='table', file_format='delta') }}

{% set expert_threshold = var('expert_mastery_threshold', 100000) %}

with as_of as (

    select max(as_of_date) as as_of_date
    from {{ ref('mart_player_profile') }}

),

current_activity as (

    select
        champion_key,
        player_id,
        recent_share
    from {{ ref('fct_players_champion_activity') }}
    where is_active

),

active_population as (

    select count(distinct player_id) as player_count
    from current_activity

),

activity_metrics as (

    select
        champion_key,
        count(distinct player_id) as active_player_count,
        avg(recent_share) as avg_active_pool_share
    from current_activity
    group by champion_key

),

primary_player_metrics as (

    select
        active_primary_champion_key as champion_key,
        count(*) as primary_player_count,
        count(lp_per_game_recent) as recent_form_player_count,
        avg(rank_score) as avg_current_rank_score,
        percentile(rank_score, 0.5) as median_current_rank_score,
        avg(lp_per_game_recent) as avg_recent_lp_per_game,
        avg(win_rate_recent) as avg_recent_win_rate
    from {{ ref('mart_player_profile') }}
    where active_primary_champion_key is not null
    group by active_primary_champion_key

),

growth_metrics as (

    select
        primary_champion_key as champion_key,
        count(distinct player_id) as observed_player_count,
        count(*) as observed_period_count,
        sum(games_delta) as observed_games,
        {{ dbt_utils.safe_divide('sum(wins_delta)', 'sum(games_delta)') }} as observed_win_rate,
        {{ dbt_utils.safe_divide('sum(lp_delta)', 'sum(games_delta)') }} as expected_lp_per_game,
        {{ dbt_utils.safe_divide('sum(lp_delta)', 'sum(period_in_days)') }} as expected_lp_per_day,
        {{ dbt_utils.safe_divide(
            'sum(lp_per_game_lift_vs_tier * games_delta)',
            'sum(case when lp_per_game_lift_vs_tier is not null then games_delta end)'
        ) }} as lp_per_game_lift_vs_tier,
        avg(rank_score) as avg_end_rank_score,
        percentile(rank_score, 0.5) as median_end_rank_score
    from {{ ref('mart_player_delta_history') }}
    where primary_champion_key is not null
      and games_delta > 0
    group by primary_champion_key

),

mastery_metrics as (

    select
        champion_key,
        count(*) as mastery_player_count,
        count(case when champion_points >= {{ expert_threshold }} then 1 end) as expert_player_count,
        avg(champion_points) as avg_mastery_points,
        percentile(champion_points, 0.5) as median_mastery_points
    from {{ ref('fct_masteries_current') }}
    group by champion_key

)

select
    c.key as champion_key,
    c.name as champion_name,
    c.patch as champion_patch,
    c.expected_positions,
    ao.as_of_date,

    coalesce(a.active_player_count, 0) as active_player_count,
    p.player_count as active_pool_player_count,
    {{ dbt_utils.safe_divide('coalesce(a.active_player_count, 0)', 'p.player_count') }} as active_play_rate,
    a.avg_active_pool_share,

    coalesce(pp.primary_player_count, 0) as primary_player_count,
    coalesce(pp.recent_form_player_count, 0) as recent_form_player_count,
    pp.avg_current_rank_score,
    pp.median_current_rank_score,
    pp.avg_recent_lp_per_game,
    pp.avg_recent_win_rate,

    coalesce(g.observed_player_count, 0) as observed_player_count,
    coalesce(g.observed_period_count, 0) as observed_period_count,
    coalesce(g.observed_games, 0) as observed_games,
    g.observed_win_rate,
    g.expected_lp_per_game,
    g.expected_lp_per_day,
    g.lp_per_game_lift_vs_tier,
    g.avg_end_rank_score,
    g.median_end_rank_score,

    coalesce(m.mastery_player_count, 0) as mastery_player_count,
    coalesce(m.expert_player_count, 0) as expert_player_count,
    {{ dbt_utils.safe_divide('m.expert_player_count', 'm.mastery_player_count') }} as expert_player_share,
    m.avg_mastery_points,
    m.median_mastery_points,

    coalesce(w.player_count, 0) as role_sample_player_count,
    w.avg_top_pct as role_top_pct,
    w.avg_jungle_pct as role_jungle_pct,
    w.avg_middle_pct as role_middle_pct,
    w.avg_bottom_pct as role_bottom_pct,
    w.avg_support_pct as role_support_pct
from {{ ref('dim_champions') }} c
cross join as_of ao
cross join active_population p
left join activity_metrics a on c.key = a.champion_key
left join primary_player_metrics pp on c.key = pp.champion_key
left join growth_metrics g on c.key = g.champion_key
left join mastery_metrics m on c.key = m.champion_key
left join {{ ref('dim_champion_role_weights') }} w on c.key = w.champion_key
