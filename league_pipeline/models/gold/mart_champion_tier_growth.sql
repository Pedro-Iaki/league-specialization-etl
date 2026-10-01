{{ config(materialized='table', file_format='delta') }}

with growth as (

    select
        champion_key,
        starting_tier,
        cohort_playstyle as playstyle,
        cohort_scope,
        count(*) as observed_player_count,
        sum(observed_period_count) as observed_period_count,
        sum(attributed_games) as attributed_games,
        avg(player_mean_champion_share) as mean_commitment,
        avg(player_mean_pool_hhi) as mean_pool_hhi,
        avg(player_win_rate) as observed_win_rate,
        avg(player_lp_per_game) as expected_lp_per_game,
        avg(player_lp_per_day) as expected_lp_per_day,
        avg(median_lp_per_game_lift_vs_tier) as climbing_efficiency
    from {{ ref('fct_players_champion_growth_summary') }}
    where cohort_scope in ('champion_tier', 'champion_tier_playstyle')
    group by champion_key, starting_tier, cohort_playstyle, cohort_scope

)

select
    {{ dbt_utils.generate_surrogate_key([
        'g.champion_key', 'g.starting_tier', 'g.playstyle', 'g.cohort_scope'
    ]) }} as champion_tier_growth_id,
    g.champion_key,
    c.name as champion_name,
    g.starting_tier,
    g.playstyle,
    g.cohort_scope,
    g.observed_player_count,
    g.observed_period_count,
    g.attributed_games,
    g.mean_commitment,
    g.mean_pool_hhi,
    g.observed_win_rate,
    g.expected_lp_per_game,
    g.expected_lp_per_day,
    g.climbing_efficiency
from growth g
inner join {{ ref('dim_champions') }} c on g.champion_key = c.key
