{{ config(materialized='table', file_format='delta') }}

with periods as (

    select
        r.rank_period_id,
        r.player_id,
        r.region,
        r.queue,
        r.previous_tier,
        r.previous_division,
        r.previous_league_points,
        r.previous_rank_score,
        r.tier,
        r.division,
        r.league_points,
        r.rank_score,
        r.previous_snapshot_date,
        r.snapshot_date,
        r.period_bucket_start,
        r.period_bucket_end,
        r.period_bucket_days,
        r.period_in_days,
        r.wins_delta,
        r.losses_delta,
        r.games_delta,
        r.lp_delta,
        p.champion_count,
        p.mastery_points_gained,
        p.primary_champion_key,
        p.primary_champion_name,
        p.primary_champion_points,
        p.top1_share as pool_top1_share,
        p.favoured_champion_count as pool_favoured_champion_count,
        p.favoured_champions_share as pool_favoured_champions_share,
        p.hhi as pool_hhi,
        p.normalized_entropy as pool_normalized_entropy,
        p.playstyle
    from {{ ref('fct_players_rank_periods') }} r
    left join {{ ref('fct_players_period_pool_profile') }} p
        on r.rank_period_id = p.rank_period_id

),

tier_baselines as (

    select
        queue,
        previous_tier,
        {{ dbt_utils.safe_divide('sum(lp_delta)', 'sum(games_delta)') }}
            as tier_lp_per_game_baseline
    from periods
    where games_delta > 0
    group by queue, previous_tier

)

select
    p.*,
    b.tier_lp_per_game_baseline,
    {{ dbt_utils.safe_divide('p.lp_delta', 'p.games_delta') }} as lp_per_game,
    {{ dbt_utils.safe_divide('p.lp_delta', 'p.period_in_days') }} as lp_per_day,
    {{ dbt_utils.safe_divide('p.wins_delta', 'p.games_delta') }} as period_win_rate,
    {{ dbt_utils.safe_divide('p.lp_delta', 'p.games_delta') }}
        - b.tier_lp_per_game_baseline as lp_per_game_lift_vs_tier
from periods p
left join tier_baselines b
    on p.queue = b.queue
    and p.previous_tier <=> b.previous_tier
