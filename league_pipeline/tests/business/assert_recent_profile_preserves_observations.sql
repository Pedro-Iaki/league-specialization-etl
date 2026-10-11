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
where not (p.games_recent <=> r.games_delta)
   or not (p.win_rate_recent <=> r.wins_delta / nullif(r.games_delta, 0))
   or not (p.games_per_day_recent <=> r.games_delta / nullif(r.period_in_days, 0))
   or not (p.lp_per_game_recent <=> case when {{ lp_growth_eligible('r.lp_delta', 'r.games_delta') }}
        then r.lp_delta / nullif(r.games_delta, 0) end)
