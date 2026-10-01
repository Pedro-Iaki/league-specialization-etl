{{ config(materialized='table', file_format='delta') }}

select
    p.rank_period_id,
    p.player_id,
    p.queue,
    p.previous_tier,
    p.period_bucket_start,
    p.period_in_days,
    p.playstyle,
    p.rank_score as end_rank_score,
    a.champion_key,
    a.champion_name,
    a.points_gained,
    a.points_rank,
    a.champion_share as attribution_share,
    p.games_delta,
    p.wins_delta,
    p.lp_delta,
    p.tier_lp_per_game_baseline,
    p.lp_per_game,
    p.lp_per_day,
    p.period_win_rate,
    p.lp_per_game_lift_vs_tier,
    p.pool_hhi,
    p.pool_top1_share,
    p.estimated_ranked_mastery_share,
    a.champion_share * p.games_delta as attributed_games,
    a.champion_share * p.wins_delta as attributed_wins,
    a.champion_share * p.lp_delta as attributed_lp_delta,
    a.champion_share
        * (p.lp_delta - p.tier_lp_per_game_baseline * p.games_delta)
        as attributed_excess_lp
from {{ ref('fct_players_period_champion_activity') }} a
inner join {{ ref('mart_player_delta_history') }} p
    on a.rank_period_id = p.rank_period_id
where a.is_favoured
  and p.is_lp_growth_eligible
  and p.tier_lp_per_game_baseline is not null
