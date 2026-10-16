-- LP plausibility must not erase independently valid games or win-rate observations.
with latest as (
    select max(period_bucket_start) as period_bucket_start
    from {{ ref('fct_players_rank_periods') }}
), recent as (
    select r.* from {{ ref('fct_players_rank_periods') }} r
    join latest l on r.period_bucket_start = l.period_bucket_start
)
select p.player_id, p.queue
from {{ ref('mart_player_profile') }} p
join recent r on p.player_id = r.player_id and p.queue = r.queue
where not (p.latest_rank_period_games <=> r.games_delta)
   or not (p.latest_rank_period_win_rate <=> r.wins_delta / nullif(r.games_delta, 0))
   or not (p.latest_rank_period_games_per_day <=> r.games_delta / nullif(r.period_in_days, 0))
   or not (p.latest_rank_period_lp_per_game <=> case when {{ lp_growth_eligible('r.lp_delta', 'r.games_delta') }}
        then r.lp_delta / nullif(r.games_delta, 0) end)
