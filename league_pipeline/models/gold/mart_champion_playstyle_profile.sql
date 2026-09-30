{{ config(materialized='table', file_format='delta') }}

with as_of as (

    select max(as_of_date) as as_of_date
    from {{ ref('mart_player_profile') }}

),

current_metrics as (

    select
        active_primary_champion_key as champion_key,
        active_playstyle as playstyle,
        count(*) as current_player_count,
        count(lp_per_game_recent) as recent_form_player_count,
        avg(rank_score) as avg_current_rank_score,
        percentile(rank_score, 0.5) as median_current_rank_score,
        avg(lp_per_game_recent) as avg_recent_lp_per_game,
        avg(win_rate_recent) as avg_recent_win_rate
    from {{ ref('mart_player_profile') }}
    where active_primary_champion_key is not null
      and active_playstyle is not null
    group by active_primary_champion_key, active_playstyle

),

growth_metrics as (

    select
        primary_champion_key as champion_key,
        playstyle,
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
      and playstyle is not null
      and games_delta > 0
    group by primary_champion_key, playstyle

),

observed_groups as (

    select champion_key, playstyle from current_metrics
    union
    select champion_key, playstyle from growth_metrics

)

select
    {{ dbt_utils.generate_surrogate_key(['g.champion_key', 'g.playstyle']) }} as champion_playstyle_id,
    ao.as_of_date,
    g.champion_key,
    c.name as champion_name,
    g.playstyle,

    coalesce(cm.current_player_count, 0) as current_player_count,
    coalesce(cm.recent_form_player_count, 0) as recent_form_player_count,
    cm.avg_current_rank_score,
    cm.median_current_rank_score,
    cm.avg_recent_lp_per_game,
    cm.avg_recent_win_rate,

    coalesce(gm.observed_player_count, 0) as observed_player_count,
    coalesce(gm.observed_period_count, 0) as observed_period_count,
    coalesce(gm.observed_games, 0) as observed_games,
    gm.observed_win_rate,
    gm.expected_lp_per_game,
    gm.expected_lp_per_day,
    gm.lp_per_game_lift_vs_tier,
    gm.avg_end_rank_score,
    gm.median_end_rank_score
from observed_groups g
cross join as_of ao
inner join {{ ref('dim_champions') }} c on g.champion_key = c.key
left join current_metrics cm
    on g.champion_key = cm.champion_key
    and g.playstyle = cm.playstyle
left join growth_metrics gm
    on g.champion_key = gm.champion_key
    and g.playstyle = gm.playstyle
