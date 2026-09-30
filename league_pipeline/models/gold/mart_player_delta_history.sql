{{ config(materialized='table', file_format='delta') }}

with periods as (

    select * except(is_counter_reset)
    from {{ ref('fct_players_rank_history') }}
    where not is_counter_reset

),

enriched as (

    select
        r.*,
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
    from periods r
    left join {{ ref('fct_players_period_pool_profile') }} p
        on r.rank_delta_id = p.rank_delta_id

),

tier_baselines as (

    select
        queue,
        previous_tier,
        {{ dbt_utils.safe_divide('sum(lp_delta)', 'sum(games_delta)') }}
            as tier_lp_per_game_baseline
    from enriched
    where games_delta > 0
    group by queue, previous_tier

)

select
    e.*,
    b.tier_lp_per_game_baseline,
    {{ dbt_utils.safe_divide('e.lp_delta', 'e.games_delta') }} as lp_per_game,
    {{ dbt_utils.safe_divide('e.lp_delta', 'e.period_in_days') }} as lp_per_day,
    {{ dbt_utils.safe_divide('e.wins_delta', 'e.games_delta') }} as period_win_rate,
    {{ dbt_utils.safe_divide('e.lp_delta', 'e.games_delta') }}
        - b.tier_lp_per_game_baseline as lp_per_game_lift_vs_tier
from enriched e
left join tier_baselines b
    on e.queue = b.queue
    and e.previous_tier <=> b.previous_tier
