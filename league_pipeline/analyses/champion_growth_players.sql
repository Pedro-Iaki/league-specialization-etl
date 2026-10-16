
with player_growth as (
    {{ champion_player_growth() }}
)
select c.name as champion_name, p.champion_key, p.starting_tier,
    p.player_mean_champion_share as champion_commitment,
    p.player_mean_rank_period_hhi as specialization_hhi,
    p.player_mean_rank_period_top1_share as top_champion_share,
    p.median_lp_per_game_lift_vs_tier as climbing_efficiency,
    p.player_win_rate as win_rate,
    p.observed_period_count as period_count,
    p.attributed_games, p.player_avg_end_rank_score as end_rank_score,
    p.region, p.queue
from player_growth p
join {{ ref('dim_champions') }} c on p.champion_key = c.key
