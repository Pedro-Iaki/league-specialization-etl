{% macro champion_player_growth(include_playstyle=false) %}
-- One player/champion/starting-tier vote, optionally within observed rank_period_playstyle.
-- Derive each cohort from periods; do not combine precomputed subgroup medians.
with selected as (
    select g.*,
        previous_tier as starting_tier,
        {% if include_playstyle %}rank_period_playstyle{% else %}cast(null as string){% endif %} as cohort_playstyle
    from {{ ref('fct_players_period_champion_growth') }} g
    where previous_tier is not null
    {% if include_playstyle %}and rank_period_playstyle is not null{% endif %}
), ordered as (
    select *,
        sum(attribution_share) over (
            partition by region, queue, player_id, champion_key, starting_tier, cohort_playstyle
            order by lp_per_game_lift_vs_tier, rank_period_id
            rows between unbounded preceding and current row
        ) as cumulative_share,
        sum(attribution_share) over (
            partition by region, queue, player_id, champion_key, starting_tier, cohort_playstyle
        ) as total_share
    from selected
), median_candidates as (
    select region, queue, player_id, champion_key, starting_tier, cohort_playstyle,
        lp_per_game_lift_vs_tier as median_lp_per_game_lift_vs_tier,
        row_number() over (
            partition by region, queue, player_id, champion_key, starting_tier, cohort_playstyle
            order by lp_per_game_lift_vs_tier, rank_period_id
        ) as median_rank
    from ordered
    where cumulative_share >= total_share / 2
), medians as (
    select * from median_candidates where median_rank = 1
), outcomes as (
    select region, queue, player_id, champion_key, starting_tier, cohort_playstyle,
        count(*) as observed_period_count,
        sum(attributed_games) as attributed_games,
        avg(attribution_share) as player_mean_champion_share,
        avg(rank_period_hhi) as player_mean_rank_period_hhi,
        avg(rank_period_top1_share) as player_mean_rank_period_top1_share,
        sum(attributed_wins) / nullif(sum(attributed_games), 0) as player_win_rate,
        sum(attributed_lp_delta) / nullif(sum(attributed_games), 0) as player_lp_per_game,
        sum(attributed_lp_delta) / nullif(sum(attribution_share * period_in_days), 0) as player_lp_per_day,
        avg(end_rank_score) as player_avg_end_rank_score
    from selected
    group by region, queue, player_id, champion_key, starting_tier, cohort_playstyle
)
select p.*, m.median_lp_per_game_lift_vs_tier
from outcomes p
join medians m
    on p.region <=> m.region and p.queue <=> m.queue
   and p.player_id = m.player_id and p.champion_key = m.champion_key
   and p.starting_tier = m.starting_tier and p.cohort_playstyle <=> m.cohort_playstyle
{% endmacro %}

{% macro champion_tier_growth(include_playstyle=false) %}
with player_growth as (
    {{ champion_player_growth(include_playstyle) }}
)
select p.region, p.queue, p.champion_key, c.name as champion_name,
    p.starting_tier, p.cohort_playstyle as rank_period_playstyle,
    '{% if include_playstyle %}champion_tier_playstyle{% else %}champion_tier{% endif %}' as cohort_scope,
    count(*) as observed_player_tier_count,
    sum(observed_period_count) as observed_period_count,
    sum(attributed_games) as attributed_games,
    avg(player_mean_champion_share) as mean_commitment,
    avg(player_mean_rank_period_hhi) as mean_rank_period_hhi,
    avg(player_win_rate) as observed_win_rate,
    avg(player_lp_per_game) as expected_lp_per_game,
    avg(player_lp_per_day) as expected_lp_per_day,
    avg(median_lp_per_game_lift_vs_tier) as climbing_efficiency
from player_growth p
join {{ ref('dim_champions') }} c on p.champion_key = c.key
group by p.region, p.queue, p.champion_key, c.name, p.starting_tier, p.cohort_playstyle
{% endmacro %}
