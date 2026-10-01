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
        champion_key,
        cohort_playstyle as playstyle,
        count(*) as observed_player_count,
        sum(observed_period_count) as observed_period_count,
        sum(attributed_games) as attributed_games,
        avg(player_win_rate) as observed_win_rate,
        avg(player_lp_per_game) as expected_lp_per_game,
        avg(player_lp_per_day) as expected_lp_per_day,
        avg(median_lp_per_game_lift_vs_tier) as climbing_efficiency,
        avg(player_avg_end_rank_score) as avg_end_rank_score,
        percentile(player_median_end_rank_score, 0.5) as median_end_rank_score
    from {{ ref('fct_players_champion_growth_summary') }}
    where cohort_scope = 'champion_playstyle'
    group by champion_key, cohort_playstyle

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
    coalesce(gm.attributed_games, 0) as attributed_games,
    coalesce(gm.attributed_games, 0) as observed_games,
    gm.observed_win_rate,
    gm.expected_lp_per_game,
    gm.expected_lp_per_day,
    gm.climbing_efficiency,
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
