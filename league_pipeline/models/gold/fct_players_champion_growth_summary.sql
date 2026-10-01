{{ config(materialized='table', file_format='delta') }}

with scoped as (

    select
        g.*,
        'champion' as cohort_scope,
        cast(null as string) as starting_tier,
        cast(null as string) as cohort_playstyle
    from {{ ref('fct_players_period_champion_growth') }} g

    union all

    select
        g.*,
        'champion_playstyle' as cohort_scope,
        cast(null as string) as starting_tier,
        g.playstyle as cohort_playstyle
    from {{ ref('fct_players_period_champion_growth') }} g
    where g.playstyle is not null

    union all

    select
        g.*,
        'champion_tier' as cohort_scope,
        g.previous_tier as starting_tier,
        cast(null as string) as cohort_playstyle
    from {{ ref('fct_players_period_champion_growth') }} g
    where g.previous_tier is not null

    union all

    select
        g.*,
        'champion_tier_playstyle' as cohort_scope,
        g.previous_tier as starting_tier,
        g.playstyle as cohort_playstyle
    from {{ ref('fct_players_period_champion_growth') }} g
    where g.previous_tier is not null and g.playstyle is not null

),

ordered as (

    select
        *,
        sum(attribution_share) over (
            partition by cohort_scope, player_id, champion_key, starting_tier, cohort_playstyle
            order by lp_per_game_lift_vs_tier, rank_period_id
            rows between unbounded preceding and current row
        ) as cumulative_share,
        sum(attribution_share) over (
            partition by cohort_scope, player_id, champion_key, starting_tier, cohort_playstyle
        ) as total_share
    from scoped

),

player_medians as (

    select
        cohort_scope,
        player_id,
        champion_key,
        starting_tier,
        cohort_playstyle,
        lp_per_game_lift_vs_tier as median_lp_per_game_lift_vs_tier
    from ordered
    where cumulative_share >= total_share / 2
    qualify row_number() over (
        partition by cohort_scope, player_id, champion_key, starting_tier, cohort_playstyle
        order by lp_per_game_lift_vs_tier, rank_period_id
    ) = 1

),

player_outcomes as (

    select
        cohort_scope,
        player_id,
        champion_key,
        starting_tier,
        cohort_playstyle,
        count(*) as observed_period_count,
        sum(attributed_games) as attributed_games,
        avg(attribution_share) as player_mean_champion_share,
        avg(pool_hhi) as player_mean_pool_hhi,
        avg(pool_top1_share) as player_mean_pool_top1_share,
        {{ dbt_utils.safe_divide('sum(attributed_wins)', 'sum(attributed_games)') }}
            as player_win_rate,
        {{ dbt_utils.safe_divide('sum(attributed_lp_delta)', 'sum(attributed_games)') }}
            as player_lp_per_game,
        {{ dbt_utils.safe_divide(
            'sum(attributed_lp_delta)',
            'sum(attribution_share * period_in_days)'
        ) }} as player_lp_per_day,
        avg(end_rank_score) as player_avg_end_rank_score,
        percentile(end_rank_score, 0.5) as player_median_end_rank_score
    from scoped
    group by cohort_scope, player_id, champion_key, starting_tier, cohort_playstyle

)

select
    {{ dbt_utils.generate_surrogate_key([
        'p.cohort_scope', 'p.player_id', 'p.champion_key',
        'p.starting_tier', 'p.cohort_playstyle'
    ]) }} as player_champion_growth_id,
    p.*,
    m.median_lp_per_game_lift_vs_tier
from player_outcomes p
inner join player_medians m
    on p.cohort_scope = m.cohort_scope
    and p.player_id = m.player_id
    and p.champion_key = m.champion_key
    and p.starting_tier <=> m.starting_tier
    and p.cohort_playstyle <=> m.cohort_playstyle
