with growth as (

    select
        rank_period_id,
        sum(attribution_share) as attributed_share,
        sum(attributed_games) as attributed_games,
        sum(attributed_wins) as attributed_wins,
        sum(attributed_lp_delta) as attributed_lp_delta,
        sum(attributed_excess_lp) as attributed_excess_lp
    from {{ ref('fct_players_period_champion_growth') }}
    group by rank_period_id

)

select g.rank_period_id
from growth g
inner join {{ ref('mart_player_delta_history') }} p
    on g.rank_period_id = p.rank_period_id
where abs(g.attributed_share - p.pool_favoured_champions_share) > 0.000001
   or abs(g.attributed_games - g.attributed_share * p.games_delta) > 0.000001
   or abs(g.attributed_wins - g.attributed_share * p.wins_delta) > 0.000001
   or abs(g.attributed_lp_delta - g.attributed_share * p.lp_delta) > 0.000001
   or abs(
       g.attributed_excess_lp
       - g.attributed_share * (p.lp_delta - p.tier_lp_per_game_baseline * p.games_delta)
   ) > 0.000001
